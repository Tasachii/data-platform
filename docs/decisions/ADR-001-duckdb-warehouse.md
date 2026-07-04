# ADR-001: DuckDB as the Warehouse

**Status:** Accepted · 2026-07-05

## Context

The platform needs an analytical store that runs locally, in CI, and inside
the Airflow container — at zero cost — while handling ~600k orders / 1.8M
order lines comfortably.

## Decision

DuckDB, as a single file at `warehouse/platform.duckdb`.

## Consequences

- Full pipeline (30 days ingest + dbt build + 52 tests) runs in ~30s locally
  and identically in CI — no cloud credentials anywhere.
- **Single-writer**: Airflow DAGs must set `max_active_runs=1`; concurrent
  backfill runs would fight over the file. This is the main scaling limit and
  it is documented, not hidden.
- dbt abstracts the SQL, so promoting to BigQuery later is mostly a profile
  change (`dbt-duckdb` → `dbt-bigquery`) plus swapping `read_csv` ingestion
  for load jobs. Kept in `docs/backlog.md`.

## Alternatives considered

- **BigQuery free tier** — the most-wanted JD keyword, but demands GCP setup
  for every reviewer who clones the repo; kills "clone → run in 10 minutes".
- **Postgres** — row store; analytical scans over 1.8M lines are noticeably
  slower, and it adds a service dependency for local dev.
