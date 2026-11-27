"""Exercise file discovery, matching, alerting and report output together."""

import csv
import os
import subprocess
import sys

import duckdb
import pytest

from pipelines.orders.common import REPO_ROOT


@pytest.mark.parametrize(
    ("feed", "header", "record", "counts", "bucket", "gap", "rules"),
    [
        (
            "ledger_entries", "entry_id,external_ref,amount,currency,posted_at,account_code,entry_type",
            "L1,DEMO-1,12500.00,THB,2026-06-28T16:00:00+07:00,1102,debit",
            (0, 1), "missing_in_gateway", -12500, {"net_difference"},
        ),
        (
            "gateway_txns", "txn_id,gateway_ref,amount,currency,fee,status,created_at,merchant_id,payment_method",
            "T1,GW-DEMO-2,12500.00,THB,10.00,captured,2026-06-28T09:00:00Z,M1,card",
            (1, 0), "missing_in_ledger", 12500, {"net_difference", "match_rate"},
        ),
    ],
    ids=["ledger-only", "gateway-only"],
)
def test_all_includes_one_sided_delivery(tmp_path, feed, header, record, counts, bucket, gap, rules):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / f"{feed}_2026-06-28.csv").write_text(f"{header}\n{record}\n")
    db = tmp_path / "probe.duckdb"
    reports = tmp_path / "reports"
    env = dict(os.environ, PLATFORM_RAW_DIR=str(raw), PLATFORM_DB=str(db), PLATFORM_REPORT_DIR=str(reports))

    for _ in range(2):
        subprocess.run([sys.executable, "pipelines/reconciliation/run_recon.py", "--all"],
                       cwd=REPO_ROOT, env=env, check=True, capture_output=True, text=True)
        with duckdb.connect(str(db), read_only=True) as con:
            assert con.execute("""
                SELECT txn_date::VARCHAR, gateway_count, ledger_count, net_difference
                FROM recon.recon_summary
            """).fetchall() == [("2026-06-28", *counts, gap)]
            assert con.execute("SELECT match_type FROM recon.recon_results").fetchall() == [(bucket,)]
            assert sorted(con.execute("SELECT severity, rule FROM recon.alerts").fetchall()) == [
                ("CRITICAL", rule) for rule in sorted(rules)
            ]
        with (reports / "recon_unmatched.csv").open() as stream:
            assert [r["match_type"] for r in csv.DictReader(stream)] == [bucket]
        assert "| 2026-06-28 | CRITICAL | net_difference |" in (reports / "recon_summary.md").read_text()
