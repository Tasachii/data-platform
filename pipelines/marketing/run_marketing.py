"""Marketing attribution pipeline entrypoint: ingest -> dbt build -> report.

Usage:
    python pipelines/marketing/run_marketing.py --all
    python pipelines/marketing/run_marketing.py --date 2026-06-30 --include-late

A platform file that hasn't been delivered yet is a WARNING, not a failure —
re-run with --date (and --include-late for the demo's held-back TikTok file)
once it arrives; replace-partition ingest makes that safe.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from pipelines.marketing import ingest, report  # noqa: E402
from pipelines.orders.common import get_logger  # noqa: E402
from pipelines.orders.ingest import parse_dates  # noqa: E402
from pipelines.orders.run_pipeline import dbt_build  # noqa: E402

log = get_logger("marketing.pipeline")


def main() -> int:
    args = ingest.build_parser().parse_args()
    dates = ingest.available_dates() if args.all else parse_dates(args)

    started = time.perf_counter()
    log.info("=== step 1/3: ingest (%d date(s)) ===", len(dates))
    ingest.ingest(dates, include_late=args.include_late)

    log.info("=== step 2/3: transform (dbt build, marketing models) ===")
    dbt_build(select="+tag:marketing")

    log.info("=== step 3/3: report ===")
    report.main()

    log.info("marketing pipeline finished in %.1fs", time.perf_counter() - started)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
