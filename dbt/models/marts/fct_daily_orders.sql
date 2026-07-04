-- Order-grain rollup: one order has exactly one date and one channel,
-- so these counts ARE additive at this grain.

select
    business_date,
    channel,
    count(*) filter (where status in ('paid', 'shipped', 'delivered')) as net_orders,
    count(*) filter (where status = 'refunded')                        as refunded_orders,
    coalesce(sum(total_amount) filter (where status in ('paid', 'shipped', 'delivered')), 0) as net_amount
from {{ ref('int_orders_enriched') }}
group by business_date, channel
