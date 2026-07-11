"""Load daily source CSVs into the `raw` schema of the warehouse.

Idempotency contract: re-loading the same file replaces that file's partition
(DELETE by _source_file, then INSERT) — never appends on top. Every load is
recorded in meta.ingest_log so we always know which files landed, when, and
with how many rows.

Raw stays untyped (all VARCHAR): the source's dirt is preserved as-is and all
casting/cleaning happens in staging, where rejects can be quarantined with a
reason instead of failing the load.
"""

from __future__ import annotations

import argparse
import re
from datetime import date, timedelta
from pathlib import Path

import duckdb

from pipelines.orders.common import RAW_DIR, connect, get_logger

log = get_logger("ingest")

DAILY_TABLES = {"orders": "orders", "order_items": "order_items"}
SNAPSHOT_TABLES = {"products": "products.csv", "customers": "customers.csv"}

DDL = {
    "orders": """
        CREATE TABLE IF NOT EXISTS raw.orders (
            order_id VARCHAR, customer_id VARCHAR, order_ts VARCHAR,
            updated_at VARCHAR, status VARCHAR, total_amount VARCHAR,
            channel VARCHAR, _source_file VARCHAR, _ingested_at TIMESTAMP
        )""",
    "order_items": """
        CREATE TABLE IF NOT EXISTS raw.order_items (
            order_id VARCHAR, product_id VARCHAR, qty VARCHAR,
            unit_price VARCHAR, _source_file VARCHAR, _ingested_at TIMESTAMP
        )""",
    "ingest_log": """
        CREATE TABLE IF NOT EXISTS meta.ingest_log (
            file_name VARCHAR PRIMARY KEY, table_name VARCHAR,
            file_date DATE, loaded_at TIMESTAMP, row_count BIGINT
        )""",
}


def _ensure_tables(con: duckdb.DuckDBPyConnection) -> None:
    for ddl in DDL.values():
        con.execute(ddl)


def _log_load(
    con: duckdb.DuckDBPyConnection, file_name: str, table: str, file_date: date | None, rows: int
) -> None:
    con.execute("DELETE FROM meta.ingest_log WHERE file_name = ?", [file_name])
    con.execute(
        "INSERT INTO meta.ingest_log VALUES (?, ?, ?, now(), ?)",
        [file_name, table, file_date, rows],
    )


def load_daily_file(con: duckdb.DuckDBPyConnection, path: Path, table: str, file_date: date) -> int:
    """Replace one file's partition in raw.<table>. Returns rows loaded."""
    stage = f"incoming_{table}"
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE {stage} AS "
        "SELECT * FROM read_csv(?, all_varchar = true, header = true)",
        [str(path)],
    )
    expected = [
        row[1]
        for row in con.execute(f"PRAGMA table_info('raw.{table}')").fetchall()
        if row[1] not in {"_source_file", "_ingested_at"}
    ]
    received = [row[1] for row in con.execute(f"PRAGMA table_info('{stage}')").fetchall()]
    if received != expected:
        raise ValueError(
            f"schema mismatch for {path.name}: expected {expected}, received {received}"
        )
    rows = con.execute(f"SELECT count(*) FROM {stage}").fetchone()[0]

    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(f"DELETE FROM raw.{table} WHERE _source_file = ?", [path.name])
        columns = ", ".join(expected)
        con.execute(
            f"INSERT INTO raw.{table} ({columns}, _source_file, _ingested_at) "
            f"SELECT {columns}, ?, now() FROM {stage}",
            [path.name],
        )
        _log_load(con, path.name, table, file_date, rows)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    log.info("loaded %s -> raw.%s (%d rows)", path.name, table, rows)
    return rows


def load_snapshots(con: duckdb.DuckDBPyConnection) -> None:
    """Dimension snapshots are small: full replace every run."""
    for table, file_name in SNAPSHOT_TABLES.items():
        path = RAW_DIR / file_name
        if not path.exists():
            raise FileNotFoundError(f"missing snapshot file: {path}")
        con.execute(f"CREATE OR REPLACE TABLE raw.{table} AS SELECT * FROM read_csv(?, header = true)", [str(path)])
        rows = con.execute(f"SELECT count(*) FROM raw.{table}").fetchone()[0]
        _log_load(con, file_name, table, None, rows)
        log.info("loaded %s -> raw.%s (%d rows)", file_name, table, rows)


def available_dates() -> list[date]:
    dates = []
    for f in sorted(RAW_DIR.glob("orders_*.csv")):
        m = re.match(r"orders_(\d{4}-\d{2}-\d{2})\.csv", f.name)
        if m:
            dates.append(date.fromisoformat(m.group(1)))
    return dates


def ingest(dates: list[date]) -> None:
    con = connect()
    _ensure_tables(con)
    load_snapshots(con)
    for d in dates:
        for table in DAILY_TABLES:
            path = RAW_DIR / f"{table}_{d}.csv"
            if not path.exists():
                log.warning("file not found, skipping: %s", path.name)
                continue
            load_daily_file(con, path, table, d)
    con.close()


def parse_dates(args: argparse.Namespace) -> list[date]:
    if args.all:
        return available_dates()
    if args.date:
        return [args.date]
    if args.start and args.end:
        if args.start > args.end:
            raise SystemExit(
                f"--start {args.start} is after --end {args.end}; "
                "a reversed range would silently ingest nothing"
            )
        n = (args.end - args.start).days
        return [args.start + timedelta(days=i) for i in range(n + 1)]
    raise SystemExit("specify --all, --date, or --start/--end")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="ingest every file in raw/")
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    return parser


if __name__ == "__main__":
    ingest(parse_dates(build_parser().parse_args()))
