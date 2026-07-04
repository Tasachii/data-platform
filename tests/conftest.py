from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipelines.orders.common import RAW_DIR, WAREHOUSE_PATH  # noqa: E402


# Function-scoped on purpose: DuckDB is single-writer, and the idempotency
# test re-runs the whole pipeline in a subprocess — no reader may hold the
# file open while that happens.
@pytest.fixture
def con() -> duckdb.DuckDBPyConnection:
    if not WAREHOUSE_PATH.exists():
        pytest.skip(f"warehouse not built yet: {WAREHOUSE_PATH} (run run_pipeline.py first)")
    connection = duckdb.connect(str(WAREHOUSE_PATH), read_only=True)
    yield connection
    connection.close()


@pytest.fixture(scope="session")
def manifest() -> dict:
    path = RAW_DIR / "_manifest.json"
    if not path.exists():
        pytest.skip(f"generator manifest missing: {path} (run generate_orders.py first)")
    return json.loads(path.read_text())


def one(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None):
    """Run a scalar query."""
    return con.execute(sql, params or []).fetchone()[0]
