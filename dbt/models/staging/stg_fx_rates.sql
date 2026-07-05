select
    try_cast("date" as date)              as fx_date,
    try_cast(usd_thb as decimal(10, 4))   as usd_thb
from {{ source('raw', 'fx_rates') }}
