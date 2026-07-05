# Marketing Attribution Pipeline

Unifies ad performance from three platforms that agree on nothing — file
format, timezone, currency, or campaign naming — and joins it to
warehouse-attributed order revenue for ROAS the growth team can defend.
~340 ad rows/14 days at campaign/ad grain, 250k UTM touches pointing at the
platform's own orders.

## Three sources, three formats (the point)

| Platform | Format | Currency | Date style | Reporting timezone | Quirks injected |
|---|---|---|---|---|---|
| Facebook | nested JSON (campaign → adset → ad) | USD | `YYYY-MM-DD` | America/Los_Angeles | ad rows with spend > 0, impressions = 0 |
| Google | CSV with 2 metadata lines before the header | THB | `DD/MM/YYYY` | Asia/Bangkok | comma-thousands costs (`"12,450.00"`), `N/A` conversions, exact duplicate rows, **no campaign_id** |
| TikTok | plain CSV | USD | `YYYYMMDD` | UTC | final day's file delivered late |

One connector class per platform (`connectors.py`) normalizes **structure** —
flattening, header-skipping, date parsing — into a unified schema. **Values**
(comma stripping, `N/A`, USD→THB via the fx table, casts) are cleaned in dbt
staging, where a bad value can be quarantined with a reason instead of dying
inside a parser.

## Identity problems and their seeds

- `fb` / `FB_ads` / `Facebook` / `adwords` / `tt` … → platform, via
  `dbt/seeds/utm_source_mapping.csv`. Unknown variants stay NULL and fail
  `test_no_unmapped_utm_sources` instead of vanishing.
- "Mega Sale 6.6" (FB) = `mega_sale_6.6_TH` (Google) = "MEGA SALE 66" (TikTok)
  → one canonical campaign, via `campaign_canonical_mapping.csv`, with a
  normalized-name fallback so unmapped campaigns surface as themselves rather
  than disappearing.

## Late files are a state, not an error

TikTok's final-day file sits in `raw/late_arrivals/` until it "arrives". The
pipeline loads what exists, WARNs about the gap, and the report says exactly
which days are understated. Backfill when it lands:

```bash
python pipelines/marketing/run_marketing.py --date 2026-06-30 --include-late
```

Replace-partition ingest makes the re-run safe; the gap-then-backfill flow is
covered by `test_late_tiktok_file_is_a_gap_not_a_failure` and
`test_backfill_late_tiktok_file_fills_the_gap`.

## Attribution model — and what it gets wrong

Last-touch on the order's UTM: each order's net revenue
(paid/shipped/delivered — a refund removes it, consistent with the sales
marts) goes to the single campaign that brought it. Deliberate limitations,
stated rather than hidden:

- Multi-touch journeys don't exist here; the last click takes everything.
- Ad platforms report by their **own calendar day** (Facebook by
  Los Angeles time). Daily aggregates cannot be re-cut to UTC, so
  `report_date` joins the order's Bangkok `business_date` as-is —
  a known, bounded imprecision at midnight boundaries.
- Platform-reported conversions and warehouse-attributed orders are shown
  side by side and **never** reconciled into one number — they measure
  different things and pretending otherwise is how marketing dashboards lie.
- `organic` keeps its own bucket. Dropping NULL-UTM orders would silently
  overstate every paid channel's share.

## Run it

```bash
python pipelines/marketing/run_marketing.py --all
```

Outputs `reports/marketing_summary.md` — blended ROAS, channel scoreboard,
cross-platform campaign rollup, and the data-quality notes (late files,
`N/A` conversions) that say how much to trust today's numbers.
Airflow DAG: `dags/marketing_daily.py`.
