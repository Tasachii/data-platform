-- Daily channel scoreboard: platform-reported delivery (spend, impressions,
-- clicks, conversions) side by side with warehouse-attributed revenue.
--
-- Two honest caveats, documented rather than hidden:
-- 1. Ad platforms report by their OWN calendar day (FB = America/Los_Angeles);
--    daily aggregates cannot be re-cut to UTC, so report_date joins the
--    order's Bangkok business_date as-is. Known, bounded imprecision.
-- 2. All ratios are NULLIF-guarded: a zero-spend or zero-impression day
--    yields NULL, never Infinity — a broken FB ad row (spend > 0,
--    impressions = 0) must not poison the aggregate.

with ads as (

    select
        report_date                       as activity_date,
        platform,
        sum(spend_thb)                    as spend_thb,
        sum(impressions)                  as impressions,
        sum(clicks)                       as clicks,
        sum(coalesce(conversions, 0))     as platform_conversions
    from {{ ref('stg_ad_performance') }}
    group by 1, 2

),

revenue as (

    select
        business_date                     as activity_date,
        platform,
        count(*)                          as attributed_orders,
        sum(revenue_thb)                  as attributed_revenue_thb
    from {{ ref('int_attributed_revenue') }}
    group by 1, 2

)

select
    coalesce(a.activity_date, r.activity_date)               as activity_date,
    coalesce(a.platform, r.platform)                         as platform,
    coalesce(a.spend_thb, 0)                                 as spend_thb,
    coalesce(a.impressions, 0)                               as impressions,
    coalesce(a.clicks, 0)                                    as clicks,
    coalesce(a.platform_conversions, 0)                      as platform_conversions,
    coalesce(r.attributed_orders, 0)                         as attributed_orders,
    coalesce(r.attributed_revenue_thb, 0)                    as attributed_revenue_thb,
    round(r.attributed_revenue_thb / nullif(a.spend_thb, 0), 2)   as roas,
    round(a.spend_thb / nullif(a.clicks, 0), 2)                   as cpc_thb,
    round(a.spend_thb / nullif(r.attributed_orders, 0), 2)        as cpa_thb,
    round(100.0 * a.clicks / nullif(a.impressions, 0), 2)         as ctr_pct
from ads a
full join revenue r
       on a.activity_date = r.activity_date and a.platform = r.platform
