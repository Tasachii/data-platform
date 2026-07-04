# ADR-006: Productionize in Phases — Scripts → dbt → Airflow

**Status:** Accepted · 2026-07-05

## Context

The end state (Airflow + dbt + Docker) was known from day one. The question
was whether to start there or to build the logic first and productionize
second.

## Decision

Three deliberate steps, preserved in commit history:

1. **Plain Python + SQL files** — all business logic (dedup, SCD2,
   restatement) proven by pytest before any framework enters.
2. **dbt migration** — the same SQL becomes models with schema tests, docs
   and lineage; the pytest invariants never changed and stayed green, which
   *is* the proof the migration was faithful.
3. **Airflow + Docker** — the runner steps become DAG tasks; the runner
   itself survives for local dev and CI.

## Consequences

- Debugging never involved fighting framework and logic simultaneously.
- dbt's value is articulable from experience, not marketing: it replaced a
  hand-rolled SQL-file runner, an execution-order convention, and ad-hoc
  quality queries with `ref()`, `dbt test`, and generated lineage.
- Pipeline logic stays orchestrator-agnostic (plain `python -m` entrypoints);
  Airflow schedules and retries, it doesn't own the logic. Swapping to
  Dagster would touch only `dags/`.
