"""Export the completed simulation warehouse as deterministic, aggregate-only JSON."""

import argparse
import json
import os
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "dashboard/data/snapshot.json"

# Money travels as integer satang. All result sets have an explicit public
# schema and order so the same warehouse always produces the same bytes.
SALES = """
    WITH money AS (
        SELECT business_date, channel, sum(net_amount) AS net, sum(refund_amount) AS refunds
        FROM marts.fct_daily_sales GROUP BY 1, 2
    )
    SELECT business_date AS date, channel, net_orders AS orders,
           (net * 100)::BIGINT AS net, (refunds * 100)::BIGINT AS refunds
    FROM money JOIN marts.fct_daily_orders USING (business_date, channel)
    ORDER BY 1, 2
"""
RECON = """
    SELECT txn_date AS date, gateway_count AS gateway, ledger_count AS ledger,
           matched + rounding + fee_timing + possible_ref_issue AS matched,
           (net_difference * 100)::BIGINT AS gap
    FROM recon.recon_summary ORDER BY 1
"""
ALERTS = """
    SELECT txn_date AS date, severity, rule, count(*) AS alerts
    FROM recon.alerts GROUP BY 1, 2, 3 ORDER BY 1, 2, 3
"""
MARKETING = """
    SELECT activity_date AS date, platform, attributed_orders AS orders,
           (attributed_revenue_thb * 100)::BIGINT AS revenue,
           (spend_thb * 100)::BIGINT AS spend
    FROM marts.fct_channel_performance ORDER BY 1, 2
"""


def rows(con, query):
    cursor = con.execute(query)
    names = [column[0] for column in cursor.description]
    return [
        dict(zip(names, (v.isoformat() if isinstance(v, date) else v for v in row), strict=True))
        for row in cursor.fetchall()
    ]


def snapshot(con):
    coverage = rows(con, """
        SELECT table_name AS feed, min(file_date) AS start, max(file_date) AS finish,
               count(DISTINCT file_date) AS days
        FROM meta.ingest_log WHERE table_name IN ('orders', 'gateway_txns', 'ad_performance')
        GROUP BY 1 ORDER BY 1
    """)
    # An undelivered ad file looks like zero spend after the mart's full join.
    # Refuse publication until each expected platform-day has reached staging.
    gaps = con.execute("""
        SELECT fx_date, p.platform
        FROM staging.stg_fx_rates CROSS JOIN (VALUES ('facebook'), ('google'), ('tiktok')) p(platform)
        EXCEPT SELECT report_date, platform FROM staging.stg_ad_performance
    """).fetchall()
    if gaps:
        raise ValueError(f"Missing ad platform-days {sorted(gaps)}. Backfill before exporting.")
    data = dict(version=1, synthetic=True, currency="THB", moneyUnit="satang", coverage=coverage,
                sales=rows(con, SALES), reconciliation=rows(con, RECON), alerts=rows(con, ALERTS),
                marketing=rows(con, MARKETING))
    if len(coverage) != 3 or not all(data[key] for key in ('sales', 'reconciliation', 'marketing')):
        raise ValueError("Build all three simulation pipelines before exporting.")
    return data


def export(database, output):
    with duckdb.connect(str(database), read_only=True) as con:
        data = snapshot(con)
    payload = json.dumps(data, allow_nan=False, separators=(",", ":")) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", dir=output.parent, delete=False, encoding="utf-8") as tmp:
        tmp.write(payload)
    os.replace(tmp.name, output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path(os.environ.get(
        "PLATFORM_DB", ROOT / "warehouse/platform.duckdb")))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    export(args.db, args.output)
