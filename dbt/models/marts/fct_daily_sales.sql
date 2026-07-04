-- Daily revenue by channel and category, built at order-line grain.
--
-- Money ONLY at this grain: line amounts are additive across all three
-- dimensions. Order counts live in fct_daily_orders — an order whose lines
-- span 3 categories would be triple-counted here (observed ~2.2x inflation).
--
-- Refund restatement: full-refresh from current status means an order
-- refunded days later automatically moves out of NET on its ORIGINAL
-- business_date; gross/refund stay visible as separate columns.

with lines as (

    select
        e.business_date,
        e.channel,
        p.category,
        e.status,
        li.qty * li.unit_price as line_amount
    from {{ ref('int_orders_enriched') }} e
    join {{ ref('stg_order_items') }} li on e.order_id = li.order_id
    join {{ ref('stg_products') }} p     on li.product_id = p.product_id

)

select
    business_date,
    channel,
    category,
    coalesce(sum(line_amount) filter (where status in ('paid', 'shipped', 'delivered', 'refunded')), 0) as gross_amount,
    coalesce(sum(line_amount) filter (where status = 'refunded'), 0)                                    as refund_amount,
    coalesce(sum(line_amount) filter (where status in ('paid', 'shipped', 'delivered')), 0)             as net_amount
from lines
group by business_date, channel, category
