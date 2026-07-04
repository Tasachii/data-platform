"""Recall proof: every edge case the generator injected (recorded in
raw/_manifest.json) must be caught and handled by the pipeline — 100%,
not "mostly". Each test maps one injected failure mode to its handling.
"""

from __future__ import annotations

from tests.conftest import one


def _ids(manifest: dict, key: str) -> list[str]:
    return sorted(set(manifest["edge_cases"][key]))


def test_duplicate_resends_collapse_to_one_row(con, manifest):
    dup_ids = _ids(manifest, "duplicates")
    over = one(con, """
        SELECT count(*) FROM (
            SELECT order_id FROM staging.stg_orders
            WHERE order_id IN (SELECT unnest(?))
            GROUP BY order_id HAVING count(*) > 1
        )""", [dup_ids])
    assert over == 0, f"{over} duplicated ids kept more than one row"


def test_retro_refunds_have_scd2_history_and_current_refunded(con, manifest):
    retro_ids = _ids(manifest, "retro_status_changes")

    single_version = one(con, """
        SELECT count(*) FROM (
            SELECT order_id FROM intermediate.int_order_status_history
            WHERE order_id IN (SELECT unnest(?))
            GROUP BY order_id HAVING count(*) < 2
        )""", [retro_ids])
    assert single_version == 0, (
        f"{single_version} retro-changed orders have no second SCD2 version"
    )

    current_refunded = one(con, """
        SELECT count(*) FROM intermediate.int_order_status_history
        WHERE order_id IN (SELECT unnest(?))
          AND is_current AND status = 'refunded'""", [retro_ids])
    assert current_refunded == len(retro_ids), (
        f"only {current_refunded}/{len(retro_ids)} retro refunds end in current status 'refunded'"
    )

    open_intervals = one(con, """
        SELECT count(*) FROM intermediate.int_order_status_history
        WHERE order_id IN (SELECT unnest(?))
          AND NOT is_current AND valid_to IS NULL""", [retro_ids])
    assert open_intervals == 0, "non-current SCD2 rows must have valid_to closed"


def test_refunds_are_restated_to_original_business_date(con, manifest):
    """A refund arriving days later must reduce the ORIGINAL order date's net,
    not the date the refund arrived. Compare per-date refund totals in the
    fact against an independent recompute from staging."""
    mismatched_dates = one(con, """
        WITH expected AS (
            SELECT CAST(timezone('Asia/Bangkok', o.order_ts) AS DATE) AS business_date,
                   SUM(li.qty * li.unit_price) AS refund_amount
            FROM staging.stg_orders o
            JOIN staging.stg_order_items li USING (order_id)
            WHERE o.status = 'refunded'
            GROUP BY 1
        ),
        actual AS (
            SELECT business_date, SUM(refund_amount) AS refund_amount
            FROM marts.fct_daily_sales
            GROUP BY 1
        )
        SELECT count(*)
        FROM expected e
        FULL JOIN actual a USING (business_date)
        WHERE abs(COALESCE(e.refund_amount, 0) - COALESCE(a.refund_amount, 0)) > 0.01
    """)
    assert mismatched_dates == 0


def test_late_arriving_orders_land_on_their_order_date(con, manifest):
    """Late orders arrive in day D+1's file but must report under day D."""
    late_ids = _ids(manifest, "late_arriving")
    # Retro refunds and rejected orders legitimately carry a different source
    # file; exclude them so the assertion isolates pure late arrivals.
    exclude = set(manifest["edge_cases"]["retro_status_changes"]) | set(
        manifest["edge_cases"]["bad_amounts"]
    )
    pure_late = sorted(set(late_ids) - exclude)

    wrong = one(con, """
        SELECT count(*) FROM staging.stg_orders
        WHERE order_id IN (SELECT unnest(?))
          AND CAST(regexp_extract(_source_file, '(\\d{4}-\\d{2}-\\d{2})', 1) AS DATE)
              != CAST(timezone('UTC', order_ts) AS DATE) + 1""", [pure_late])
    assert wrong == 0, f"{wrong} late orders not sourced from the D+1 file"

    missing = len(pure_late) - one(con, """
        SELECT count(*) FROM staging.stg_orders
        WHERE order_id IN (SELECT unnest(?))""", [pure_late])
    assert missing == 0, f"{missing} late-arriving orders were lost"


def test_bad_amounts_are_rejected_with_reason_not_loaded(con, manifest):
    bad_ids = _ids(manifest, "bad_amounts")

    in_clean = one(con, "SELECT count(*) FROM staging.stg_orders WHERE order_id IN (SELECT unnest(?))", [bad_ids])
    assert in_clean == 0, f"{in_clean} bad-amount orders leaked into stg_orders"

    rejected = one(con, """
        SELECT count(*) FROM staging.rejected_orders
        WHERE order_id IN (SELECT unnest(?))
          AND reject_reason IN ('amount_null_or_invalid', 'amount_negative')""", [bad_ids])
    assert rejected == len(bad_ids), (
        f"only {rejected}/{len(bad_ids)} injected bad amounts were quarantined"
    )


def test_orphan_customers_map_to_unknown_never_dropped(con, manifest):
    orphan_ids = set(manifest["edge_cases"]["orphan_customers"])
    # Orders that are BOTH orphaned and bad-amount get rejected for the amount.
    expected = sorted(orphan_ids - set(manifest["edge_cases"]["bad_amounts"]))

    unknown_count = one(con, "SELECT count(*) FROM intermediate.int_orders_enriched WHERE customer_id = 'unknown'")
    assert unknown_count == len(expected), (
        f"expected {len(expected)} 'unknown'-customer orders, found {unknown_count}"
    )

    matched = one(con, """
        SELECT count(*) FROM intermediate.int_orders_enriched
        WHERE customer_id = 'unknown' AND order_id IN (SELECT unnest(?))""", [expected])
    assert matched == len(expected)


def test_invalid_emails_flagged_but_customers_kept(con, manifest):
    bad_customer_ids = _ids(manifest, "invalid_emails")

    kept = one(con, "SELECT count(*) FROM staging.stg_customers WHERE customer_id IN (SELECT unnest(?))", [bad_customer_ids])
    assert kept == len(bad_customer_ids), "customers with bad emails must not be dropped"

    flagged = one(con, """
        SELECT count(*) FROM staging.stg_customers
        WHERE customer_id IN (SELECT unnest(?)) AND NOT email_is_valid""", [bad_customer_ids])
    assert flagged == len(bad_customer_ids), (
        f"only {flagged}/{len(bad_customer_ids)} injected bad emails were flagged"
    )

    false_positives = one(con, """
        SELECT count(*) FROM staging.stg_customers
        WHERE customer_id NOT IN (SELECT unnest(?)) AND NOT email_is_valid""", [bad_customer_ids])
    assert false_positives == 0, f"{false_positives} valid emails wrongly flagged"


def test_mixed_timezones_all_parsed_to_utc_instants(con, manifest):
    unparseable = one(con, """
        SELECT count(*) FROM staging.rejected_orders
        WHERE reject_reason = 'unparseable_timestamp'""")
    assert unparseable == 0, "source emits valid +00:00/+07:00 offsets; nothing should fail parsing"

    col_type = one(con, """
        SELECT data_type FROM duckdb_columns()
        WHERE schema_name = 'staging' AND table_name = 'stg_orders' AND column_name = 'order_ts'""")
    assert col_type == "TIMESTAMP WITH TIME ZONE", f"order_ts stored as {col_type}"

    # Compare in explicit UTC — a bare CAST(ts AS DATE) follows the session
    # timezone and would give different answers on this laptop (BKK) vs CI (UTC).
    out_of_window = one(con, """
        SELECT count(*) FROM staging.stg_orders
        WHERE CAST(timezone('UTC', order_ts) AS DATE) < CAST(? AS DATE)
           OR CAST(timezone('UTC', order_ts) AS DATE) > CAST(? AS DATE)""",
        [manifest["start_date"], manifest["end_date"]])
    assert out_of_window == 0, "a timezone mishandled by ±7h would push orders outside the window"
