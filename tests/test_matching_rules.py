"""Unit tests: every rule of the matching waterfall exercised in isolation on
tiny handcrafted fixtures (in-memory DuckDB, no warehouse needed).
"""

from __future__ import annotations

import duckdb
import pytest

from pipelines.reconciliation.matching import run_matching

GATEWAY_COLS = "txn_id, gateway_ref, amount, currency, fee, status, created_at, merchant_id, payment_method"
LEDGER_COLS = "entry_id, external_ref, amount, currency, posted_at, account_code, entry_type"


def make_con(gateway_rows: list[tuple], ledger_rows: list[tuple]) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET timezone = 'UTC'")
    con.execute("CREATE SCHEMA raw")
    con.execute(f"CREATE TABLE raw.gateway_txns ({GATEWAY_COLS.replace(', ', ' VARCHAR, ')} VARCHAR)")
    con.execute(f"CREATE TABLE raw.ledger_entries ({LEDGER_COLS.replace(', ', ' VARCHAR, ')} VARCHAR)")
    con.executemany(
        "INSERT INTO raw.gateway_txns VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", gateway_rows
    ) if gateway_rows else None
    con.executemany(
        "INSERT INTO raw.ledger_entries VALUES (?, ?, ?, ?, ?, ?, ?)", ledger_rows
    ) if ledger_rows else None
    return con


def g_row(txn_id="T1", ref="GW-ORD-100", amount="1000.00", fee="29.00",
          created="2026-06-28 10:00:00+00:00"):
    return (txn_id, ref, amount, "THB", fee, "captured", created, "M001", "card")


def l_row(entry_id="L1", ref="GW-ORD-100", amount="1000.00", currency="THB",
          posted="2026-06-28 17:30:00+07:00"):
    return (entry_id, ref, amount, currency, posted, "1102", "debit")


def buckets(con) -> dict[str, str]:
    """txn/entry id -> match_type."""
    out = {}
    for txn_id, entry_id, match_type in con.execute(
        "SELECT txn_id, entry_id, match_type FROM recon.recon_results"
    ).fetchall():
        for key in (txn_id, entry_id):
            if key is not None:
                out[key] = match_type
    return out


def test_exact_match():
    con = make_con([g_row()], [l_row()])
    run_matching(con)
    assert buckets(con) == {"T1": "exact", "L1": "exact"}


def test_prefix_stripping_still_exact():
    con = make_con([g_row(ref="GW-ORD-100")], [l_row(ref="ORD-100")])
    run_matching(con)
    assert buckets(con)["T1"] == "exact"


def test_dirty_currency_does_not_block_match():
    con = make_con([g_row()], [l_row(currency=" thb ")])
    run_matching(con)
    assert buckets(con)["T1"] == "exact"


def test_utc_midnight_crossing_is_date_boundary_not_missing():
    # 23:50 UTC settles 40 min later = next day in UTC; both serialized in
    # different zones. Without UTC normalization this reads as two missing rows.
    con = make_con(
        [g_row(created="2026-06-28 23:50:00+00:00")],
        [l_row(posted="2026-06-29 07:30:00+07:00")],  # = 00:30 UTC next day
    )
    run_matching(con)
    assert buckets(con) == {"T1": "date_boundary", "L1": "date_boundary"}


def test_rounding_difference_classified():
    con = make_con([g_row(amount="1000.00")], [l_row(amount="1000.03")])
    run_matching(con)
    assert buckets(con)["T1"] == "rounding"


def test_fee_timing_classified():
    con = make_con([g_row(amount="1000.00", fee="29.00")], [l_row(amount="971.00")])
    run_matching(con)
    assert buckets(con)["T1"] == "fee_timing"


def test_unexplained_amount_difference_is_amount_other():
    con = make_con([g_row(amount="1000.00")], [l_row(amount="500.00")])
    run_matching(con)
    assert buckets(con)["T1"] == "amount_other"


def test_gateway_without_ledger_is_missing_in_ledger():
    con = make_con([g_row()], [])
    run_matching(con)
    assert buckets(con) == {"T1": "missing_in_ledger"}


def test_ledger_without_gateway_is_missing_in_gateway():
    con = make_con([], [l_row()])
    run_matching(con)
    assert buckets(con) == {"L1": "missing_in_gateway"}


def test_similar_refs_same_money_flagged_as_ref_issue():
    con = make_con(
        [g_row(ref="GW-ORD-1005")],
        [l_row(ref="ORD-105")],  # one digit dropped by a human — lev distance 1
    )
    run_matching(con)
    assert buckets(con) == {"T1": "possible_ref_issue", "L1": "possible_ref_issue"}


def test_unrelated_refs_same_money_stay_missing_not_fuzzy_matched():
    # Same amount, same day, totally different refs: pairing them would hide
    # BOTH problems from finance. The similarity guard must refuse.
    con = make_con(
        [g_row(ref="GW-ORD-100")],
        [l_row(ref="GW-X-9999999")],
    )
    run_matching(con)
    assert buckets(con) == {"T1": "missing_in_ledger", "L1": "missing_in_gateway"}


def test_duplicate_ledger_posting_detected_once_matched_once():
    con = make_con(
        [g_row()],
        [l_row(entry_id="L1"), l_row(entry_id="L2")],
    )
    run_matching(con)
    b = buckets(con)
    assert b["T1"] == "exact"
    assert sorted([b["L1"], b["L2"]]) == ["duplicate_posting", "exact"]


def test_every_record_lands_in_exactly_one_bucket():
    con = make_con(
        [g_row("T1", "GW-A", "100.00"), g_row("T2", "GW-B", "200.00"),
         g_row("T3", "GW-C", "300.00")],
        [l_row("L1", "GW-A", "100.00"), l_row("L2", "GW-B", "200.05"),
         l_row("L3", "GW-Z", "999.00")],
    )
    run_matching(con)
    result_rows = con.execute("""
        SELECT count(DISTINCT txn_id) FILTER (WHERE txn_id IS NOT NULL),
               count(DISTINCT entry_id) FILTER (WHERE entry_id IS NOT NULL),
               count(*)
        FROM recon.recon_results""").fetchone()
    assert result_rows[0] == 3 and result_rows[1] == 3
    dup_assignments = con.execute("""
        SELECT count(*) FROM (
            SELECT txn_id FROM recon.recon_results
            WHERE txn_id IS NOT NULL GROUP BY txn_id HAVING count(*) > 1
        )""").fetchone()[0]
    assert dup_assignments == 0


@pytest.mark.parametrize("bad_amount", ["", "N/A"])
def test_unparseable_amounts_do_not_crash(bad_amount):
    con = make_con([g_row(amount=bad_amount)], [])
    run_matching(con)
    assert con.execute("SELECT count(*) FROM recon.recon_results").fetchone()[0] == 1
