"""Reconciliation pipeline entrypoint: ingest -> match -> alert -> report.

Usage:
    python pipelines/reconciliation/run_recon.py --all
    python pipelines/reconciliation/run_recon.py --date 2026-06-28

Alerts are business signals, not pipeline failures: a CRITICAL mismatch day
still exits 0 — the alert lands in recon.alerts and the report. The pipeline
fails (non-zero) only on real execution errors.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from pipelines.orders.common import get_logger  # noqa: E402
from pipelines.reconciliation import ingest, matching, report  # noqa: E402

log = get_logger("recon.pipeline")


def main() -> int:
    parser = ingest.build_parser()
    args = parser.parse_args()
    dates = ingest.available_dates() if args.all else ingest.parse_dates(args)

    started = time.perf_counter()
    log.info("=== step 1/3: ingest (%d date(s)) ===", len(dates))
    ingest.ingest(dates)

    log.info("=== step 2/3: matching + alerts ===")
    alerts = matching.run()
    log.info("%d alert(s) raised", len(alerts))

    log.info("=== step 3/3: report ===")
    report.main()

    log.info("recon finished in %.1fs", time.perf_counter() - started)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
