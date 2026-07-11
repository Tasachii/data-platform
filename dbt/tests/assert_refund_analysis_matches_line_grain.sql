-- Regression guard for ADR-007: category money must be allocated at line grain.
-- A row returned here means either a category allocation or the mart total is wrong.

with expected as (

    select
        p.category,
        sum(li.qty * li.unit_price) as refunded_amount
    from {{ ref('int_orders_enriched') }} e
    join {{ ref('stg_order_items') }} li on e.order_id = li.order_id
    join {{ ref('stg_products') }} p     on li.product_id = p.product_id
    where e.status = 'refunded'
    group by p.category

),

actual as (

    select
        category,
        refunded_amount
    from {{ ref('fct_refund_analysis') }}

)

select
    coalesce(e.category, a.category) as category,
    e.refunded_amount               as expected_refunded_amount,
    a.refunded_amount               as actual_refunded_amount
from expected e
full outer join actual a using (category)
where e.category is null
   or a.category is null
   or abs(e.refunded_amount - a.refunded_amount) > 0.01
