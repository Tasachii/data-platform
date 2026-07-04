# data-platform

[![ci](https://github.com/Tasachii/data-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/Tasachii/data-platform/actions/workflows/ci.yml)

An end-to-end data platform for a simulated Thai e-commerce/logistics company: a
daily orders pipeline (~20,000 orders/day, 30 days, with the dirt real sources
produce), a dbt-modelled DuckDB warehouse, a payment-reconciliation engine, and
Airflow orchestration on Docker Compose. Everything runs locally at zero cost —
no cloud account, no credentials — and rebuilds from an empty directory in
about a minute of compute.

## Contents

- [Status](#status)
- [Quickstart](#quickstart)
- [Why this exists](#why-this-exists)
- [Architecture](#architecture)
- [The orders pipeline](#the-orders-pipeline)
- [The reconciliation pipeline](#the-reconciliation-pipeline)
- [Airflow](#airflow)
- [Configuration](#configuration)
- [Testing](#testing)
- [Project documentation](#project-documentation)
- [Roadmap](#roadmap)
- [License](#license)

## Status

Both pipelines are **implemented and tested** end to end: 52 pytest tests
(idempotency by checksum, 100%-recall edge-case coverage, per-rule matching
units) plus 36 dbt schema tests, all green in CI on every push. The two Airflow
DAGs have been executed to completion inside the Docker stack
(`airflow dags test`, state=success).

The sources are **simulators, by design**: real order and payment feeds cannot
be published, so `generator/` produces them — and writes a manifest of every
corruption it injects, which is what lets the test suite prove recall instead
of asserting vibes. Not wired up: a webhook target for reconciliation alerts
(they land in a table and the report), and a cloud warehouse — see
[Roadmap](#roadmap).

## Quickstart

**Requirements** — [Python 3.11+](https://www.python.org) · [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Airflow path only)

```bash
git clone https://github.com/Tasachii/data-platform.git
cd data-platform
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python generator/generate_orders.py
python generator/generate_payments.py

python pipelines/orders/run_pipeline.py --all
python pipelines/reconciliation/run_recon.py --all
```

The orders run finishes with the full test suite; a red test aborts the
pipeline with a non-zero exit. Outputs land in `reports/` as markdown, plus a
`recon_unmatched.csv` follow-up queue for the finance persona.

Backfills never touch other days:

```bash
python pipelines/orders/run_pipeline.py --date 2026-06-15
python pipelines/orders/run_pipeline.py --start 2026-06-01 --end 2026-06-07
```

## Why this exists

Portfolio pipelines usually demonstrate the happy path on a clean CSV. Real
data work is the opposite: sources resend rows, refunds arrive a week late,
files show up a day after their data, ledgers disagree with gateways by
exactly one fee. This platform makes those failure modes the *point* — each
one is deliberately injected, recorded in a manifest, and caught by a named
test. The result doubles as a working answer to the classic data-engineering
interview questions: idempotency, SCD Type 2, late-arriving data, restatement,
fact grain, and reconciliation.

## Architecture

```
generator/                          DuckDB warehouse (warehouse/platform.duckdb)
  orders + items  ──ingest──▶  raw ──dbt build──▶ staging ─▶ intermediate ─▶ marts ─▶ sales report
  gateway + ledger ─ingest──▶  raw ──matching engine──▶ recon (results · summary · alerts) ─▶ finance report
                               ▲
             replace-partition by source file, logged in meta.ingest_log
```

| Component | Role | Technology |
|---|---|---|
| `generator/` | Simulates both source systems; writes corruption manifests | Python · numpy · pandas |
| `pipelines/orders/` | Idempotent ingest, runner, business report | Python · DuckDB |
| `dbt/` | 12 models (staging → intermediate → marts) · 36 schema tests | dbt-duckdb |
| `pipelines/reconciliation/` | 5-rule waterfall matching engine, alerting | Python · DuckDB SQL |
| `dags/` | `orders_daily` · `recon_daily` | Airflow 2.10 · Docker Compose |
| `tests/` | 52 tests: quality, recall, idempotency, per-rule units | pytest |

Design decisions worth noting (each has a full ADR in `docs/decisions/`):

- **Idempotency is proven, not promised.** Ingest replaces a file's partition
  (`DELETE` by `_source_file`, then insert); transforms are pure
  `CREATE OR REPLACE`. A test checksums all ten tables, re-runs the whole
  pipeline in a subprocess, and asserts nothing moved. (ADR-004)
- **Money is `DECIMAL(14,2)` end to end.** A reconciliation engine with float
  equality invents mismatches and hides real ones. (ADR-002)
- **Store UTC, report Asia/Bangkok.** Sources serialize the same instant as
  `+00:00` or `+07:00`; everything is parsed to UTC instants, and the Bangkok
  calendar date is derived only at the reporting layer — always explicitly,
  never via session-timezone casts. (ADR-003)
- **Refunds restate the original business date.** The mart rebuilds from
  current status, so a refund five days later moves its order out of NET on
  the day it was placed — with gross/refund kept visible. (ADR-005)
- **Money at line grain, counts at order grain.** Counting distinct orders
  inside category groups inflated totals 2.2× during development; the fix is
  two facts, each carrying only measures additive at its grain. (ADR-007)
- **DuckDB is single-writer.** DAGs run with `max_active_runs=1`; the
  BigQuery promotion path is in the backlog. (ADR-001)

## The orders pipeline

~20,000 orders/day across three channels (`web` · `shopee` · `lazada`),
600,000 orders over the default 30-day window. Every failure mode below is
injected by the generator, counted in `raw/_manifest.json`, and caught at 100%
by a named test:

| Injected failure | Volume (default run) | Handling |
|---|---|---|
| Duplicate resends — not always byte-identical (same instant, different tz offset) | 12,298 rows | Dedup on latest `updated_at` with a full content tie-break |
| Retroactive refunds, 1–7 days late | 15,561 orders | SCD2 status history; NET restated onto the original date |
| Late-arriving orders (day D in day D+1's file) | 5,800 orders | Facts key on `order_ts`, never file date |
| Null / negative amounts | 3,000 orders | Quarantined with a reason — never silently dropped |
| Orphan customer ids | 6,000 orders | Mapped to an explicit `unknown` dim member |
| Invalid customer emails | 240 customers | Flagged, kept |
| Mixed `+00:00` / `+07:00` timestamps | ~50% of rows | Parsed to UTC instants at staging |

Details, proofs, and the analyst query pack: [`pipelines/orders/README.md`](pipelines/orders/README.md).

## The reconciliation pipeline

125,336 gateway transactions vs 125,326 ledger entries over 7 days — derived
from the orders pipeline's own paid orders, so the platform describes one
business. A 5-rule waterfall puts every record in exactly one bucket:
exact → date-boundary → fee/rounding → fuzzy (refs must *look related*:
containment or Levenshtein ≤ 4) → missing, with duplicate postings flagged in
a pre-pass. Recall of injected mismatches is 100%:

| Injected mismatch | Volume | Detected as |
|---|---|---|
| In gateway, missing from ledger | 1,880 | `missing_in_ledger` |
| In ledger, missing from gateway | 1,253 | `missing_in_gateway` |
| Rounding drift (0.01–0.05) | 2,506 | `rounding` |
| Ledger already net of fee | 1,253 | `fee_timing` |
| Double postings | 617 | `duplicate_posting` |
| Dirty currency (`thb`, ` THB`) · missing `GW-` prefix | 376 · 6,266 | normalized → still match |

Alerts (`CRITICAL` on match rate < 97% or |net difference| > ฿10,000/day,
`WARNING` on any duplicate posting) land in `recon.alerts` and the report.
Waterfall diagram and rule rationale: [`pipelines/reconciliation/README.md`](pipelines/reconciliation/README.md).

## Airflow

```bash
docker compose up -d
```

The UI serves on `http://localhost:8080` (`admin` / `admin` — local demo
credentials only). Or execute a DAG headlessly:

```bash
docker compose exec airflow-scheduler airflow dags test orders_daily 2026-06-15
docker compose exec airflow-scheduler airflow dags test recon_daily 2026-06-28
```

| DAG | Schedule | Tasks |
|---|---|---|
| `orders_daily` | `@daily` | ingest → dbt build → report → data-quality gate |
| `recon_daily` | `@daily` | ingest → match + alert → report |

## Configuration

Everything works with defaults; the environment variables exist so CI,
containers, and throwaway experiments can point elsewhere.

| Variable | Required | Default | Description |
|---|---|---|---|
| `PLATFORM_DB` | No | `warehouse/platform.duckdb` | Warehouse file path (also read by the dbt profile) |
| `PLATFORM_RAW_DIR` | No | `raw/` | Directory the generators write and ingest reads |

## Testing

```bash
pytest tests/
ruff check .
```

52 tests: structural data quality (uniqueness, referential integrity, money
reconciled across layers), manifest-driven recall of every injected edge case,
full-pipeline idempotency by checksum, and 15 per-rule unit tests for the
matching waterfall on in-memory fixtures. dbt adds 36 schema tests inside
`dbt build`. CI (GitHub Actions) regenerates a 3-day sample and runs the
whole platform — generators, both pipelines, every test — on each push.

## Project documentation

- [`pipelines/orders/README.md`](pipelines/orders/README.md) — the orders pipeline: handling table, idempotency contract, modeling notes
- [`pipelines/reconciliation/README.md`](pipelines/reconciliation/README.md) — the matching waterfall, mismatch taxonomy, alerting rules
- [`docs/decisions/`](docs/decisions/) — ADR-000 … ADR-008, one per non-obvious choice
- [`docs/backlog.md`](docs/backlog.md) — deliberately out-of-scope work
- [`docs/blog/refund-restatement-th.md`](docs/blog/refund-restatement-th.md) — blog draft (Thai): refund restatement and the bugs found building this

## Roadmap

Shipped: both pipelines, dbt migration, Airflow-on-Docker, CI, ADRs. Next, in
rough order — marketing-attribution pipeline (multi-source ingest), promotion
of the warehouse to BigQuery (dbt makes this mostly a profile change), Airflow
3.x migration, and a product-analytics pipeline fed by real web events. The
full list with rationale lives in [`docs/backlog.md`](docs/backlog.md).

## License

MIT © Phasathat Jaruchitsophon

Synthetic data only — no real customer, order, or payment records exist
anywhere in this repository.
