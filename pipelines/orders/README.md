# Orders Pipeline

Daily batch pipeline for e-commerce orders: ~20,000 orders/day across 3 sales
channels, with the dirt real sources produce — duplicate resends, refunds
arriving up to 7 days late, late-arriving files, broken amounts, orphan
customers, and timestamps serialized in two different timezones.

## Flow

```
raw CSVs (daily)                    DuckDB warehouse
┌──────────────────┐   ingest    ┌──────┐ transform ┌─────────┐ ┌──────────────┐ ┌───────┐
│ orders_YYYY-MM-DD│ ──────────► │ raw  │ ─────────►│ staging │►│ intermediate │►│ marts │
│ order_items_...  │  (replace   └──────┘  (full    └─────────┘ └──────────────┘ └───────┘
│ products/custs   │   partition,           refresh)   dedup      SCD2 history    fct/dim
└──────────────────┘   ingest_log)                     reject     enrichment
```

Run it:

```bash
python pipelines/orders/run_pipeline.py --all                 # everything in raw/
python pipelines/orders/run_pipeline.py --date 2026-06-15 --skip-tests
python pipelines/orders/run_pipeline.py --start 2026-06-01 --end 2026-06-07 --skip-tests
```

A dated run reloads the selected source partitions and rebuilds the marts. Use
`--skip-tests` for a scoped backfill because the full pytest suite also exercises
all-date ingestion and the marketing backfill. dbt data tests run in either mode.

## The problems this pipeline actually solves

| Source behaviour | Handling | Proof |
|---|---|---|
| Duplicate resends (2%) — **not always byte-identical**: same instant can arrive as `+07:00` on one copy, `+00:00` on the other | Latest `updated_at` wins, with ingestion time and serialized order timestamp used to break ties | `test_duplicate_resends_collapse_to_one_row`, idempotency checksums |
| Refund arrives 1–7 days after the order (3%) | SCD2 status history (`valid_from`/`valid_to`/`is_current`); marts rebuild restates the refund onto the **original** business date | `test_refunds_are_restated_to_original_business_date` |
| Late-arriving orders (1%): day D order in day D+1's file | Facts key on `order_ts`, never on file date | `test_late_arriving_orders_land_on_their_order_date` |
| Null / negative amounts (0.5%) | Quarantined to `staging.rejected_orders` **with a reason** — never silently dropped; clean + rejected must equal total | `test_bad_amounts_are_rejected_with_reason_not_loaded`, accounting test |
| Orphan customer_id (1%) | Mapped to explicit `unknown` dim member — the revenue is real | `test_orphan_customers_map_to_unknown_never_dropped` |
| Mixed +00:00 / +07:00 timestamps | Everything stored as UTC instants; Asia/Bangkok applied only when deriving `business_date` for reporting | `test_mixed_timezones_all_parsed_to_utc_instants` |

## Idempotency contract

- **Ingest**: replace-partition by source file (`DELETE WHERE _source_file`, then
  insert), tracked in `meta.ingest_log`. Re-loading a file never appends.
- **Transforms**: pure `CREATE OR REPLACE` functions of raw.
- **Proof**: `test_full_rerun_changes_nothing` checksums all 10 tables, re-runs
  the entire pipeline in a subprocess, and asserts nothing moved.

## Modeling notes

- `fct_daily_sales` (date × channel × category) carries **money only** — line
  amounts are additive at that grain. Order **counts** live in
  `fct_daily_orders` (date × channel) because an order spanning 3 categories
  would be triple-counted otherwise. This exact bug appeared during
  development (1.24M "orders" from 600k real ones) and is now pinned by
  `test_order_counts_are_not_inflated_by_category_grain`.
- Money is `DECIMAL(14,2)` end to end. Floats do not touch amounts.

## Outputs

- `reports/sales_summary.md` — the morning business summary
- `pipelines/orders/example_queries.sql` — 5-query analyst pack
