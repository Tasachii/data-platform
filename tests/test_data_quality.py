"""Structural data-quality tests: uniqueness, nullability, referential
integrity, money reconciliation across layers, freshness and volume anomaly.
"""

from __future__ import annotations

import pytest

from tests.conftest import one

KEY_COLUMNS = ["order_id", "order_ts", "updated_at", "status", "total_amount", "channel"]


def test_stg_orders_order_id_unique(con):
    dupes = one(con, """
        SELECT count(*) FROM (
            SELECT order_id FROM staging.stg_orders GROUP BY order_id HAVING count(*) > 1
        )""")
    assert dupes == 0, f"{dupes} duplicated order_ids survived staging dedup"


@pytest.mark.parametrize("column", KEY_COLUMNS)
def test_stg_orders_key_columns_not_null(con, column):
    nulls = one(con, f"SELECT count(*) FROM staging.stg_orders WHERE {column} IS NULL")
    assert nulls == 0, f"stg_orders.{column} has {nulls} NULLs"


def test_every_enriched_customer_exists_in_dim(con):
    missing = one(con, """
        SELECT count(*)
        FROM intermediate.int_orders_enriched e
        LEFT JOIN marts.dim_customers d USING (customer_id)
        WHERE d.customer_id IS NULL""")
    assert missing == 0, f"{missing} orders reference customers missing from dim_customers"


def test_every_item_product_exists_in_dim(con):
    missing = one(con, """
        SELECT count(*)
        FROM staging.stg_order_items li
        LEFT JOIN marts.dim_products d USING (product_id)
        WHERE d.product_id IS NULL""")
    assert missing == 0


def test_fct_net_equals_gross_minus_refund(con):
    broken = one(con, """
        SELECT count(*) FROM marts.fct_daily_sales
        WHERE net_amount != gross_amount - refund_amount""")
    assert broken == 0


def test_reconciliation_marts_net_vs_staging(con):
    """Independent recompute: money must not appear or vanish between layers."""
    fct_net = one(con, "SELECT COALESCE(SUM(net_amount), 0) FROM marts.fct_daily_sales")
    staging_net = one(con, """
        SELECT COALESCE(SUM(li.qty * li.unit_price), 0)
        FROM staging.stg_orders o
        JOIN staging.stg_order_items li USING (order_id)
        WHERE o.status IN ('paid', 'shipped', 'delivered')""")
    assert abs(float(fct_net) - float(staging_net)) < 0.01, (
        f"marts net {fct_net} != staging net {staging_net}"
    )


def test_order_total_matches_line_sum(con):
    """The source computes total_amount from its lines — so must we."""
    broken = one(con, """
        SELECT count(*)
        FROM staging.stg_orders o
        JOIN (
            SELECT order_id, SUM(qty * unit_price) AS line_total
            FROM staging.stg_order_items GROUP BY order_id
        ) li USING (order_id)
        WHERE abs(o.total_amount - li.line_total) > 0.01""")
    assert broken == 0, f"{broken} orders where header total != sum of lines"


def test_order_counts_are_not_inflated_by_category_grain(con):
    """Regression guard: order counts must come from order grain. Counting
    distinct orders inside (date, channel, category) groups double-counts
    multi-category orders when summed (observed ~2.2x on this dataset)."""
    fct_orders = one(con, "SELECT SUM(net_orders) FROM marts.fct_daily_orders")
    true_orders = one(con, """
        SELECT count(*) FROM staging.stg_orders
        WHERE status IN ('paid', 'shipped', 'delivered')""")
    assert fct_orders == true_orders, f"fct says {fct_orders} orders, staging says {true_orders}"


def test_rejected_records_all_have_reasons(con):
    missing = one(con, "SELECT count(*) FROM staging.rejected_orders WHERE reject_reason IS NULL")
    assert missing == 0


def test_accounting_clean_plus_rejected_covers_all_orders(con):
    """No silent drops: every distinct raw order_id is either clean or rejected."""
    raw_ids = one(con, "SELECT count(DISTINCT order_id) FROM raw.orders")
    clean = one(con, "SELECT count(*) FROM staging.stg_orders")
    rejected = one(con, "SELECT count(*) FROM staging.rejected_orders")
    assert clean + rejected == raw_ids, (
        f"clean({clean}) + rejected({rejected}) != distinct raw ids({raw_ids})"
    )


def test_freshness_latest_generated_day_is_loaded(con, manifest):
    latest_loaded = one(con, "SELECT CAST(max(file_date) AS VARCHAR) FROM meta.ingest_log")
    assert latest_loaded == manifest["end_date"], (
        f"warehouse is stale: latest loaded file is {latest_loaded}, "
        f"source has data through {manifest['end_date']}"
    )


def test_anomaly_daily_volume_within_50pct_of_trailing_avg(con):
    """ALERT-style check: a day whose raw volume deviates >50% from its own
    trailing 7-day average points at a broken or double-shipped source file."""
    n_days = one(con, "SELECT count(DISTINCT file_date) FROM meta.ingest_log WHERE table_name = 'orders'")
    if n_days < 8:
        pytest.skip("need 8+ days of history for a trailing 7-day average")
    anomalies = con.execute("""
        WITH daily AS (
            SELECT file_date, SUM(row_count) AS rows
            FROM meta.ingest_log WHERE table_name = 'orders'
            GROUP BY file_date
        ),
        with_avg AS (
            SELECT file_date, rows,
                   AVG(rows) OVER (ORDER BY file_date ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING) AS trail
            FROM daily
        )
        SELECT file_date, rows, ROUND(trail) AS trailing_avg
        FROM with_avg
        WHERE trail IS NOT NULL AND abs(rows - trail) / trail > 0.5
    """).fetchall()
    assert not anomalies, f"ALERT volume anomaly on: {anomalies}"
