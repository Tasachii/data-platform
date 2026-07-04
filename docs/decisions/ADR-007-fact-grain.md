# ADR-007: Fact Grain — Money at Line Grain, Counts at Order Grain

**Status:** Accepted · 2026-07-05

## Context

The business wants daily sales by channel **and by product category**.
Channel is an order attribute; category is a line attribute. During
development, `fct_daily_sales` at (date × channel × category) carried
`count(DISTINCT order_id)` — and the summary report totalled **1.24M orders
out of 600k real ones** (~2.2x), because an order whose lines span three
categories was counted in three groups.

## Decision

Two facts, each carrying only measures that are additive at its grain:

- `fct_daily_sales` (date × channel × category): **money only** — line
  amounts split cleanly across categories.
- `fct_daily_orders` (date × channel): **order counts** — one order has
  exactly one date and channel.

A regression test (`test_order_counts_are_not_inflated_by_category_grain`)
pins the invariant: fact order totals must equal an independent order-grain
count from staging.

## Consequences

- Report queries join the two facts on business_date; slightly more SQL,
  never a silently-wrong number.
- The general rule this encodes: **a measure belongs in a fact only if it is
  additive at that fact's grain**. Semi-additive measures get their own table
  or an explicit disclaimer.
