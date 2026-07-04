"""Daily payment reconciliation: ingest gateway + ledger files, run the
matching waterfall, publish the finance report. Alerts land in recon.alerts
(CRITICAL/WARNING) — wire a webhook notifier there when one exists.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

REPO = "/opt/airflow/repo"

default_args = {
    "owner": "data-platform",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="recon_daily",
    description="Gateway vs ledger reconciliation with waterfall matching",
    schedule="@daily",
    start_date=datetime(2026, 6, 24),
    end_date=datetime(2026, 6, 30),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["reconciliation", "finance"],
) as dag:
    ingest = BashOperator(
        task_id="ingest",
        bash_command=f"cd {REPO} && python -m pipelines.reconciliation.ingest --date {{{{ ds }}}}",
    )

    match_and_alert = BashOperator(
        task_id="match_and_alert",
        bash_command=f"cd {REPO} && python -m pipelines.reconciliation.matching",
    )

    report = BashOperator(
        task_id="report",
        bash_command=f"cd {REPO} && python -m pipelines.reconciliation.report",
    )

    ingest >> match_and_alert >> report
