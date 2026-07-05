-- One row per order: which ad platform (if any) the order came from.
-- Dirty utm_source variants (fb / FB_ads / adwords / tt / ...) normalize via
-- the ops-maintained seed. NULL utm = organic — kept, never dropped. A
-- non-null utm that the seed doesn't know stays platform NULL so the
-- unmapped-sources check can surface it instead of it vanishing silently.

select distinct
    t.order_id,
    t.utm_source,
    t.utm_campaign,
    case
        when t.utm_source is null or trim(t.utm_source) = '' then 'organic'
        else m.platform
    end as platform
from {{ source('raw', 'utm_touches') }} t
left join {{ ref('utm_source_mapping') }} m
       on trim(t.utm_source) = m.utm_source_variant
where t.order_id is not null
