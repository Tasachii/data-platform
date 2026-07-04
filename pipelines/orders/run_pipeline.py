"""Orders pipeline entrypoint: ingest -> transform -> data quality tests.

Usage:
    python pipelines/orders/run_pipeline.py --all
    python pipelines/orders/run_pipeline.py --date 2026-06-15          # single-day backfill
    python pipelines/orders/run_pipeline.py --start 2026-06-01 --end 2026-06-07
    python pipelines/orders/run_pipeline.py --all --skip-tests

Any failing step aborts the run with a non-zero exit code.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from pipelines.orders import ingest, report  # noqa: E402
from pipelines.orders.common import get_logger  # noqa: E402

log = get_logger("pipeline")


def dbt_build() -> None:
    """Transform + schema-test via dbt (models live in dbt/models)."""
    # dbt has no python -m entrypoint; use the console script installed next
    # to the interpreter (works in the venv and inside the Airflow image).
    dbt_exe = Path(sys.executable).with_name("dbt")
    result = subprocess.run(
        [str(dbt_exe) if dbt_exe.exists() else "dbt", "build",
         "--project-dir", str(REPO_ROOT / "dbt"),
         "--profiles-dir", str(REPO_ROOT / "dbt")],
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        raise RuntimeError("dbt build failed")


def main() -> int:
    parser = ingest.build_parser()
    parser.add_argument("--skip-tests", action="store_true",
                        help="skip the pytest data-quality step (used by the idempotency test itself)")
    args = parser.parse_args()
    dates = ingest.parse_dates(args)

    started = time.perf_counter()
    log.info("=== step 1/4: ingest (%d date(s)) ===", len(dates))
    ingest.ingest(dates)

    log.info("=== step 2/4: transform (dbt build) ===")
    dbt_build()

    log.info("=== step 3/4: business report ===")
    report.main()

    if args.skip_tests:
        log.info("=== step 4/4: tests SKIPPED (--skip-tests) ===")
    else:
        log.info("=== step 4/4: data quality tests ===")
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(REPO_ROOT / "tests"), "-q", "--no-header"],
            cwd=REPO_ROOT,
        )
        if result.returncode != 0:
            log.error("data quality tests FAILED — pipeline aborted")
            return result.returncode

    log.info("pipeline finished in %.1fs", time.perf_counter() - started)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
