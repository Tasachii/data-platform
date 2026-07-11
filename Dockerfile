# Airflow worker image for the data platform: base Airflow + our pipeline deps
# (duckdb, dbt-duckdb, pandas, pytest) so DAG tasks run the exact same code
# and tests as local development.
FROM apache/airflow:2.10.5-python3.11

ARG AIRFLOW_VERSION=2.10.5
ARG PYTHON_VERSION=3.11
ARG AIRFLOW_CONSTRAINTS_URL=https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt

COPY requirements-airflow.txt requirements-dbt-airflow.txt /
RUN pip install --no-cache-dir \
      "apache-airflow==${AIRFLOW_VERSION}" \
      -r /requirements-airflow.txt \
      --constraint "${AIRFLOW_CONSTRAINTS_URL}" \
    && pip install --no-cache-dir \
      "apache-airflow==${AIRFLOW_VERSION}" \
      -r /requirements-dbt-airflow.txt \
    && pip check
