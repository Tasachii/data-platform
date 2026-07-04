-- A bad email is a contactability problem, not a reason to drop the customer.

select
    customer_id,
    email,
    regexp_matches(email, '^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$') as email_is_valid,
    try_cast(signup_date as date) as signup_date,
    region
from {{ source('raw', 'customers') }}
where customer_id is not null
