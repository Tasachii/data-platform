-- Unified ad rows, typed and converted to THB. The connectors normalized
-- STRUCTURE (nested JSON, metadata headers, date formats); this model cleans
-- VALUES: comma-thousands costs, "N/A" conversions, currency conversion.
-- SELECT DISTINCT collapses Google's exact-duplicate resent rows.

with cleaned as (

    select distinct
        try_cast(report_date as date)                             as report_date,
        platform,
        campaign_id,
        ad_id,
        trim(campaign_name)                                       as campaign_name,
        try_cast(replace(spend, ',', '') as decimal(14, 2))       as spend_local,
        upper(trim(currency))                                     as currency,
        try_cast(impressions as bigint)                           as impressions,
        try_cast(clicks as bigint)                                as clicks,
        try_cast(conversions as bigint)                           as conversions,
        -- "N/A" fails the cast while the raw value exists: flag, don't drop —
        -- the spend on that row is still real money.
        (try_cast(conversions as bigint) is null and conversions is not null)
                                                                  as conversions_missing
    from {{ source('raw', 'ad_performance') }}
    where campaign_name is not null

)

select
    c.report_date,
    c.platform,
    c.campaign_id,
    c.ad_id,
    c.campaign_name,
    c.spend_local,
    c.currency,
    case when c.currency = 'THB' then c.spend_local
         else round(c.spend_local * fx.usd_thb, 2)
    end                                                           as spend_thb,
    c.impressions,
    c.clicks,
    c.conversions,
    c.conversions_missing
from cleaned c
left join {{ ref('stg_fx_rates') }} fx
       on c.report_date = fx.fx_date
