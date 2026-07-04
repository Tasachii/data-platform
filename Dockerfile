# Airflow worker image for the data platform: base Airflow + our pipeline deps
# (duckdb, dbt-duckdb, pandas, pytest) so DAG tasks run the exact same code
# and tests as local development.
FROM apache/airflow:2.10.5-python3.11

COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt
