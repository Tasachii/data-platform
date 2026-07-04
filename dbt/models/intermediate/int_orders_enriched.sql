-- Current orders enriched with customer and line aggregates.
-- business_date = the order's calendar date in Asia/Bangkok (reporting tz);
-- storage stays UTC. Orphan customer_ids map to 'unknown', never dropped.

with line_aggs as (

    select
        order_id,
        count(*)              as n_lines,
        sum(qty * unit_price) as items_amount
    from {{ ref('stg_order_items') }}
    group by order_id

)

select
    o.order_id,
    o.order_ts,
    o.updated_at,
    o.status,
    o.total_amount,
    o.channel,
    cast(timezone('Asia/Bangkok', o.order_ts) as date) as business_date,
    coalesce(c.customer_id, 'unknown')                 as customer_id,
    o.customer_id                                      as source_customer_id,
    c.region,
    coalesce(i.n_lines, 0)                             as n_lines,
    coalesce(i.items_amount, 0)                        as items_amount
from {{ ref('stg_orders') }} o
left join {{ ref('stg_customers') }} c
       on o.customer_id = c.customer_id
left join line_aggs i
       on o.order_id = i.order_id
