# ADR-004: Idempotency — Replace-Partition Ingest, Full-Refresh Transforms

**Status:** Accepted · 2026-07-05

## Context

Files get re-delivered, backfills get re-run, and the same DAG run can retry.
"Run it again" must never mean "count it twice".

## Decision

- **Ingest**: partition raw tables by `_source_file`; loading a file means
  `DELETE WHERE _source_file = ?` then INSERT, logged in `meta.ingest_log`.
  Never append-only.
- **Transforms**: every model is a pure `CREATE OR REPLACE` function of raw —
  full refresh, deterministic output.
- **Proof, not promise**: `test_full_rerun_changes_nothing` checksums all ten
  tables, re-runs the entire pipeline in a subprocess, and asserts equality.

## Consequences

- Backfilling one day cannot corrupt any other day.
- Determinism is a hard requirement this surfaced: "identical" source resends
  can serialize the same instant in different timezone offsets, so dedup
  tie-breaks must be a total ordering over **content**, or the surviving row
  flips between runs (caught by the checksum test during development).
- Full-refresh transforms trade compute for simplicity — fine at 600k orders.
  At real scale the marts would become incremental models keyed on
  `business_date`; the restatement window (7 days) defines the reprocess span.
