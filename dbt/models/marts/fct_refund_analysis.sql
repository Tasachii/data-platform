-- Refund behaviour per category: which product categories bleed money?

with order_categories as (

    select distinct
        e.order_id,
        e.status,
        p.category,
        e.total_amount
    from {{ ref('int_orders_enriched') }} e
    join {{ ref('stg_order_items') }} li on e.order_id = li.order_id
    join {{ ref('stg_products') }} p     on li.product_id = p.product_id
    where e.status in ('paid', 'shipped', 'delivered', 'refunded')

)

select
    category,
    count(*)                                                                 as paid_orders,
    count(*) filter (where status = 'refunded')                              as refunded_orders,
    round(count(*) filter (where status = 'refunded') * 100.0 / count(*), 2) as refund_rate_pct,
    coalesce(sum(total_amount) filter (where status = 'refunded'), 0)        as refunded_amount
from order_categories
group by category
