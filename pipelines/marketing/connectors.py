"""One connector per ad platform. Each parses its platform's export format —
nested JSON, metadata-prefixed CSV, odd date formats — into one STRUCTURAL
schema at ad/campaign grain:

    report_date (ISO str) · platform · campaign_id · ad_id · campaign_name
    · spend (string, as exported) · currency · impressions · clicks · conversions

Connectors normalize STRUCTURE only. Value cleaning — comma-thousands, "N/A"
conversions, currency conversion, type casts — happens in dbt staging, where
bad values can be quarantined with a reason instead of dying in a parser.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

UNIFIED_COLUMNS = [
    "report_date", "platform", "campaign_id", "ad_id", "campaign_name",
    "spend", "currency", "impressions", "clicks", "conversions",
]


class FacebookConnector:
    """facebook_ads_YYYY-MM-DD.json — nested campaign→adset→ad, USD,
    reported by America/Los_Angeles calendar day. Flattens to ad grain so
    broken ad rows (spend > 0, impressions = 0) stay individually visible."""

    platform = "facebook"
    file_pattern = "facebook_ads_{date}.json"

    def parse(self, path: Path) -> pd.DataFrame:
        payload = json.loads(path.read_text())
        rows = []
        for campaign in payload["campaigns"]:
            for adset in campaign["adsets"]:
                for ad in adset["ads"]:
                    rows.append({
                        "report_date": payload["date_start"],
                        "platform": self.platform,
                        "campaign_id": campaign["campaign_id"],
                        "ad_id": ad["ad_id"],
                        "campaign_name": campaign["campaign_name"],
                        "spend": str(ad["spend"]),
                        "currency": "USD",
                        "impressions": str(ad["impressions"]),
                        "clicks": str(ad["clicks"]),
                        "conversions": str(ad["conversions"]),
                    })
        return pd.DataFrame(rows, columns=UNIFIED_COLUMNS)


class GoogleConnector:
    """google_ads_YYYY-MM-DD.csv — two quoted metadata lines before the real
    header, THB costs with comma thousands, dates as DD/MM/YYYY, and no
    campaign_id at all (this export identifies campaigns by name only)."""

    platform = "google"
    file_pattern = "google_ads_{date}.csv"

    def parse(self, path: Path) -> pd.DataFrame:
        lines = path.read_text().splitlines()
        body = "\n".join(lines[2:])  # drop "Report: ..." and "Date range: ..."
        rows = []
        for rec in csv.DictReader(io.StringIO(body)):
            rows.append({
                "report_date": datetime.strptime(rec["Day"], "%d/%m/%Y").date().isoformat(),
                "platform": self.platform,
                "campaign_id": None,
                "ad_id": None,
                "campaign_name": rec["Campaign"],
                "spend": rec["Cost"],
                "currency": "THB",
                "impressions": rec["Impr."],
                "clicks": rec["Clicks"],
                "conversions": rec["Conv."],
            })
        return pd.DataFrame(rows, columns=UNIFIED_COLUMNS)


class TiktokConnector:
    """tiktok_ads_YYYY-MM-DD.csv — cost in USD, stat_date as YYYYMMDD."""

    platform = "tiktok"
    file_pattern = "tiktok_ads_{date}.csv"

    def parse(self, path: Path) -> pd.DataFrame:
        rows = []
        for rec in csv.DictReader(io.StringIO(path.read_text())):
            rows.append({
                "report_date": datetime.strptime(rec["stat_date"], "%Y%m%d").date().isoformat(),
                "platform": self.platform,
                "campaign_id": rec["campaign_id"],
                "ad_id": None,
                "campaign_name": rec["campaign_name"],
                "spend": rec["cost_usd"],
                "currency": "USD",
                "impressions": rec["impressions"],
                "clicks": rec["clicks"],
                "conversions": rec["conversions"],
            })
        return pd.DataFrame(rows, columns=UNIFIED_COLUMNS)


CONNECTORS = [FacebookConnector(), GoogleConnector(), TiktokConnector()]
