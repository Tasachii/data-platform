"""Daily orders pipeline: ingest -> dbt build -> report -> data-quality gate.

Backfill any window with:
    airflow dags backfill orders_daily -s 2026-06-01 -e 2026-06-07

max_active_runs=1 because DuckDB is single-writer — concurrent runs would
fight over the warehouse file. (Migrating the warehouse to BigQuery removes
this constraint; see docs/backlog.md.)
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
    dag_id="orders_daily",
    description="E-commerce orders: ingest, transform (dbt), report, quality gate",
    schedule="@daily",
    start_date=datetime(2026, 6, 1),
    end_date=datetime(2026, 6, 30),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["orders", "dbt"],
) as dag:
    ingest = BashOperator(
        task_id="ingest",
        bash_command=f"cd {REPO} && python -m pipelines.orders.ingest --date {{{{ ds }}}}",
    )

    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=(f"cd {REPO} && dbt build --project-dir dbt --profiles-dir dbt "
                      "--select +tag:orders"),
    )

    report = BashOperator(
        task_id="report",
        bash_command=f"cd {REPO} && python -m pipelines.orders.report",
    )

    data_quality = BashOperator(
        task_id="data_quality",
        bash_command=f"cd {REPO} && python -m pytest tests -q --no-header",
    )

    ingest >> dbt_build >> report >> data_quality
