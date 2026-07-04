-- Clean, typed, UTC-normalized current state of every order.

select
    order_id,
    customer_id,
    order_ts,
    updated_at,
    status,
    total_amount,
    channel,
    _source_file
from {{ ref('stg_orders_base') }}
where order_id is not null
  and order_ts is not null
  and updated_at is not null
  and total_amount is not null
  and total_amount >= 0
