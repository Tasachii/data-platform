-- Campaign scoreboard at CANONICAL grain: the same campaign's spend on
-- Facebook, Google and TikTok rolls up under one name, which is the whole
-- point of int_campaign_mapping.

with ads as (

    select
        cm.canonical,
        count(distinct s.platform)        as n_platforms,
        sum(s.spend_thb)                  as spend_thb,
        sum(s.impressions)                as impressions,
        sum(s.clicks)                     as clicks,
        sum(coalesce(s.conversions, 0))   as platform_conversions
    from {{ ref('stg_ad_performance') }} s
    join {{ ref('int_campaign_mapping') }} cm
      on s.platform = cm.platform and s.campaign_name = cm.campaign_name
    group by 1

),

revenue as (

    select
        campaign_canonical                as canonical,
        count(*)                          as attributed_orders,
        sum(revenue_thb)                  as attributed_revenue_thb
    from {{ ref('int_attributed_revenue') }}
    where campaign_canonical is not null
    group by 1

)

select
    coalesce(a.canonical, r.canonical)                       as canonical,
    coalesce(a.n_platforms, 0)                               as n_platforms,
    coalesce(a.spend_thb, 0)                                 as spend_thb,
    coalesce(a.impressions, 0)                               as impressions,
    coalesce(a.clicks, 0)                                    as clicks,
    coalesce(a.platform_conversions, 0)                      as platform_conversions,
    coalesce(r.attributed_orders, 0)                         as attributed_orders,
    coalesce(r.attributed_revenue_thb, 0)                    as attributed_revenue_thb,
    round(r.attributed_revenue_thb / nullif(a.spend_thb, 0), 2) as roas
from ads a
full join revenue r on a.canonical = r.canonical
