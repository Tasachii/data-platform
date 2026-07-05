-- Cross-platform campaign identity: "Mega Sale 6.6" (FB) = "mega_sale_6.6_TH"
-- (Google) = "MEGA SALE 66" (TikTok). The ops-maintained seed is the source
-- of truth; anything the seed doesn't know falls back to its own normalized
-- name (lowercase, alphanumerics only) so new campaigns never disappear —
-- they show up as their own canonical until ops maps them.

with observed as (

    select distinct platform, campaign_name
    from {{ ref('stg_ad_performance') }}

    union

    select distinct platform, utm_campaign as campaign_name
    from {{ ref('stg_utm_touches') }}
    where utm_campaign is not null and platform is not null and platform != 'organic'

)

select
    o.platform,
    o.campaign_name,
    coalesce(
        m.canonical,
        regexp_replace(lower(o.campaign_name), '[^a-z0-9]', '', 'g')
    )                              as canonical,
    (m.canonical is null)          as is_unmapped
from observed o
left join {{ ref('campaign_canonical_mapping') }} m
       on o.platform = m.platform
      and o.campaign_name = m.campaign_name
