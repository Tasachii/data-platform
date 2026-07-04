# ADR-002: Money Is DECIMAL, Never Float

**Status:** Accepted · 2026-07-05

## Context

Amounts flow through CSV (text) → raw (VARCHAR) → staging → marts, and the
reconciliation engine matches on amount **equality**.

## Decision

`DECIMAL(14,2)` from the first cast onward. No stage stores or compares
money as FLOAT/DOUBLE.

## Consequences

- `0.1 + 0.2 != 0.3` in binary floating point. A recon engine with float
  equality invents mismatches that don't exist and hides real ones behind
  tolerance fudge factors.
- Rounding classification (|diff| ≤ 0.05) and fee detection (diff == fee)
  stay exact; SUM() over 1.8M lines accumulates zero error.
- TRY_CAST to DECIMAL doubles as validation: unparseable amounts become NULL
  and land in the rejected quarantine with a reason.
