# ADR-008: Reconciliation as a Waterfall with a Similarity-Guarded Fuzzy Tier

**Status:** Accepted · 2026-07-05

## Context

~18k payments/day must be matched between two systems that disagree on
serialization (timezone, currency case, ref prefixes) and occasionally on
substance (fees, rounding, missing rows, double postings). The finance team
needs every transaction in exactly one explainable bucket.

## Decision

Ordered waterfall from strictest to loosest — exact → date-boundary →
ref-match-amount-differs (fee/rounding/other) → fuzzy → residuals — with two
hard rules:

1. **Normalize before matching** (UTC instants, upper-trim, strip `GW-`,
   DECIMAL). Serialization noise must die before rule 1, or it masquerades
   as substance in every later tier.
2. **The fuzzy tier requires refs to look related** (containment or
   Levenshtein ≤ 4), not merely same-amount-same-day. Without the guard, one
   accidental amount collision per ~100k txns pairs two *genuinely missing*
   records — hiding both from finance. Observed on this dataset, now pinned
   by a unit test.

Implemented as one SQL waterfall in DuckDB (not dbt models): matching is a
procedure with greedy 1:1 pairing, clearer as an engine than as a model DAG.
Unit tests drive each rule on tiny in-memory fixtures.

## Consequences

- Every record lands in exactly one bucket (completeness-tested); bucket
  counts per day sum to the gateway total.
- match_confidence gives finance a triage order: exact 1.0 → fuzzy 0.5.
- The loosest tier is where recon systems quietly lie; ours prefers two
  honest "missing" rows over one confident wrong match.
