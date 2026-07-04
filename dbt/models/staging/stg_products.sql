select
    product_id,
    name,
    category,
    try_cast(cost as decimal(12, 2)) as cost
from {{ source('raw', 'products') }}
where product_id is not null
