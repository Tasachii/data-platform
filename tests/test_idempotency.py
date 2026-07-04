"""Gate-1 proof: running the whole pipeline again over the same inputs must
change nothing. Checksums of every layer are compared before and after a
full re-run (volatile audit columns excluded).
"""

from __future__ import annotations

import subprocess
import sys

import duckdb
import pytest

from tests.conftest import REPO_ROOT, WAREHOUSE_PATH

# table -> projection to checksum (audit timestamps change every run by design)
TABLES = {
    "raw.orders": "* EXCLUDE (_ingested_at)",
    "raw.order_items": "* EXCLUDE (_ingested_at)",
    "staging.stg_orders": "*",
    "staging.rejected_orders": "*",
    "intermediate.int_order_status_history": "*",
    "intermediate.int_orders_enriched": "*",
    "marts.fct_daily_sales": "*",
    "marts.fct_refund_analysis": "*",
    "marts.dim_customers": "*",
    "marts.dim_products": "*",
}


def _checksums() -> dict[str, tuple]:
    con = duckdb.connect(str(WAREHOUSE_PATH), read_only=True)
    try:
        return {
            table: con.execute(
                f"SELECT count(*), sum(hash(CAST(t AS VARCHAR))) "
                f"FROM (SELECT {projection} FROM {table}) t"
            ).fetchone()
            for table, projection in TABLES.items()
        }
    finally:
        con.close()


def test_full_rerun_changes_nothing():
    if not WAREHOUSE_PATH.exists():
        pytest.skip("warehouse not built yet")

    before = _checksums()

    # --skip-tests: this test IS the test step; no recursion.
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "pipelines/orders/run_pipeline.py"), "--all", "--skip-tests"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, f"pipeline re-run failed:\n{result.stderr[-2000:]}"

    after = _checksums()
    diffs = {t: (before[t], after[t]) for t in TABLES if before[t] != after[t]}
    assert not diffs, f"re-run mutated tables: {diffs}"
