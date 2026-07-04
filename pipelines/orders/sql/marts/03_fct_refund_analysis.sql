-- Refund behaviour per category: which product categories bleed money?

CREATE OR REPLACE TABLE marts.fct_refund_analysis AS
WITH order_categories AS (
    SELECT DISTINCT
        e.order_id,
        e.status,
        p.category,
        e.total_amount
    FROM intermediate.int_orders_enriched e
    JOIN staging.stg_order_items li ON e.order_id = li.order_id
    JOIN staging.stg_products p     ON li.product_id = p.product_id
    WHERE e.status IN ('paid', 'shipped', 'delivered', 'refunded')
)
SELECT
    category,
    count(*)                                                    AS paid_orders,
    count(*) FILTER (WHERE status = 'refunded')                 AS refunded_orders,
    ROUND(count(*) FILTER (WHERE status = 'refunded') * 100.0 / count(*), 2) AS refund_rate_pct,
    COALESCE(SUM(total_amount) FILTER (WHERE status = 'refunded'), 0)        AS refunded_amount
FROM order_categories
GROUP BY category
ORDER BY refund_rate_pct DESC;
