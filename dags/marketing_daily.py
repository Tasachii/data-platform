"""Daily marketing attribution: ingest the three ad platforms' files + UTM
touches, rebuild the attribution marts, publish the growth report. A missing
platform file (they deliver late routinely) is a WARNING — the day backfills
itself on a later run once the file lands.
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
    dag_id="marketing_daily",
    description="Ad platforms + UTM -> unified attribution marts (ROAS)",
    schedule="@daily",
    start_date=datetime(2026, 6, 17),
    end_date=datetime(2026, 6, 30),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["marketing", "dbt"],
) as dag:
    ingest = BashOperator(
        task_id="ingest",
        bash_command=f"cd {REPO} && python -m pipelines.marketing.ingest --date {{{{ ds }}}}",
    )

    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=f"cd {REPO} && dbt build --project-dir dbt --profiles-dir dbt",
    )

    report = BashOperator(
        task_id="report",
        bash_command=f"cd {REPO} && python -m pipelines.marketing.report",
    )

    ingest >> dbt_build >> report
