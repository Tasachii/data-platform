"""Unit tests: each ad-platform connector parses its format quirks into the
unified structural schema, on tiny fixture files — no warehouse needed.
"""

from __future__ import annotations

import json

from pipelines.marketing.connectors import (
    UNIFIED_COLUMNS,
    FacebookConnector,
    GoogleConnector,
    TiktokConnector,
)

FB_PAYLOAD = {
    "account": "act_1",
    "date_start": "2026-06-05",
    "timezone": "America/Los_Angeles",
    "campaigns": [{
        "campaign_id": "238510001",
        "campaign_name": "Mega Sale 6.6",
        "adsets": [{
            "adset_id": "as1", "adset_name": "broad",
            "ads": [
                {"ad_id": "ad1", "spend": 10.5, "impressions": 1000, "clicks": 50, "conversions": 2},
                {"ad_id": "ad2", "spend": 3.25, "impressions": 0, "clicks": 0, "conversions": 0},
            ],
        }],
    }],
}

GOOGLE_CSV = (
    '"Report: Campaign performance"\n'
    '"Date range: 05/06/2026 - 05/06/2026"\n'
    "Campaign,Cost,Impr.,Clicks,Conv.,Day\n"
    'mega_sale_6.6_TH,"12,450.00",645048,17918,N/A,05/06/2026\n'
)

TIKTOK_CSV = (
    "campaign_id,campaign_name,cost_usd,impressions,clicks,conversions,stat_date\n"
    "170490001,MEGA SALE 66,2999.01,388310,13390,515,20260605\n"
)


def test_facebook_flattens_nested_json_to_ad_grain(tmp_path):
    path = tmp_path / "facebook_ads_2026-06-05.json"
    path.write_text(json.dumps(FB_PAYLOAD))
    frame = FacebookConnector().parse(path)

    assert list(frame.columns) == UNIFIED_COLUMNS
    assert len(frame) == 2, "one row per ad, not per campaign"
    assert set(frame["campaign_name"]) == {"Mega Sale 6.6"}
    assert frame["currency"].unique().tolist() == ["USD"]
    # the classic broken row survives parsing intact for staging to flag
    broken = frame[frame["ad_id"] == "ad2"].iloc[0]
    assert broken["spend"] == "3.25" and broken["impressions"] == "0"


def test_google_skips_metadata_and_normalizes_dates(tmp_path):
    path = tmp_path / "google_ads_2026-06-05.csv"
    path.write_text(GOOGLE_CSV)
    frame = GoogleConnector().parse(path)

    assert list(frame.columns) == UNIFIED_COLUMNS
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["report_date"] == "2026-06-05", "DD/MM/YYYY must become ISO"
    assert row["spend"] == "12,450.00", "comma-thousands cleaned in staging, not here"
    assert row["conversions"] == "N/A", "'N/A' quarantine decision belongs to staging"
    assert row["campaign_id"] is None, "this Google export has no campaign ids"


def test_tiktok_parses_compact_dates(tmp_path):
    path = tmp_path / "tiktok_ads_2026-06-05.csv"
    path.write_text(TIKTOK_CSV)
    frame = TiktokConnector().parse(path)

    assert list(frame.columns) == UNIFIED_COLUMNS
    row = frame.iloc[0]
    assert row["report_date"] == "2026-06-05", "YYYYMMDD must become ISO"
    assert row["currency"] == "USD"
    assert row["campaign_id"] == "170490001"
