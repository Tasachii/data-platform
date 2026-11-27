"""Rebuild the published sample in isolation, using the regular pipeline entry points."""

import argparse
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from export_dashboard import DEFAULT_OUTPUT, ROOT


def rebuild(output):
    with TemporaryDirectory(prefix="commerce-snapshot-") as folder:
        work = Path(folder)
        env = dict(os.environ, PLATFORM_DB=str(work / "platform.duckdb"),
                   PLATFORM_RAW_DIR=str(work / "raw"), PLATFORM_REPORT_DIR=str(work / "reports"),
                   DBT_SEND_ANONYMOUS_USAGE_STATS="false")
        commands = [
            ["generator/generate_orders.py", "--days", "30", "--orders-per-day", "2000",
             "--end-date", "2026-06-30", "--seed", "42"],
            ["generator/generate_payments.py", "--days", "7", "--seed", "43"],
            ["generator/generate_marketing.py", "--days", "14", "--seed", "44"],
            ["pipelines/orders/run_pipeline.py", "--all", "--skip-tests"],
            ["pipelines/reconciliation/run_recon.py", "--all"],
            ["pipelines/marketing/run_marketing.py", "--all", "--include-late"],
            ["-m", "pytest", "tests/", "-q"],
            ["scripts/export_dashboard.py", "--output", str(output.resolve())],
        ]
        for command in commands:
            subprocess.run([sys.executable, *command], cwd=ROOT, env=env, check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    rebuild(parser.parse_args().output)
