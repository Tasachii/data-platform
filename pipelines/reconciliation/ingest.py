"""Load gateway settlement files and ledger exports into raw — same
replace-partition idempotency contract as the orders ingest, same log table.
"""

from __future__ import annotations

import argparse
from datetime import date

from pipelines.orders.common import RAW_DIR, connect, get_logger
from pipelines.orders.ingest import _ensure_tables, load_daily_file, parse_dates

log = get_logger("recon.ingest")

DDL = {
    "gateway_txns": """
        CREATE TABLE IF NOT EXISTS raw.gateway_txns (
            txn_id VARCHAR, gateway_ref VARCHAR, amount VARCHAR, currency VARCHAR,
            fee VARCHAR, status VARCHAR, created_at VARCHAR, merchant_id VARCHAR,
            payment_method VARCHAR, _source_file VARCHAR, _ingested_at TIMESTAMP
        )""",
    "ledger_entries": """
        CREATE TABLE IF NOT EXISTS raw.ledger_entries (
            entry_id VARCHAR, external_ref VARCHAR, amount VARCHAR, currency VARCHAR,
            posted_at VARCHAR, account_code VARCHAR, entry_type VARCHAR,
            _source_file VARCHAR, _ingested_at TIMESTAMP
        )""",
}


def available_dates() -> list[date]:
    dates = []
    for f in sorted(RAW_DIR.glob("gateway_txns_*.csv")):
        dates.append(date.fromisoformat(f.stem.removeprefix("gateway_txns_")))
    return dates


def ingest(dates: list[date]) -> None:
    con = connect()
    _ensure_tables(con)
    for ddl in DDL.values():
        con.execute(ddl)
    for d in dates:
        for table in DDL:
            path = RAW_DIR / f"{table}_{d}.csv"
            if not path.exists():
                log.warning("file not found, skipping: %s", path.name)
                continue
            load_daily_file(con, path, table, d)
    con.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    if args.all:
        ingest(available_dates())
    else:
        ingest(parse_dates(args))
