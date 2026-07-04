"""Execute the SQL transform layers in order: staging -> intermediate -> marts.

Each .sql file is a full CREATE OR REPLACE — transforms are a deterministic
function of the raw layer, so re-running is always safe (idempotent by
construction). Files run in lexical order within a layer (hence the numeric
prefixes).
"""

from __future__ import annotations

import time
from pathlib import Path

import duckdb

from pipelines.orders.common import connect, get_logger

log = get_logger("transform")

SQL_DIR = Path(__file__).resolve().parent / "sql"
LAYERS = ["staging", "intermediate", "marts"]


def run_layer(con: duckdb.DuckDBPyConnection, layer: str) -> None:
    for sql_file in sorted((SQL_DIR / layer).glob("*.sql")):
        started = time.perf_counter()
        con.execute(sql_file.read_text())
        log.info("ran %s/%s (%.2fs)", layer, sql_file.name, time.perf_counter() - started)

    tables = con.execute(
        "SELECT table_name, estimated_size FROM duckdb_tables() WHERE schema_name = ?",
        [layer],
    ).fetchall()
    for name, size in tables:
        log.info("  %s.%s: %s rows", layer, name, f"{size:,}")


def run_all(con: duckdb.DuckDBPyConnection | None = None) -> None:
    own_connection = con is None
    if own_connection:
        con = connect()
    try:
        for layer in LAYERS:
            run_layer(con, layer)
    finally:
        if own_connection:
            con.close()


if __name__ == "__main__":
    run_all()
