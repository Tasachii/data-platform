# Reconciliation Pipeline

Automated daily reconciliation between the payment gateway's settlement files
and the internal accounting ledger — ~125k transactions over 7 days, every one
of which must end in **exactly one** explainable bucket. Replaces the
"finance team in Excel" workflow.

The payments are derived from the orders pipeline's own data (money-status
orders, last 7 days), so both pipelines describe the same business.

## Matching waterfall

```
                 ┌─ rule 1: exact ──────────── ref + amount + UTC date agree
                 ├─ rule 2: date_boundary ──── ref + amount agree, settlement crossed midnight
 gateway txns ──►├─ rule 3: ref agrees ─────── fee_timing   (diff == fee exactly)
 ledger entries  │                             rounding     (|diff| ≤ 0.05)
                 │                             amount_other (unexplained)
                 ├─ rule 4: possible_ref_issue amount + date agree AND refs look related
                 └─ rule 5: residuals ──────── missing_in_ledger / missing_in_gateway
 (pre-pass)      duplicate_posting ─────────── same (ref, amount) posted twice
```

**Normalize first, match second.** Refs are upper-trimmed and stripped of the
`GW-` prefix, currencies upper-trimmed (`thb` == `THB `), timestamps parsed to
UTC instants, amounts DECIMAL. Matching raw strings is how real recon breaks.

Two design points worth interrogating:

- **Rule 4 requires ref similarity** (containment or edit distance ≤ 4), not
  just same-money-same-day. Without the guard, one accidental amount collision
  per ~100k txns pairs two *genuinely missing* records and hides both from
  finance — observed on this dataset, pinned by
  `test_unrelated_refs_same_money_stay_missing_not_fuzzy_matched`.
- **date_boundary is a separate bucket**, not a failure: a 23:50 UTC payment
  legitimately posts after midnight. Normalizing both sides to UTC makes these
  match on ref+amount; keeping them out of `exact` preserves the audit trail.

## Mismatch types handled (all injected by the generator, all caught at 100% recall)

| Injected | Rate | Detected as |
|---|---|---|
| In gateway, absent from ledger | 1.5% | `missing_in_ledger` |
| In ledger, absent from gateway | 1.0% | `missing_in_gateway` |
| Rounding drift 0.01–0.05 | 2.0% | `rounding` |
| Ledger already net of fee | 1.0% | `fee_timing` |
| Double posting | 0.5% | `duplicate_posting` |
| Dirty currency strings | 0.3% | normalized → still `exact` |
| Missing `GW-` prefix | 5% | normalized → still `exact` |
| +07:00 vs UTC serialization | ~50% | normalized → `exact`/`date_boundary` |

## Alerting

Written to `recon.alerts` and logged (webhook-ready):

- `CRITICAL` — match rate < 97% of gateway txns
- `CRITICAL` — |net difference| > 10,000 THB/day
- `WARNING` — any duplicate postings

Alerts are business signals, not pipeline failures: a CRITICAL day exits 0 and
lands in the report; only execution errors fail the run.

## Money handling

Amounts are `DECIMAL(14,2)` everywhere. Floats are unacceptable for money:
`0.1 + 0.2 != 0.3` in binary floating point, and a reconciliation engine whose
equality checks wobble at the 15th bit will invent mismatches that do not
exist (and hide ones that do).

## Run it

```bash
python pipelines/reconciliation/run_recon.py --all
```

Outputs: `reports/recon_summary.md` + `reports/recon_unmatched.csv`
(the finance follow-up queue). Airflow DAG: `dags/recon_daily.py`.
