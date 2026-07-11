-- Refund behaviour per category: which product categories bleed money?
--
-- Counts are distinct orders participating in a category. Money is allocated
-- at order-line grain so an order spanning three categories contributes only
-- each category's own refunded lines, never its full order total three times.

with category_lines as (

    select
        e.order_id,
        e.status,
        p.category,
        li.qty * li.unit_price as line_amount
    from {{ ref('int_orders_enriched') }} e
    join {{ ref('stg_order_items') }} li on e.order_id = li.order_id
    join {{ ref('stg_products') }} p     on li.product_id = p.product_id
    where e.status in ('paid', 'shipped', 'delivered', 'refunded')

)

select
    category,
    count(distinct order_id)                                                                 as paid_orders,
    count(distinct order_id) filter (where status = 'refunded')                              as refunded_orders,
    round(count(distinct order_id) filter (where status = 'refunded') * 100.0
          / count(distinct order_id), 2)                                                      as refund_rate_pct,
    coalesce(sum(line_amount) filter (where status = 'refunded'), 0)                          as refunded_amount
from category_lines
group by category
