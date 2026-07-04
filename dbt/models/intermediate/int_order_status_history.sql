-- SCD Type 2 over order status: every (order_id, status, updated_at) version
-- becomes a validity interval. Retroactive refunds appear as a second row;
-- exact resends collapse under DISTINCT (identical updated_at).

with versions as (

    select distinct
        order_id,
        lower(trim(status))                 as status,
        try_cast(updated_at as timestamptz) as updated_at
    from {{ source('raw', 'orders') }}
    where order_id is not null
      and try_cast(updated_at as timestamptz) is not null

)

select
    order_id,
    status,
    updated_at                      as valid_from,
    lead(updated_at) over w         as valid_to,
    lead(updated_at) over w is null as is_current
from versions
window w as (partition by order_id order by updated_at)
