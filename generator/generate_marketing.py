"""Simulate ad-platform exports and UTM touch data for marketing attribution —
derived from the SAME orders the platform already tracks, so ROAS is computed
against real warehouse revenue, not invented numbers.

Three platforms, three deliberately incompatible formats (the point):

- facebook_ads_YYYY-MM-DD.json  — nested campaign→adset→ad, spend in USD,
                                  reported by America/Los_Angeles calendar day
- google_ads_YYYY-MM-DD.csv     — 2 metadata header lines to skip, cost in THB
                                  with comma thousands ("12,450.00"), Day as DD/MM/YYYY
- tiktok_ads_YYYY-MM-DD.csv     — cost_usd, stat_date as YYYYMMDD; the final
                                  day's file arrives LATE (held in raw/late_arrivals/)

Plus:
- utm_touches_YYYY-MM-DD.csv    — order_id ↔ dirty utm_source/utm_campaign
                                  (~25% of orders stay organic with no UTM)
- fx_rates.csv                  — daily USD→THB

Injected edge cases (recorded in raw/_marketing_manifest.json):
- duplicate rows in Google files on some days
- Facebook ads with spend > 0 but impressions = 0 (a real, common data bug)
- conversions serialized as the string "N/A" on some rows
- the same campaign spelled differently on every platform
- dirty utm_source variants (fb / FB_ads / Facebook / adwords / tt / ...)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "generator"))

from generate_payments import load_paid_orders  # noqa: E402

ORGANIC_RATE = 0.25
PLATFORM_WEIGHTS = {"facebook": 0.40, "google": 0.35, "tiktok": 0.25}
UTM_VARIANTS = {
    "facebook": ["facebook", "Facebook", "fb", "FB_ads"],
    "google": ["google", "adwords", "Google"],
    "tiktok": ["tiktok", "tt", "TikTok"],
}

# One canonical campaign, three platform spellings — cross-platform mapping
# has to survive this. None = campaign doesn't run on that platform.
CAMPAIGNS = [
    {"canonical": "mega-sale-66",      "facebook": "Mega Sale 6.6",        "google": "mega_sale_6.6_TH",      "tiktok": "MEGA SALE 66"},
    {"canonical": "payday-blast",      "facebook": "Payday Blast!",        "google": "payday_blast_search",   "tiktok": "Payday Blast"},
    {"canonical": "new-arrivals",      "facebook": "New Arrivals TH",      "google": "new-arrivals-th",       "tiktok": None},
    {"canonical": "free-shipping",     "facebook": "Free Shipping Promo",  "google": "free_shipping_promo",   "tiktok": "FREE SHIPPING promo"},
    {"canonical": "brand-awareness",   "facebook": "Brand Awareness Q2",   "google": None,                    "tiktok": "brand awareness q2"},
    {"canonical": "flash-friday",      "facebook": "Flash Friday",         "google": "flash_friday_TH",       "tiktok": "FlashFriday"},
    {"canonical": "app-install",       "facebook": None,                   "google": "app_install_upa",       "tiktok": "App Install TH"},
    {"canonical": "retargeting-cart",  "facebook": "Retargeting - Cart",   "google": "retargeting_cart",      "tiktok": None},
    {"canonical": "midyear-clearance", "facebook": "Midyear Clearance",    "google": "midyear-clearance-th",  "tiktok": "MIDYEAR clearance"},
    {"canonical": "kol-collab",        "facebook": None,                   "google": None,                    "tiktok": "KOL Collab June"},
]


def _campaign_id(platform: str, idx: int) -> str:
    prefix = {"facebook": "23851", "google": "G-", "tiktok": "17049"}[platform]
    return f"{prefix}{idx:04d}"


def build_touches(orders: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Assign each paid order an ad touch (or none — organic)."""
    n = len(orders)
    platforms = [p for p in PLATFORM_WEIGHTS]
    weights = np.array([PLATFORM_WEIGHTS[p] for p in platforms])

    is_paid_traffic = rng.random(n) >= ORGANIC_RATE
    chosen_platform = rng.choice(platforms, size=n, p=weights / weights.sum())

    campaign_names, sources = [], []
    for i in range(n):
        if not is_paid_traffic[i]:
            campaign_names.append(None)
            sources.append(None)
            continue
        platform = chosen_platform[i]
        running = [c for c in CAMPAIGNS if c[platform]]
        campaign = running[int(rng.integers(len(running)))]
        campaign_names.append(campaign[platform])
        sources.append(UTM_VARIANTS[platform][int(rng.integers(len(UTM_VARIANTS[platform])))])

    return pd.DataFrame(
        {
            "order_id": orders["order_id"],
            "order_ts": orders["order_ts"],
            "revenue": orders["total_amount"].astype(float),
            "utm_source": sources,
            "utm_campaign": campaign_names,
            "platform": np.where(is_paid_traffic, chosen_platform, None),
        }
    )


def generate(raw_dir: Path, end_date: date, days: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    start = end_date - timedelta(days=days - 1)
    orders = load_paid_orders(raw_dir, start, end_date)
    if len(orders) == 0:
        raise SystemExit("no paid orders found — run generate_orders.py first")

    touches = build_touches(orders, rng)
    touches["utc_date"] = pd.to_datetime(touches["order_ts"], utc=True).dt.date

    day_list = [start + timedelta(days=i) for i in range(days)]
    fx = pd.DataFrame(
        {"date": [str(d) for d in day_list],
         "usd_thb": np.round(rng.uniform(35.5, 37.0, size=days), 4)}
    )
    fx.to_csv(raw_dir / "fx_rates.csv", index=False)

    ec: dict = {
        "google_duplicate_rows": [],
        "fb_zero_impression_ads": [],
        "conversions_na_rows": [],
        "tiktok_late_dates": [],
        "campaign_variants": {c["canonical"]: {p: c[p] for p in ("facebook", "google", "tiktok") if c[p]}
                              for c in CAMPAIGNS},
    }
    late_dir = raw_dir / "late_arrivals"
    late_dir.mkdir(exist_ok=True)
    google_dup_days = set(str(d) for d in rng.choice(day_list, size=3, replace=False))
    totals = {"ad_rows": 0, "touches": len(touches)}

    for day in day_list:
        day_touches = touches[(touches["utc_date"] == day) & touches["platform"].notna()]
        attributed = day_touches.groupby(["platform", "utm_campaign"]).size()

        fb_campaigns, google_rows, tiktok_rows = [], [], []
        for c_idx, campaign in enumerate(CAMPAIGNS):
            for platform in ("facebook", "google", "tiktok"):
                name = campaign[platform]
                if name is None:
                    continue
                orders_today = int(attributed.get((platform, name), 0))
                conversions = max(0, int(orders_today * rng.uniform(0.8, 1.3)))
                clicks = max(conversions * int(rng.integers(15, 40)), int(rng.integers(20, 80)))
                impressions = clicks * int(rng.integers(20, 60))
                cid = _campaign_id(platform, c_idx + 1)

                if platform == "facebook":
                    spend_usd = round(clicks * rng.uniform(0.12, 0.35), 2)
                    fb_campaigns.append(_fb_campaign(cid, name, spend_usd, impressions,
                                                     clicks, conversions, rng, day, ec))
                elif platform == "google":
                    spend_thb = round(clicks * rng.uniform(4.0, 12.0), 2)
                    conv_value = "N/A" if rng.random() < 0.04 else str(conversions)
                    if conv_value == "N/A":
                        ec["conversions_na_rows"].append(f"google|{cid}|{day}")
                    google_rows.append({
                        "Campaign": name,
                        "Cost": f"{spend_thb:,.2f}",
                        "Impr.": impressions,
                        "Clicks": clicks,
                        "Conv.": conv_value,
                        "Day": day.strftime("%d/%m/%Y"),
                        "_cid": cid,
                    })
                else:
                    cost_usd = round(clicks * rng.uniform(0.08, 0.25), 2)
                    conv_value = "N/A" if rng.random() < 0.03 else str(conversions)
                    if conv_value == "N/A":
                        ec["conversions_na_rows"].append(f"tiktok|{cid}|{day}")
                    tiktok_rows.append({
                        "campaign_id": cid,
                        "campaign_name": name,
                        "cost_usd": cost_usd,
                        "impressions": impressions,
                        "clicks": clicks,
                        "conversions": conv_value,
                        "stat_date": day.strftime("%Y%m%d"),
                    })

        # Facebook: nested JSON, reported by LA calendar day.
        (raw_dir / f"facebook_ads_{day}.json").write_text(json.dumps(
            {"account": "act_100420266", "date_start": str(day),
             "timezone": "America/Los_Angeles", "campaigns": fb_campaigns}, indent=1))

        # Google: two metadata lines before the real header.
        g = pd.DataFrame(google_rows)
        if str(day) in google_dup_days and len(g) > 1:
            dup = g.sample(n=int(rng.integers(1, 3)), random_state=int(rng.integers(2**31)))
            ec["google_duplicate_rows"] += [f"{cid}|{day}" for cid in dup["_cid"]]
            g = pd.concat([g, dup], ignore_index=True)
        g = g.drop(columns=["_cid"])
        header = (f'"Report: Campaign performance"\n"Date range: '
                  f'{day.strftime("%d/%m/%Y")} - {day.strftime("%d/%m/%Y")}"\n')
        (raw_dir / f"google_ads_{day}.csv").write_text(header + g.to_csv(index=False))

        # TikTok: plain CSV; the final day's file arrives late.
        tt = pd.DataFrame(tiktok_rows)
        tt_target = late_dir if day == end_date else raw_dir
        if day == end_date:
            ec["tiktok_late_dates"].append(str(day))
        tt.to_csv(tt_target / f"tiktok_ads_{day}.csv", index=False)

        totals["ad_rows"] += len(fb_campaigns) + len(g) + len(tt)

        day_utm = touches[touches["utc_date"] == day]
        day_utm[["order_id", "utm_source", "utm_campaign"]].to_csv(
            raw_dir / f"utm_touches_{day}.csv", index=False)

    manifest = {
        "seed": seed, "start_date": str(start), "end_date": str(end_date),
        "totals": totals,
        "organic_touches": int(touches["platform"].isna().sum()),
        "edge_cases": ec,
        "edge_counts": {k: len(v) for k, v in ec.items() if isinstance(v, list)},
    }
    (raw_dir / "_marketing_manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def _fb_campaign(cid, name, spend_usd, impressions, clicks, conversions, rng, day, ec) -> dict:
    """Split campaign totals across a nested adset/ad tree; occasionally emit
    the classic broken ad row: spend recorded, zero impressions."""
    n_ads = int(rng.integers(2, 5))
    weights = rng.dirichlet(np.ones(n_ads))
    ads = []
    for i, w in enumerate(weights):
        ad = {
            "ad_id": f"{cid}-ad{i + 1}",
            "spend": round(float(spend_usd * w), 2),
            "impressions": int(impressions * w),
            "clicks": int(clicks * w),
            "conversions": int(conversions * w),
        }
        if rng.random() < 0.02 and ad["spend"] > 0:
            ad["impressions"] = 0
            ad["clicks"] = 0
            ad["conversions"] = 0
            ec["fb_zero_impression_ads"].append(f"{ad['ad_id']}|{day}")
        ads.append(ad)
    return {
        "campaign_id": cid,
        "campaign_name": name,
        "adsets": [{"adset_id": f"{cid}-as1", "adset_name": f"{name} - TH broad", "ads": ads}],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--end-date", type=lambda s: date.fromisoformat(s), default=None)
    parser.add_argument("--seed", type=int, default=44)
    parser.add_argument("--raw-dir", type=Path, default=REPO_ROOT / "raw")
    args = parser.parse_args()

    end = args.end_date
    if end is None:
        orders_manifest = json.loads((args.raw_dir / "_manifest.json").read_text())
        end = date.fromisoformat(orders_manifest["end_date"])

    manifest = generate(args.raw_dir, end, args.days, args.seed)
    print(f"Generated {manifest['totals']['ad_rows']} ad rows, "
          f"{manifest['totals']['touches']} utm touches "
          f"({manifest['start_date']} .. {manifest['end_date']}), "
          f"late TikTok file(s) in raw/late_arrivals/: {manifest['edge_cases']['tiktok_late_dates']}")
    print(json.dumps(manifest["edge_counts"], indent=2))


if __name__ == "__main__":
    main()
