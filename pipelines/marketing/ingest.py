"""Load ad-platform files (via their connectors), UTM touches, and FX rates
into raw — same replace-partition contract as every other ingest.

A missing platform file is a WARNING, not a failure: ad platforms deliver
late routinely (TikTok's final day sits in raw/late_arrivals/ until it
"arrives"). Re-running --date after the file lands backfills that partition;
--include-late ingests directly from raw/late_arrivals/ for the demo.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import duckdb

from pipelines.marketing.connectors import CONNECTORS
from pipelines.orders.common import RAW_DIR, connect, get_logger
from pipelines.orders.ingest import _ensure_tables, _log_load, load_daily_file, parse_dates

log = get_logger("marketing.ingest")

DDL = {
    "ad_performance": """
        CREATE TABLE IF NOT EXISTS raw.ad_performance (
            report_date VARCHAR, platform VARCHAR, campaign_id VARCHAR,
            ad_id VARCHAR, campaign_name VARCHAR, spend VARCHAR,
            currency VARCHAR, impressions VARCHAR, clicks VARCHAR,
            conversions VARCHAR, _source_file VARCHAR, _ingested_at TIMESTAMP
        )""",
    "utm_touches": """
        CREATE TABLE IF NOT EXISTS raw.utm_touches (
            order_id VARCHAR, utm_source VARCHAR, utm_campaign VARCHAR,
            _source_file VARCHAR, _ingested_at TIMESTAMP
        )""",
}


def load_ad_file(con: duckdb.DuckDBPyConnection, path: Path, file_date: date) -> int:
    """Parse one platform file through its connector, replace its partition."""
    connector = next(
        c for c in CONNECTORS if path.name.startswith(c.file_pattern.split("{")[0])
    )
    frame = connector.parse(path)  # noqa: F841 — duckdb resolves `frame` by name below
    con.execute("DELETE FROM raw.ad_performance WHERE _source_file = ?", [path.name])
    con.execute(
        "INSERT INTO raw.ad_performance "
        "SELECT *, ? AS _source_file, now() AS _ingested_at FROM frame",
        [path.name],
    )
    rows = con.execute(
        "SELECT count(*) FROM raw.ad_performance WHERE _source_file = ?", [path.name]
    ).fetchone()[0]
    _log_load(con, path.name, "ad_performance", file_date, rows)
    log.info("loaded %s -> raw.ad_performance (%d rows)", path.name, rows)
    return rows


def ingest(dates: list[date], include_late: bool = False) -> None:
    con = connect()
    _ensure_tables(con)
    for ddl in DDL.values():
        con.execute(ddl)

    fx_path = RAW_DIR / "fx_rates.csv"
    if not fx_path.exists():
        raise FileNotFoundError(f"missing fx table: {fx_path}")
    con.execute("CREATE OR REPLACE TABLE raw.fx_rates AS SELECT * FROM read_csv(?, header = true)",
                [str(fx_path)])
    _log_load(con, fx_path.name, "fx_rates",
              None, con.execute("SELECT count(*) FROM raw.fx_rates").fetchone()[0])

    search_dirs = [RAW_DIR] + ([RAW_DIR / "late_arrivals"] if include_late else [])
    for d in dates:
        for connector in CONNECTORS:
            file_name = connector.file_pattern.format(date=d)
            path = next((base / file_name for base in search_dirs if (base / file_name).exists()), None)
            if path is None:
                log.warning("ad file not yet delivered, skipping: %s "
                            "(re-run --date %s when it arrives)", file_name, d)
                continue
            load_ad_file(con, path, d)

        utm_path = RAW_DIR / f"utm_touches_{d}.csv"
        if utm_path.exists():
            load_daily_file(con, utm_path, "utm_touches", d)
        else:
            log.warning("file not found, skipping: %s", utm_path.name)
    con.close()


def available_dates() -> list[date]:
    dates = set()
    for f in RAW_DIR.glob("utm_touches_*.csv"):
        dates.add(date.fromisoformat(f.stem.removeprefix("utm_touches_")))
    return sorted(dates)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--include-late", action="store_true",
                        help="also ingest files still sitting in raw/late_arrivals/")
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    ingest(available_dates() if args.all else parse_dates(args), include_late=args.include_late)
