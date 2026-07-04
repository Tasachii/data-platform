-- Quarantine, not a bin: every reject keeps its raw values and a reason so
-- the source team can be pointed at the exact broken rows.

select
    order_id,
    customer_id,
    order_ts_raw,
    total_amount_raw,
    status,
    channel,
    _source_file,
    case
        when order_id is null                        then 'missing_order_id'
        when order_ts is null or updated_at is null  then 'unparseable_timestamp'
        when total_amount is null                    then 'amount_null_or_invalid'
        when total_amount < 0                        then 'amount_negative'
    end as reject_reason
from {{ ref('stg_orders_base') }}
where order_id is null
   or order_ts is null
   or updated_at is null
   or total_amount is null
   or total_amount < 0
