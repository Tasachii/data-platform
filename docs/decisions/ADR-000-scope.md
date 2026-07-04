# ADR-000: Project Scope — One Platform Repo, Phased Delivery

**Status:** Accepted · 2026-07-05

## Context

Portfolio goal: demonstrate production Data Engineering skills for the Thai job
market (Airflow, dbt, SQL, Python, Docker are the most-requested JD keywords).
Two candidate structures: one repo per pipeline vs. a single platform repo.

## Decision

Single platform repo (`data-platform`) containing multiple pipelines that share
one warehouse, one orchestrator, and one CI setup. Delivery is phased:

1. **Phase 1** — orders pipeline as plain Python + SQL (learn the logic first)
2. **Phase 2** — productionize: migrate SQL to dbt, wrap in Airflow, Docker Compose
3. **Phase 3** — reconciliation pipeline built on Phase 1's payment data
4. **Phase 4** — docs, ADRs, blog post

## Consequences

- Infra (Airflow/dbt/Docker/CI) is built once and reused by every pipeline.
- The reconciliation pipeline can consume orders data directly — the two
  pipelines form one coherent business story instead of disconnected demos.
- Commit history shows a script → production evolution, which is the narrative
  we want to tell in interviews.
- Marketing attribution pipeline is deliberately **out of scope** until Gate 3
  passes (see `docs/backlog.md`).

## Alternatives considered

- **Repo per pipeline**: simpler to present as separate portfolio items, but
  triples infra setup cost and hides the platform-thinking signal we want.
