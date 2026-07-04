-- Current orders enriched with customer and line aggregates.
-- business_date is the order's calendar date in Asia/Bangkok (reporting tz);
-- storage stays UTC. Orphan customer_ids map to 'unknown' — the revenue is
-- real even when the customer record never arrived.

CREATE OR REPLACE TABLE intermediate.int_orders_enriched AS
SELECT
    o.order_id,
    o.order_ts,
    o.updated_at,
    o.status,
    o.total_amount,
    o.channel,
    CAST(timezone('Asia/Bangkok', o.order_ts) AS DATE) AS business_date,
    COALESCE(c.customer_id, 'unknown')                 AS customer_id,
    o.customer_id                                      AS source_customer_id,
    c.region,
    COALESCE(i.n_lines, 0)                             AS n_lines,
    COALESCE(i.items_amount, 0)                        AS items_amount
FROM staging.stg_orders o
LEFT JOIN staging.stg_customers c
       ON o.customer_id = c.customer_id
LEFT JOIN (
    SELECT order_id, count(*) AS n_lines, SUM(qty * unit_price) AS items_amount
    FROM staging.stg_order_items
    GROUP BY order_id
) i ON o.order_id = i.order_id;
