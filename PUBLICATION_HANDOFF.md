# Publication handoff

The static demo is ready for Test3 to review locally. Lead owns the GitHub push, Vercel project and public URL. The Vercel artifact consists of four files under [dashboard/](dashboard/). The JSON contains aggregate measures and dates. Raw feeds, manifests with record IDs, the unmatched queue, DuckDB and Airflow stay outside the site.

## Published sample

The order generator produced 2,000 orders per UTC day from June 1–30, 2026. Payments used June 24–30 source orders and ads used June 17–30. Seeds were 42, 43 and 44, respectively. The publication run included the late June 30 TikTok delivery. July 1 is a partial reporting day. It contains Bangkok-dated orders and UTC settlement spillover. Ad delivery ends June 30, while revenue can still be attributed on July 1.

| Measure | Verified result | Warehouse evidence |
|---|---:|---|
| Generated orders / raw order rows | 60,000 / 62,772 | Orders manifest, including resends and status updates |
| Net orders / refunded orders | 52,232 / 1,551 | Sum of order-grain counts in `marts.fct_daily_orders` |
| Gross / refunds / net | ฿597,230,705.68 / ฿17,088,447.27 / ฿580,142,258.41 | Line-grain sums in `marts.fct_daily_sales` |
| Quarantined orders | 300 | 138 negative amounts and 162 null or invalid amounts |
| Gateway / ledger records | 12,564 / 12,562 | Raw transaction counts equal the sum of `recon.recon_summary` counts |
| Matched gateway / signed settlement gap | 12,376 (98.50%) / −฿629,123.10 | Exact, date-boundary, fee, rounding and possible-ref counts over gateway count. Gap is gateway minus ledger. |
| Alerts | 8 critical, 7 warning | `recon.alerts` contains eight daily amount gaps and seven duplicate-posting warnings |
| Paid-attributed orders / revenue / spend | 18,418 / ฿204,803,918.53 / ฿3,995,635.73 | `marts.fct_channel_performance`, excluding organic |
| Blended paid ROAS | 51.26× | Sum of paid-attributed revenue divided by sum of spend |
| Organic orders / revenue | 6,140 / ฿68,136,564.26 | Organic attribution has zero ad spend |

The exported series have 93 date/channel sales rows, 8 settlement days, 15 date/severity/rule rows and 60 date/platform marketing rows. File-date coverage comes from three ingest-log rollups. The public export uses integer satang. Its 15,755 bytes have SHA-256 `34438b7602ababfd6cb40cdada41bcc43ad93693e7adae40db58cb4399c12264`.

## Repeat the verification

Run these commands at the repository root in a Python 3.11 environment with [requirements.txt](requirements.txt) installed. The first command creates fresh temporary inputs, builds the warehouse, tests it, writes the export to the chosen path and cleans up the temporary warehouse. Two independent builds matched byte for byte.

```bash
python scripts/rebuild_snapshot.py --output /tmp/commerce-rebuilt.json
cmp dashboard/data/snapshot.json /tmp/commerce-rebuilt.json
shasum -a 256 dashboard/data/snapshot.json
ruff check .
node --check dashboard/app.js
docker compose config --quiet
```

To export an existing complete simulation, point the exporter at its DuckDB file. This reads the source in read-only mode. Missing ad platform-days stop publication before the output is replaced.

```bash
python scripts/export_dashboard.py --db warehouse/platform.duckdb --output /tmp/commerce-local.json
```

The full sample passed **79 pytest cases**, including original order, matching, connector and marketing checks. Export coverage compares public totals with staging/raw tables, tests repeat exports and checks the committed JSON field allowlist. Markdown path checks resolved all 23 local references in the README, handoff and orders guide at preflight. The public directory inspection found no order references, emails or credential markers. Git listed no raw feeds, queue CSVs or database files. The orders dbt build passed 49 nodes, and the marketing build passed 49 nodes. The selections share dependencies. The manifest contains **53 distinct data tests, 20 models and 2 seeds**.

The [CI recipe](.github/workflows/ci.yml) also ran locally with a fresh three-day, 6,000-order sample. It passed **78 tests with one skip**. The trailing-volume test needs eight days. Backfilling TikTok and rerunning the two export tests passed. `dbt docs generate --project-dir dbt --profiles-dir dbt` produced the catalog. The existing Pages jobs still publish dbt docs after a successful main-branch run.

## Airflow compatibility

The Docker image built with Airflow 2.10.5, DuckDB 1.1.3 and dbt-core 1.7.19. Its final pip check reported `No broken requirements found`. The DAG test used temporary copies of the project and three-day source files, a container-built warehouse, SQLite test metadata and disabled networking. The Compose configuration validated separately. This exercises DAG tasks and dependencies without starting the webserver, Postgres or a persistent scheduler.

The initial orders retry exposed a duplicate primary-key exception on `meta.ingest_log.file_name`. The corrected upsert let the same dated load finish. A fresh container then repeated the three pipelines and all three DAG tests against the existing scratch warehouse without a retry. Each command below reported `state=success` for the June 28 logical date. The in-container orders quality gate passed 78 tests and skipped the short-history check.

```bash
docker build -t data-platform-dev3-preflight:local .
```

Inside the image, with a scratch project mounted at `/opt/airflow/repo`, the three-day raw sample in its `raw/`, and `AIRFLOW__CORE__DAGS_FOLDER=/opt/airflow/repo/dags`, run these commands.

```bash
cd /opt/airflow/repo
export PLATFORM_DB=/opt/airflow/repo/warehouse/platform.duckdb
export DBT_SEND_ANONYMOUS_USAGE_STATS=false
airflow db migrate
python pipelines/orders/run_pipeline.py --all --skip-tests
python pipelines/reconciliation/run_recon.py --all
python pipelines/marketing/run_marketing.py --all --include-late
airflow dags test orders_daily 2026-06-28
airflow dags test recon_daily 2026-06-28
airflow dags test marketing_daily 2026-06-28
```

## Findings addressed

| Finding | Change and evidence |
|---|---|
| Seeded sources could assign payments and UTM touches to different orders tied on timestamp | The shared loader sorts by timestamp and order ID before applying the RNG. NumPy is pinned. Independent clean builds matched the recorded hash. |
| Small marketing windows could request more duplicate-injection dates than existed | The generator caps the sample size at the number of days available. A one-day run produced 26 ad rows and 1,784 touches. The orders build passed all 49 selected nodes on the same zero-refund sample. |
| A ledger-only date vanished from the daily summary | The full date join retains its balance and yields a null match rate when the gateway count is zero. A regression fixture retained a −฿12,500 day and emitted a critical gap alert. |
| Identical, legitimate order lines could collapse in staging | Line staging preserves the file's rows. Ingestion replaces the whole partition on resend. The refund assertion now includes categories with zero refunds. |
| A different raw path or sample size could pollute local data or overwrite the checked-in reports | All generators honor the raw-directory setting and all reports honor the report-directory setting. The snapshot recipe isolates both plus the database. |
| Airflow's pinned DuckDB rejected repeat ingestion of an existing log key | The ingest log now uses one atomic upsert. File replacement and the matching log write stay in the same transaction. |
| README counts, example reports and reporting-window claims referred to different runs | All three tracked reports now match the public sample. README distinguishes source days, reporting days, CI skips and generator defaults. |

## Browser preflight

Serve `dashboard/` over HTTP and open it in a browser.

```bash
python3 -m http.server 8000 --bind 127.0.0.1 --directory dashboard
```

Chromium rendered the full snapshot at 1400 × 940 and 375 × 812. The mobile document stayed within the viewport. Last 7 days showed seven trend bars. The Shopee filter changed the sales total. Focusing a bar exposed its date, value and order count. Warning showed six alert dates in the last seven days. First 7 days displayed empty payment and marketing states. The attribution link navigated to its section. A forced JSON 404 produced the retry message. The normal path produced no unexpected HTTP or JavaScript errors. [Sales screenshot](docs/images/commerce-overview.png) · [Settlement and attribution screenshot](docs/images/settlement-and-attribution.png)

| Craft QA angle | Score | Five checks |
|---|---:|---|
| CTO | 8/10 | ✓ defined scope · ✓ aggregate data boundary · ✓ reproducible setup · ✓ static serving · ✓ repository license |
| Tech lead | 8/10 | ✓ readable queries · ✓ separate export and UI · ✓ source-total checks · ✓ lint · ⚠ browser flow checked locally |
| UX/UI | 8/10 | ✓ chart hierarchy · ✓ scoped filters · ⚠ keyboard checks only, no screen-reader session · ✓ metric definitions · ✓ small-screen and empty states |
| QA | 8/10 | ✓ static smoke · ✓ warehouse-to-browser flow · ✓ late/empty/ledger-only cases · ✓ failed fetch · ⚠ hosted verification pending |

Overall preflight **8/10**. Local checks cover the static publication path. Public routing and access still require a real deployed URL.

## Hosting and remaining limits

1. After Test3 reviews the local changes, Lead can push the approved commits and import `Tasachii/data-platform` into Vercel.
2. Choose project root `dashboard`, framework **Other**, an empty build-command override and output directory `.`. The site needs no install step or environment variables. [Vercel static build settings](https://vercel.com/docs/builds/configure-a-build)
3. Open the production URL signed out. Verify the headline, a filter change, and `/data/snapshot.json` against the SHA-256 above. Record the verified public URL in the README.
4. Check the GitHub Actions CI and Pages jobs on the published commit. Pages serves the dbt catalog and lineage.

The site is a fixed synthetic snapshot. A new warehouse run reaches the public site only after export and publication. Attribution uses one simulated UTM assignment per eligible order. Platform-local ad days and Bangkok order dates can differ at boundaries. The high ROAS comes from generator assumptions and should not be interpreted as an observed business return. Alerts are simulated business signals. The alert table and report are the delivery endpoints.

The local and Airflow environments use different DuckDB/dbt versions. Use separate database files. Airflow caps active runs per DAG, while overlapping different DAGs can still contend for DuckDB's writer lock. The local dbt build also reports a generic-test syntax deprecation; the current syntax is shared with the older Airflow dbt stack.
