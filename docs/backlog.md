# Backlog

Ideas that are explicitly **not** in scope until the current gate passes.
Write them here instead of building them (scope-creep firewall).

- OpenGambit product analytics pipeline (real event data, GA4 → warehouse)
- Metabase service in docker-compose (needs community DuckDB driver)
- Migrate warehouse DuckDB → BigQuery free tier (dbt makes this cheap)
- Streaming ingest variant (Kafka/Redpanda) — only if a target JD asks for it
- Great Expectations as a second data-quality layer
- Airflow 3.x migration — currently pinned to 2.10.5 (stable LocalExecutor
  compose pattern, well-documented). Revisit once the 3.x deployment pattern
  settles; DAG code uses only BashOperator + `schedule`, so the surface is small.
