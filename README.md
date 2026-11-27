# Thai commerce data platform

I built this project to understand what happens to a sales report when a shop gets a late refund, a payment gateway disagrees with the ledger, or an ad file arrives a day late. The three pipelines follow the same simulated Thai retailer, so I can trace an order from its source file to sales, settlement and last-touch marketing revenue. All business records are synthetic.

[![CI](https://github.com/Tasachii/data-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/Tasachii/data-platform/actions/workflows/ci.yml)

## Explore the dashboard

[Open the live commerce dashboard](https://data-platform-amber.vercel.app/).

For a local preview, serve the checked-in snapshot from the repository root with Python, then open `http://localhost:8000`.

```bash
python3 -m http.server 8000 --bind 127.0.0.1 --directory dashboard
```

| Sales and refunds | Settlement gaps and last-touch revenue |
|---|---|
| ![Daily sales chart and channel breakdown](docs/images/commerce-overview.png) | ![Daily gateway differences, triggered alerts and attributed return by platform](docs/images/settlement-and-attribution.png) |

The snapshot contains **60,000 generated orders** across 30 UTC source days ending June 30, 2026. Of those, 52,232 orders remain paid, shipped or delivered, worth **฿580,142,258.41** in net sales. Payment files cover the last 7 source days and ad files the last 14. Bangkok order dates and UTC settlements extend into July 1. The reporting-window filter applies across the page. The channel selector applies to sales, and the severity selector applies to alerts.

## Quickstart

Use Python 3.11 for the local pipeline. Docker is only needed for Airflow. In a fresh checkout, create an environment and install the local requirements.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

To reproduce the dashboard, run the generators, pipelines, test suite and aggregate export in one command. It uses temporary raw, report and warehouse directories. The public output is [dashboard/data/snapshot.json](dashboard/data/snapshot.json).

```bash
python scripts/rebuild_snapshot.py
```

To keep a warehouse for SQL exploration, run the stages directly. These commands use the generator defaults of 30 days and 20,000 orders per day. Use an empty raw directory and a fresh warehouse when changing sample size or dates. The final marketing run loads the held-back TikTok file.

```bash
python generator/generate_orders.py
python generator/generate_payments.py
python generator/generate_marketing.py
python pipelines/orders/run_pipeline.py --all --skip-tests
python pipelines/reconciliation/run_recon.py --all
python pipelines/marketing/run_marketing.py --all --include-late
python -m pytest tests/ -q
```

The three [sample reports](reports/) in Git use the smaller published snapshot. Local pipeline runs replace the reports with results from the current warehouse. Set `PLATFORM_RAW_DIR`, `PLATFORM_DB` and `PLATFORM_REPORT_DIR` to choose different paths. Defaults are `raw/`, `warehouse/platform.duckdb` and `reports/`.

## From files to figures

| Pipeline | What it does | How to inspect it |
|---|---|---|
| Orders | Replaces source partitions, keeps the current order version, quarantines invalid amounts and rebuilds sales by Bangkok business date. Refunds reduce net sales on the original date. | [Orders](pipelines/orders/README.md) · [Example SQL](pipelines/orders/example_queries.sql) |
| Reconciliation | Compares gateway transactions with ledger postings, starting with exact matches and then checking settlement dates, fees, rounding and similar references. Thresholds produce daily alerts. | [Matching rules](pipelines/reconciliation/README.md) · [Payment report](reports/recon_summary.md) |
| Marketing | Reads Facebook, Google and TikTok files, converts spend to THB and maps UTM variants and campaign names. A qualifying order contributes its revenue to one simulated source. | [Attribution assumptions](pipelines/marketing/README.md) · [Marketing report](reports/marketing_summary.md) |

DuckDB holds the raw, staging, intermediate and reporting tables. dbt builds the sales and marketing marts. Counts come from order grain, while sales and refund amounts come from line grain. The public exporter reads aggregate results in read-only mode and writes monetary values as integer satang. It checks that each expected ad platform-day reached staging before publishing. [Design decisions](docs/decisions/) · [Refund restatement walkthrough in Thai](docs/blog/refund-restatement-th.md)

## Airflow and hosting

The local Docker Compose stack runs Airflow 2.10.5 with Postgres metadata. Generate the raw files first. Use a separate warehouse file for the container when switching between the local and Airflow dependency sets. The Compose file sets the container warehouse to `warehouse/platform.duckdb` in the mounted repo. Use `PLATFORM_DB` for an alternate **local** file before building with the newer DuckDB version.

```bash
docker compose up -d
```

The demo binds the Airflow UI to `http://127.0.0.1:8080` on host loopback. The three daily DAGs are [orders_daily](dags/orders_daily.py), [recon_daily](dags/recon_daily.py) and [marketing_daily](dags/marketing_daily.py). Each DAG caps its own active runs at one. Schedule warehouse writes sequentially across DAGs because DuckDB permits one writer process at a time.

For Vercel, use **dashboard** as the project root and serve its static files. GitHub Pages has a separate workflow for the dbt catalog and lineage. [Publication handoff](PUBLICATION_HANDOFF.md)

## Verification

```bash
ruff check .
python -m pytest tests/ -q
node --check dashboard/app.js
dbt docs generate --project-dir dbt --profiles-dir dbt
```

The dashboard build passed all **81 pytest cases**. The dbt manifest contains **20 models, 53 data tests and 2 seeds**. The three-day CI recipe exercises late delivery and skips the volume-history check, which requires at least eight days. A separate CI job runs a Playwright Chromium smoke against the checked-in dashboard, covering first render, filters and empty states. Full commands, counts, limitations and the snapshot checksum are in the [publication handoff](PUBLICATION_HANDOFF.md).

## License

MIT © Phasathat Jaruchitsophon. [License](LICENSE)
