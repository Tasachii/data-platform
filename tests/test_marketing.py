"""Warehouse-level marketing attribution tests: spend conservation, recall of
injected edge cases, late-file behaviour, attribution completeness,
idempotency. Test order inside this file matters: late-file state is asserted
BEFORE the backfill test consumes it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date

import duckdb
import pytest

from pipelines.marketing import ingest as mkt_ingest
from tests.conftest import RAW_DIR, REPO_ROOT, WAREHOUSE_PATH, one


@pytest.fixture(scope="session")
def mkt_manifest() -> dict:
    path = RAW_DIR / "_marketing_manifest.json"
    if not path.exists():
        pytest.skip("marketing manifest missing (run generate_marketing.py first)")
    return json.loads(path.read_text())


@pytest.fixture
def mcon(con):
    if not one(con, """
        SELECT count(*) FROM duckdb_tables()
        WHERE schema_name = 'marts' AND table_name = 'fct_channel_performance'"""):
        pytest.skip("marketing marts not built yet (run run_marketing.py first)")
    return con


def test_spend_is_conserved_staging_to_marts(mcon):
    """เงินห้ามหาย: every satang of spend in staging reaches the mart."""
    stg = one(mcon, "SELECT COALESCE(SUM(spend_thb), 0) FROM staging.stg_ad_performance")
    fct = one(mcon, "SELECT COALESCE(SUM(spend_thb), 0) FROM marts.fct_channel_performance")
    assert abs(float(stg) - float(fct)) < 0.01, f"staging {stg} vs marts {fct}"


def test_google_duplicate_rows_collapse(mcon, mkt_manifest):
    dup_injected = mkt_manifest["edge_counts"]["google_duplicate_rows"]
    raw_google = one(mcon, "SELECT count(*) FROM raw.ad_performance WHERE platform = 'google'")
    stg_google = one(mcon, "SELECT count(*) FROM staging.stg_ad_performance WHERE platform = 'google'")
    assert raw_google - stg_google == dup_injected, (
        f"expected exactly {dup_injected} duplicate rows collapsed, "
        f"got {raw_google - stg_google}"
    )
    survivors = one(mcon, """
        SELECT count(*) FROM (
            SELECT report_date, campaign_name FROM staging.stg_ad_performance
            WHERE platform = 'google' GROUP BY 1, 2 HAVING count(*) > 1
        )""")
    assert survivors == 0


def test_na_conversions_flagged_not_dropped(mcon, mkt_manifest):
    # Manifest entries look like "tiktok|170490001|2026-06-30". An N/A row can
    # live inside a late file that hasn't been ingested yet — only rows from
    # DELIVERED files can possibly be flagged, so count against those.
    loaded_tiktok_dates = {
        str(r[0]) for r in mcon.execute(
            "SELECT DISTINCT report_date FROM staging.stg_ad_performance WHERE platform = 'tiktok'"
        ).fetchall()
    }
    late_undelivered = set(mkt_manifest["edge_cases"]["tiktok_late_dates"]) - loaded_tiktok_dates
    expected = sum(
        1 for entry in mkt_manifest["edge_cases"]["conversions_na_rows"]
        if not (entry.startswith("tiktok|") and entry.rsplit("|", 1)[1] in late_undelivered)
    )
    flagged = one(mcon, "SELECT count(*) FROM staging.stg_ad_performance WHERE conversions_missing")
    assert flagged == expected, (
        f"{expected} N/A rows delivered, {flagged} flagged "
        f"(undelivered late dates: {sorted(late_undelivered)})"
    )
    spend_kept = one(mcon, """
        SELECT count(*) FROM staging.stg_ad_performance
        WHERE conversions_missing AND spend_thb > 0""")
    assert spend_kept == flagged, "rows with N/A conversions still carry real spend"


def test_fb_zero_impression_ads_survive_without_poisoning_ratios(mcon, mkt_manifest):
    injected = mkt_manifest["edge_counts"]["fb_zero_impression_ads"]
    present = one(mcon, """
        SELECT count(*) FROM staging.stg_ad_performance
        WHERE platform = 'facebook' AND impressions = 0 AND spend_thb > 0""")
    assert present == injected
    broken_ratios = one(mcon, """
        SELECT count(*) FROM marts.fct_channel_performance
        WHERE NOT isfinite(COALESCE(roas, 0))
           OR NOT isfinite(COALESCE(cpc_thb, 0))
           OR NOT isfinite(COALESCE(cpa_thb, 0))
           OR NOT isfinite(COALESCE(ctr_pct, 0))""")
    assert broken_ratios == 0, "zero denominators must yield NULL, never Infinity"


def test_late_tiktok_file_is_a_gap_not_a_failure(mcon, mkt_manifest):
    """Late platform files are routine: the pipeline loads what exists and the
    gap is visible. Valid states: file still late (gap) or backfilled (no gap)."""
    late_dates = set(mkt_manifest["edge_cases"]["tiktok_late_dates"])
    loaded = {
        str(r[0]) for r in mcon.execute(
            "SELECT DISTINCT report_date FROM staging.stg_ad_performance WHERE platform = 'tiktok'"
        ).fetchall()
    }
    still_missing = late_dates - loaded
    assert still_missing in (late_dates, set()), (
        f"unexpected partial state: {still_missing}"
    )


def test_backfill_late_tiktok_file_fills_the_gap(mkt_manifest):
    """--include-late ingests from raw/late_arrivals/ and replaces the partition."""
    if not WAREHOUSE_PATH.exists():
        pytest.skip("warehouse not built yet")
    late_dates = [date.fromisoformat(d) for d in mkt_manifest["edge_cases"]["tiktok_late_dates"]]
    if not late_dates:
        pytest.skip("no late files in this manifest")

    mkt_ingest.ingest(late_dates, include_late=True)

    con = duckdb.connect(str(WAREHOUSE_PATH), read_only=True)
    try:
        for d in late_dates:
            rows = con.execute(
                "SELECT count(*) FROM raw.ad_performance "
                "WHERE platform = 'tiktok' AND report_date = ?", [str(d)]
            ).fetchone()[0]
            assert rows > 0, f"backfill did not land tiktok rows for {d}"
    finally:
        con.close()


def test_no_unmapped_utm_sources(mcon):
    unmapped = one(mcon, """
        SELECT count(*) FROM staging.stg_utm_touches
        WHERE platform IS NULL""")
    assert unmapped == 0, (
        f"{unmapped} utm_source variants unknown to the seed — "
        "extend dbt/seeds/utm_source_mapping.csv"
    )


def test_no_unmapped_campaigns(mcon):
    unmapped = one(mcon,
        "SELECT count(*) FROM intermediate.int_campaign_mapping WHERE is_unmapped")
    assert unmapped == 0, "extend dbt/seeds/campaign_canonical_mapping.csv"


def test_attribution_keeps_every_moneyed_touch(mcon):
    """Every touch whose order has a money status lands in attribution exactly
    once — organic included; nothing silently dropped."""
    expected = one(mcon, """
        SELECT count(*) FROM staging.stg_utm_touches t
        JOIN intermediate.int_orders_enriched e ON t.order_id = e.order_id
        WHERE e.status IN ('paid', 'shipped', 'delivered')""")
    actual = one(mcon, "SELECT count(*) FROM intermediate.int_attributed_revenue")
    assert actual == expected
    organic = one(mcon,
        "SELECT count(*) FROM intermediate.int_attributed_revenue WHERE platform = 'organic'")
    assert organic > 0, "organic bucket must exist"


def test_marketing_rerun_is_idempotent(mkt_manifest):
    if not WAREHOUSE_PATH.exists():
        pytest.skip("warehouse not built yet")

    tables = {
        "raw.ad_performance": "* EXCLUDE (_ingested_at)",
        "raw.utm_touches": "* EXCLUDE (_ingested_at)",
        "staging.stg_ad_performance": "*",
        "marts.fct_channel_performance": "*",
        "marts.fct_campaign_performance": "*",
    }

    def checksums():
        c = duckdb.connect(str(WAREHOUSE_PATH), read_only=True)
        try:
            return {
                t: c.execute(f"SELECT count(*), sum(hash(CAST(t AS VARCHAR))) "
                             f"FROM (SELECT {proj} FROM {t}) t").fetchone()
                for t, proj in tables.items()
            }
        finally:
            c.close()

    def run_pipeline():
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "pipelines/marketing/run_marketing.py"), "--all"],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        assert result.returncode == 0, f"marketing run failed:\n{result.stderr[-2000:]}"

    # Converge first (the backfill test above may have advanced raw past the
    # marts), then prove two consecutive runs are identical.
    run_pipeline()
    before = checksums()
    run_pipeline()
    after = checksums()
    diffs = {t: (before[t], after[t]) for t in tables if before[t] != after[t]}
    assert not diffs, f"re-run mutated tables: {diffs}"
