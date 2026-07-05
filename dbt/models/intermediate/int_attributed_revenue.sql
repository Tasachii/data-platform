-- Last-touch attribution: each order's revenue goes to the platform/campaign
-- of its (single) UTM touch. Organic orders keep their revenue under the
-- 'organic' bucket — dropping them would overstate paid channels' share.
-- Revenue = current net view (paid/shipped/delivered), consistent with the
-- sales marts: a refunded order stops counting toward ROAS.

select
    e.business_date,
    t.platform,
    coalesce(cm.canonical, case when t.platform = 'organic' then 'organic' end)
                          as campaign_canonical,
    e.order_id,
    e.total_amount        as revenue_thb
from {{ ref('stg_utm_touches') }} t
join {{ ref('int_orders_enriched') }} e
  on t.order_id = e.order_id
left join {{ ref('int_campaign_mapping') }} cm
       on t.platform = cm.platform
      and t.utm_campaign = cm.campaign_name
where e.status in ('paid', 'shipped', 'delivered')
