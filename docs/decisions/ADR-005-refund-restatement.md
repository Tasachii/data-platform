# ADR-005: Refunds Restate the Original Business Date

**Status:** Accepted · 2026-07-05

## Context

3% of orders get refunded 1–7 days after purchase. Two defensible accounting
views exist: book the refund on the day it *happened* (event view), or reduce
the net of the day the order was *placed* (restatement view).

## Decision

Restatement: `fct_daily_sales` is rebuilt from **current** order status, so a
refund automatically moves its order out of NET on the original
`business_date`. Gross and refund stay visible as separate columns — the
restatement is auditable, not silent.

## Consequences

- "Net sales for June 3rd" means the same thing whenever you ask, once the
  refund window closes. Trend analysis doesn't see phantom dips on
  refund-processing days.
- The trade-off: yesterday's reported number can change for up to 7 days.
  The business must know a day is "final" only after the window passes —
  documented in the report.
- The event view isn't lost: `int_order_status_history` (SCD2) holds every
  transition with timestamps, so "refunds processed on day X" remains one
  query away.
- If both views were first-class requirements, the mart would gain a
  `fct_refund_events` table rather than overloading this one.
