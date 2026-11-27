import json

import pytest

from scripts.export_dashboard import export, snapshot
from tests.conftest import WAREHOUSE_PATH


def test_public_export_reconciles_with_source_totals(con, tmp_path):
    if not con.execute("""
        SELECT count(*) FROM duckdb_tables()
        WHERE schema_name = 'marts' AND table_name = 'fct_channel_performance'
    """).fetchone()[0]:
        pytest.skip("build all three pipelines first")
    # CI intentionally holds back one file until the marketing backfill test.
    # Use the actual delivery state to test either side of the publication gate.
    missing = con.execute("""
        SELECT 3 * (SELECT count(*) FROM staging.stg_fx_rates)
               - count(DISTINCT (report_date, platform)) FROM staging.stg_ad_performance
    """).fetchone()[0]
    if missing:
        with pytest.raises(ValueError, match="Missing ad platform-days"):
            snapshot(con)
        return
    data = snapshot(con)
    expected = con.execute("""
        SELECT count(*), sum(total_amount) * 100 FROM staging.stg_orders
        WHERE status IN ('paid', 'shipped', 'delivered')
    """).fetchone()
    assert (sum(r['orders'] for r in data['sales']), sum(r['net'] for r in data['sales'])) == expected
    assert sum(r['gateway'] for r in data['reconciliation']) == con.execute(
        'SELECT count(*) FROM raw.gateway_txns').fetchone()[0]
    assert sum(r['ledger'] for r in data['reconciliation']) == con.execute(
        'SELECT count(*) FROM raw.ledger_entries').fetchone()[0]
    assert sum(r['spend'] for r in data['marketing']) == con.execute(
        'SELECT sum(spend_thb) * 100 FROM staging.stg_ad_performance').fetchone()[0]
    assert sum(r['revenue'] for r in data['marketing']) == con.execute(
        'SELECT sum(revenue_thb) * 100 FROM intermediate.int_attributed_revenue').fetchone()[0]
    assert sum(r['alerts'] for r in data['alerts']) == con.execute(
        'SELECT count(*) FROM recon.alerts').fetchone()[0]
    path = tmp_path / "snapshot.json"
    export(WAREHOUSE_PATH, path)
    first = path.read_bytes()
    export(WAREHOUSE_PATH, path)
    assert path.read_bytes() == first
    assert json.loads(first) == data


def test_committed_snapshot_has_only_public_aggregate_fields():
    from scripts.export_dashboard import DEFAULT_OUTPUT

    data = json.loads(DEFAULT_OUTPUT.read_text())
    schema = {
        "coverage": {"feed", "start", "finish", "days"},
        "sales": {"date", "channel", "orders", "net", "refunds"},
        "reconciliation": {"date", "gateway", "ledger", "matched", "gap"},
        "alerts": {"date", "severity", "rule", "alerts"},
        "marketing": {"date", "platform", "orders", "revenue", "spend"},
    }
    assert set(data) == set(schema) | {"synthetic", "version", "currency", "moneyUnit"}
    assert data["synthetic"] is True and data["moneyUnit"] == "satang"
    for section, columns in schema.items():
        assert all(set(r) == columns for r in data[section])
    assert {r["channel"] for r in data["sales"]} == {"web", "shopee", "lazada"}
    assert {r["platform"] for r in data["marketing"]} == {"facebook", "google", "tiktok", "organic"}
