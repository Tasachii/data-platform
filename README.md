# data-platform

End-to-end data platform simulating a Thai e-commerce/logistics company:
daily order ingestion with realistic dirty data, dbt-style warehouse modeling,
payment reconciliation, orchestrated with Airflow.

> **Status:** Phase 1 in progress — see `docs/decisions/` for the plan.

## Pipelines

| Pipeline | What it demonstrates | Status |
|---|---|---|
| [`pipelines/orders`](pipelines/orders/) | Incremental idempotent loads, late-arriving data, SCD2, refund restatement | 🚧 |
| [`pipelines/reconciliation`](pipelines/reconciliation/) | Waterfall matching, data quality, alerting | ⏳ |

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python generator/generate_orders.py          # simulate 30 days of source data
python pipelines/orders/run_pipeline.py --all
pytest tests/
```

Architecture diagram, design decisions and runbooks land in Phase 4.
Decision records live in [`docs/decisions/`](docs/decisions/).
