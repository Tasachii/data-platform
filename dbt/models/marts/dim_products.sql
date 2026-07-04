select
    product_id,
    name,
    category,
    cost
from {{ ref('stg_products') }}
