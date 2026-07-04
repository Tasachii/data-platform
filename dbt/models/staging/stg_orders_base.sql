{{ config(materialized='ephemeral') }}

-- Shared parse + dedup logic for stg_orders and rejected_orders.
-- Latest version per order_id wins; resends are NOT always byte-identical
-- (same instant serialized as +07:00 vs +00:00), hence the content tie-break —
-- without it the surviving raw values flip nondeterministically between runs.

with parsed as (

    select
        order_id,
        customer_id,
        order_ts                                  as order_ts_raw,
        total_amount                              as total_amount_raw,
        try_cast(order_ts as timestamptz)         as order_ts,
        try_cast(updated_at as timestamptz)       as updated_at,
        lower(trim(status))                       as status,
        try_cast(total_amount as decimal(14, 2))  as total_amount,
        lower(trim(channel))                      as channel,
        _source_file,
        _ingested_at
    from {{ source('raw', 'orders') }}

)

select *
from parsed
qualify row_number() over (
    partition by order_id
    order by updated_at desc nulls last, _ingested_at desc, order_ts_raw desc
) = 1
