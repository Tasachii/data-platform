-- Daily sales by channel and category, at order-line grain underneath.
--
-- Refund restatement: this fact is rebuilt full-refresh from current status,
-- so an order refunded 5 days later automatically disappears from the NET of
-- its ORIGINAL business_date (and shows in refund_amount there). gross/refund
-- are kept as separate columns so the restatement is visible, not silent.

CREATE OR REPLACE TABLE marts.fct_daily_sales AS
WITH lines AS (
    SELECT
        e.business_date,
        e.channel,
        p.category,
        e.order_id,
        e.status,
        li.qty * li.unit_price AS line_amount
    FROM intermediate.int_orders_enriched e
    JOIN staging.stg_order_items li ON e.order_id = li.order_id
    JOIN staging.stg_products p     ON li.product_id = p.product_id
)
-- Money only: line amounts are additive across every dimension of this grain.
-- Order COUNTS deliberately live in fct_daily_orders below — an order whose
-- lines span 3 categories would be counted 3 times here, and a SUM over
-- category groups would silently double-count (~2x on real data).
SELECT
    business_date,
    channel,
    category,
    COALESCE(SUM(line_amount) FILTER (WHERE status IN ('paid', 'shipped', 'delivered', 'refunded')), 0) AS gross_amount,
    COALESCE(SUM(line_amount) FILTER (WHERE status = 'refunded'), 0)                              AS refund_amount,
    COALESCE(SUM(line_amount) FILTER (WHERE status IN ('paid', 'shipped', 'delivered')), 0)       AS net_amount
FROM lines
GROUP BY business_date, channel, category
ORDER BY business_date, channel, category;

-- Order-grain rollup: one order has exactly one date and one channel, so
-- these counts ARE additive at this grain.
CREATE OR REPLACE TABLE marts.fct_daily_orders AS
SELECT
    business_date,
    channel,
    count(*) FILTER (WHERE status IN ('paid', 'shipped', 'delivered')) AS net_orders,
    count(*) FILTER (WHERE status = 'refunded')                        AS refunded_orders,
    COALESCE(SUM(total_amount) FILTER (WHERE status IN ('paid', 'shipped', 'delivered')), 0) AS net_amount
FROM intermediate.int_orders_enriched
GROUP BY business_date, channel
ORDER BY business_date, channel;
