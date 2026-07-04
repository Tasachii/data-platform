"""Warehouse-level reconciliation tests: 100% recall of injected mismatches
(the Gate-3 contract), completeness of the waterfall, alerting, idempotency.
"""

from __future__ import annotations

import json

import duckdb
import pytest

from pipelines.reconciliation.matching import run as run_recon
from tests.conftest import RAW_DIR, WAREHOUSE_PATH, one


@pytest.fixture(scope="session")
def payments_manifest() -> dict:
    path = RAW_DIR / "_payments_manifest.json"
    if not path.exists():
        pytest.skip("payments manifest missing (run generate_payments.py first)")
    return json.loads(path.read_text())


@pytest.fixture
def rcon(con):
    if not con.execute(
        "SELECT count(*) FROM duckdb_tables() WHERE schema_name = 'recon'"
    ).fetchone()[0]:
        pytest.skip("recon tables not built yet (run run_recon.py first)")
    return con


EXPECTED_BUCKET = {
    "missing_in_ledger": "missing_in_ledger",
    "missing_in_gateway": "missing_in_gateway",
    "rounding": "rounding",
    "fee_timing": "fee_timing",
}


@pytest.mark.parametrize("case", list(EXPECTED_BUCKET))
def test_recall_100pct_of_injected_mismatches(rcon, payments_manifest, case):
    injected = sorted(set(payments_manifest["edge_cases"][case]))
    bucket = EXPECTED_BUCKET[case]
    # manifest records order_ids for gateway-derived cases, raw refs for ghosts
    refs = [r.removeprefix("GW-").upper() for r in injected]
    detected = one(rcon, f"""
        SELECT count(*) FROM recon.recon_results
        WHERE match_type = '{bucket}' AND ref IN (SELECT unnest(?))""", [refs])
    assert detected == len(refs), (
        f"{case}: injected {len(refs)}, detected {detected} in bucket '{bucket}'"
    )


def test_recall_duplicate_postings(rcon, payments_manifest):
    injected = payments_manifest["edge_counts"]["duplicate_posting"]
    detected = one(rcon,
        "SELECT count(*) FROM recon.recon_results WHERE match_type = 'duplicate_posting'")
    assert detected == injected


def test_normalization_cases_still_match(rcon, payments_manifest):
    """Dirty currency and missing GW- prefix must NOT prevent matching."""
    for case in ("dirty_currency", "no_prefix_ref"):
        refs = [r.upper() for r in sorted(set(payments_manifest["edge_cases"][case]))]
        unmatched = one(rcon, """
            SELECT count(*) FROM recon.recon_results
            WHERE ref IN (SELECT unnest(?))
              AND match_type IN ('missing_in_ledger', 'missing_in_gateway')""", [refs])
        assert unmatched == 0, f"{case}: {unmatched} records failed to match"


def test_waterfall_completeness_no_record_left_behind(rcon):
    gw_total = one(rcon, "SELECT count(*) FROM raw.gateway_txns")
    led_total = one(rcon, "SELECT count(*) FROM raw.ledger_entries")
    gw_bucketed = one(rcon,
        "SELECT count(DISTINCT txn_id) FROM recon.recon_results WHERE txn_id IS NOT NULL")
    led_bucketed = one(rcon,
        "SELECT count(DISTINCT entry_id) FROM recon.recon_results WHERE entry_id IS NOT NULL")
    assert gw_bucketed == gw_total, f"{gw_total - gw_bucketed} gateway txns unaccounted"
    assert led_bucketed == led_total, f"{led_total - led_bucketed} ledger entries unaccounted"


def test_no_record_assigned_to_two_buckets(rcon):
    for id_col in ("txn_id", "entry_id"):
        doubles = one(rcon, f"""
            SELECT count(*) FROM (
                SELECT {id_col} FROM recon.recon_results
                WHERE {id_col} IS NOT NULL GROUP BY {id_col} HAVING count(*) > 1
            )""")
        assert doubles == 0, f"{doubles} {id_col}s landed in multiple buckets"


def test_summary_daily_buckets_sum_to_gateway_total(rcon):
    broken = one(rcon, """
        SELECT count(*) FROM recon.recon_summary
        WHERE matched + fee_timing + rounding + amount_other
              + possible_ref_issue + missing_in_ledger != gateway_count""")
    assert broken == 0


def test_alerts_fire_on_known_bad_days(rcon):
    warnings = one(rcon,
        "SELECT count(*) FROM recon.alerts WHERE severity = 'WARNING' AND rule = 'duplicate_posting'")
    assert warnings > 0, "617 duplicate postings were injected — WARNING must fire"
    criticals = one(rcon, "SELECT count(*) FROM recon.alerts WHERE severity = 'CRITICAL'")
    assert criticals > 0, "millions of THB go missing daily by design — CRITICAL must fire"


def test_matching_engine_rerun_is_idempotent():
    if not WAREHOUSE_PATH.exists():
        pytest.skip("warehouse not built yet")

    def checksum():
        c = duckdb.connect(str(WAREHOUSE_PATH), read_only=True)
        try:
            return c.execute("""
                SELECT count(*), sum(hash(CAST(t AS VARCHAR)))
                FROM recon.recon_results t""").fetchone()
        finally:
            c.close()

    before = checksum()
    run_recon()
    assert checksum() == before
