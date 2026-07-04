-- Customer dimension with an explicit 'unknown' member so facts keep
-- referential integrity even for orphan customer_ids.

select
    customer_id,
    email,
    email_is_valid,
    signup_date,
    region
from {{ ref('stg_customers') }}

union all

select
    'unknown', null, false, null, null
