from __future__ import annotations

from datetime import date

import duckdb
import pytest

from pipelines.marketing import ingest as marketing_ingest
from pipelines.orders import ingest as orders_ingest


def make_con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("CREATE SCHEMA raw")
    con.execute("CREATE SCHEMA meta")
    orders_ingest._ensure_tables(con)
    for ddl in marketing_ingest.DDL.values():
        con.execute(ddl)
    return con


@pytest.mark.parametrize(
    ("table", "header", "row"),
    [
        (
            "orders",
            "order_id,customer_id,order_ts,updated_at,status,total_amount,channel",
            "O1,C1,2026-07-11,2026-07-11,paid,100.00,web",
        ),
        (
            "utm_touches",
            "order_id,utm_source,utm_campaign",
            "O1,google,summer",
        ),
    ],
)
def test_daily_replace_preserves_partition_on_bad_schema(tmp_path, table, header, row):
    con = make_con()
    path = tmp_path / f"{table}_2026-07-11.csv"
    path.write_text(f"{header}\n{row}\n")
    orders_ingest.load_daily_file(con, path, table, date(2026, 7, 11))

    path.write_text("wrong,columns\nx,y\n")
    with pytest.raises(ValueError, match="schema mismatch"):
        orders_ingest.load_daily_file(con, path, table, date(2026, 7, 11))

    assert con.execute(
        f"SELECT count(*) FROM raw.{table} WHERE _source_file = ?", [path.name]
    ).fetchone()[0] == 1
    assert con.execute(
        "SELECT row_count FROM meta.ingest_log WHERE file_name = ?", [path.name]
    ).fetchone()[0] == 1


def test_daily_replace_rolls_back_insert_when_ingest_log_fails(tmp_path, monkeypatch):
    con = make_con()
    path = tmp_path / "orders_2026-07-11.csv"
    path.write_text(
        "order_id,customer_id,order_ts,updated_at,status,total_amount,channel\n"
        "OLD,C1,2026-07-11,2026-07-11,paid,100.00,web\n"
    )
    orders_ingest.load_daily_file(con, path, "orders", date(2026, 7, 11))
    path.write_text(
        "order_id,customer_id,order_ts,updated_at,status,total_amount,channel\n"
        "NEW,C2,2026-07-11,2026-07-11,paid,200.00,app\n"
    )
    monkeypatch.setattr(orders_ingest, "_log_load", lambda *args: (_ for _ in ()).throw(RuntimeError("log failed")))

    with pytest.raises(RuntimeError, match="log failed"):
        orders_ingest.load_daily_file(con, path, "orders", date(2026, 7, 11))

    assert con.execute(
        "SELECT order_id FROM raw.orders WHERE _source_file = ?", [path.name]
    ).fetchall() == [("OLD",)]


def test_ad_replace_rolls_back_when_ingest_log_fails(tmp_path, monkeypatch):
    con = make_con()
    path = tmp_path / "tiktok_ads_2026-07-11.csv"
    header = "stat_date,campaign_id,campaign_name,cost_usd,impressions,clicks,conversions"
    path.write_text(f"{header}\n20260711,C1,old,10,100,5,1\n")
    marketing_ingest.load_ad_file(con, path, date(2026, 7, 11))
    path.write_text(f"{header}\n20260711,C2,new,20,200,10,2\n")
    monkeypatch.setattr(
        marketing_ingest,
        "_log_load",
        lambda *args: (_ for _ in ()).throw(RuntimeError("log failed")),
    )

    with pytest.raises(RuntimeError, match="log failed"):
        marketing_ingest.load_ad_file(con, path, date(2026, 7, 11))

    assert con.execute(
        "SELECT campaign_id FROM raw.ad_performance WHERE _source_file = ?", [path.name]
    ).fetchall() == [("C1",)]
