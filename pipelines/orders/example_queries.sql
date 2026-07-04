-- Analyst query pack: the five questions the business actually asks.
-- Run any of these against warehouse/platform.duckdb.

-- 1. Yesterday's sales vs the same weekday last week, by channel.
WITH latest AS (SELECT max(business_date) AS d FROM marts.fct_daily_sales)
SELECT
    f.channel,
    SUM(net_amount) FILTER (WHERE business_date = (SELECT d FROM latest))            AS yesterday,
    SUM(net_amount) FILTER (WHERE business_date = (SELECT d - 7 FROM latest))        AS same_day_last_week,
    ROUND(100.0 * (SUM(net_amount) FILTER (WHERE business_date = (SELECT d FROM latest))
         / NULLIF(SUM(net_amount) FILTER (WHERE business_date = (SELECT d - 7 FROM latest)), 0) - 1), 1) AS pct_change
FROM marts.fct_daily_sales f
GROUP BY f.channel;

-- 2. Top 10 product categories by net revenue, with refund drag.
SELECT category,
       SUM(net_amount)                          AS net_revenue,
       SUM(refund_amount)                       AS refunded,
       ROUND(SUM(refund_amount) * 100.0 / NULLIF(SUM(gross_amount), 0), 2) AS refund_pct_of_gross
FROM marts.fct_daily_sales
GROUP BY category
ORDER BY net_revenue DESC
LIMIT 10;

-- 3. How long do orders take to be refunded? (SCD2 history in action)
SELECT
    date_diff('day', first_seen.valid_from, refunded.valid_from) AS days_to_refund,
    count(*) AS orders
FROM intermediate.int_order_status_history refunded
JOIN (
    SELECT order_id, min(valid_from) AS valid_from
    FROM intermediate.int_order_status_history
    GROUP BY order_id
) first_seen USING (order_id)
WHERE refunded.status = 'refunded'
GROUP BY 1
ORDER BY 1;

-- 4. Regional revenue concentration (orphan customers stay visible as 'unknown').
SELECT
    COALESCE(c.region, 'unknown') AS region,
    count(DISTINCT e.order_id)    AS orders,
    ROUND(SUM(e.total_amount), 2) AS revenue
FROM intermediate.int_orders_enriched e
LEFT JOIN marts.dim_customers c USING (customer_id)
WHERE e.status IN ('paid', 'shipped', 'delivered')
GROUP BY 1
ORDER BY revenue DESC;

-- 5. Data health for this morning's standup: what got quarantined yesterday?
SELECT reject_reason, count(*) AS rows, min(_source_file) AS example_file
FROM staging.rejected_orders
GROUP BY reject_reason
ORDER BY rows DESC;
