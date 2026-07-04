# ADR-003: Store UTC Instants, Report in Asia/Bangkok

**Status:** Accepted · 2026-07-05

## Context

Sources serialize timestamps inconsistently: the web shop emits `+00:00`, the
internal ledger emits `+07:00`, marketplace files mix both. The business
thinks in Bangkok calendar days.

## Decision

- Parse every timestamp to `TIMESTAMPTZ` (a UTC instant) at staging.
- Derive `business_date` = the instant viewed in `Asia/Bangkok`, **only** at
  the reporting layer, always via explicit `timezone('Asia/Bangkok', ts)`.
- Set `SET timezone='UTC'` on every connection so no implicit cast ever
  depends on the host machine (laptop = BKK, CI = UTC).

## Consequences

- A payment at 23:50 UTC and its ledger entry at 07:05 +07:00 are the *same
  instant* and reconcile as such (`date_boundary` bucket, not two missing rows).
- Bare `CAST(ts AS DATE)` is banned in models — it silently uses session
  timezone. This bit us during development: two tests passed locally and
  would have failed in CI. Explicit-timezone casts everywhere.
- Bangkok has no DST, but nothing in the code assumes that — the same design
  works for zones that do.
