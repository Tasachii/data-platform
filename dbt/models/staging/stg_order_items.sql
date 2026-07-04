select distinct
    order_id,
    product_id,
    try_cast(qty as integer)               as qty,
    try_cast(unit_price as decimal(12, 2)) as unit_price
from {{ source('raw', 'order_items') }}
where order_id is not null
  and try_cast(qty as integer) > 0
  and try_cast(unit_price as decimal(12, 2)) >= 0
