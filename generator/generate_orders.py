"""Simulate a Thai e-commerce source system emitting daily order batches.

Produces CSV files under raw/ the way a real source would hand them to us:
one orders + order_items file per day, dimension snapshots, and — crucially —
deliberately dirty data. Every injected edge case is recorded in
raw/_manifest.json so the test suite can verify the pipeline catches 100%.

Edge cases injected (rates per the project spec):
- 2%   duplicate order rows (source resend, exact copy)
- 3%   retroactive status change: paid/shipped/delivered -> refunded 1-7 days later
- 1%   late-arriving: order belongs to day D, shows up in day D+1's file
- 0.5% total_amount null or negative
- 1%   orphan customer_id (never appears in customers.csv)
- 3%   invalid customer emails
- ~50% timestamps serialized as Asia/Bangkok (+07:00), rest UTC (+00:00)
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]

CATEGORIES = ["electronics", "fashion", "home", "beauty", "sports", "grocery"]
REGIONS = ["Bangkok", "Central", "North", "Northeast", "East", "South"]
CHANNELS = ["web", "shopee", "lazada"]
CHANNEL_WEIGHTS = [0.30, 0.45, 0.25]
STATUSES = ["delivered", "shipped", "paid", "pending", "cancelled"]
STATUS_WEIGHTS = [0.60, 0.15, 0.15, 0.05, 0.05]
REFUNDABLE = {"delivered", "shipped", "paid"}

DUP_RATE = 0.02
REFUND_RATE = 0.03
LATE_RATE = 0.01
BAD_AMOUNT_RATE = 0.005
ORPHAN_RATE = 0.01
BAD_EMAIL_RATE = 0.03

BAD_EMAIL_PATTERNS = ["{n}@@gmail..com", "{n}.gmail.com", "{n}@", "{n} @hotmail.com"]


def _mixed_tz_strings(ts_utc: pd.Series, rng: np.random.Generator) -> pd.Series:
    """Serialize UTC timestamps as a random mix of +00:00 and +07:00 strings.

    Bangkok has no DST, so the +07:00 offset is safe to hardcode.
    """
    # Refund rows are built via Series.to_frame().T which degrades the column
    # to object dtype after concat — coerce back before using .dt.
    ts_utc = pd.to_datetime(ts_utc, utc=True)
    as_utc = ts_utc.dt.strftime("%Y-%m-%d %H:%M:%S+00:00")
    as_bkk = ts_utc.dt.tz_convert("Asia/Bangkok").dt.strftime("%Y-%m-%d %H:%M:%S+07:00")
    use_bkk = rng.random(len(ts_utc)) < 0.5
    return pd.Series(np.where(use_bkk, as_bkk, as_utc), index=ts_utc.index)


def build_products(n: int, rng: np.random.Generator) -> pd.DataFrame:
    cats = rng.choice(CATEGORIES, size=n)
    cost = np.round(rng.uniform(50, 2000, size=n), 2)
    return pd.DataFrame(
        {
            "product_id": [f"P{i:04d}" for i in range(1, n + 1)],
            "name": [f"{c}-product-{i:04d}" for i, c in enumerate(cats, start=1)],
            "category": cats,
            "cost": cost,
        }
    )


def build_customers(
    n: int, start_day: date, rng: np.random.Generator
) -> tuple[pd.DataFrame, list[str]]:
    ids = [f"C{i:05d}" for i in range(1, n + 1)]
    emails = [f"customer{i:05d}@example.com" for i in range(1, n + 1)]

    bad_idx = rng.choice(n, size=int(n * BAD_EMAIL_RATE), replace=False)
    for i in bad_idx:
        pattern = BAD_EMAIL_PATTERNS[int(rng.integers(len(BAD_EMAIL_PATTERNS)))]
        emails[i] = pattern.format(n=f"customer{i + 1:05d}")

    signup_offsets = rng.integers(30, 720, size=n)
    return (
        pd.DataFrame(
            {
                "customer_id": ids,
                "email": emails,
                "signup_date": [str(start_day - timedelta(days=int(o))) for o in signup_offsets],
                "region": rng.choice(REGIONS, size=n),
            }
        ),
        [ids[i] for i in bad_idx],
    )


def build_day_orders(
    day: date,
    n_orders: int,
    products: pd.DataFrame,
    n_customers: int,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """One day of base orders + items. Returns (orders, items, edge_case_ids)."""
    edge: dict[str, list[str]] = {"bad_amounts": [], "orphan_customers": []}

    order_ids = [f"O-{day:%Y%m%d}-{i:06d}" for i in range(1, n_orders + 1)]
    day_start = pd.Timestamp(datetime.combine(day, datetime.min.time()), tz="UTC")
    order_ts = day_start + pd.to_timedelta(rng.integers(0, 86400, size=n_orders), unit="s")
    updated_at = order_ts + pd.to_timedelta(rng.integers(0, 7200, size=n_orders), unit="s")

    customer_ids = np.array(
        [f"C{i:05d}" for i in rng.integers(1, n_customers + 1, size=n_orders)]
    )
    orphan_idx = rng.choice(n_orders, size=max(1, int(n_orders * ORPHAN_RATE)), replace=False)
    customer_ids[orphan_idx] = [
        f"CX{int(i):05d}" for i in rng.integers(1, 99999, size=len(orphan_idx))
    ]
    edge["orphan_customers"] = [order_ids[i] for i in orphan_idx]

    # Items first; order total derives from its lines like a real OLTP system.
    n_items = rng.integers(1, 6, size=n_orders)
    line_order_idx = np.repeat(np.arange(n_orders), n_items)
    n_lines = len(line_order_idx)
    prod_idx = rng.integers(0, len(products), size=n_lines)
    qty = rng.integers(1, 4, size=n_lines)
    unit_price = np.round(
        products["cost"].to_numpy()[prod_idx] * rng.uniform(1.2, 2.5, size=n_lines), 2
    )
    items = pd.DataFrame(
        {
            "order_id": np.array(order_ids)[line_order_idx],
            "product_id": products["product_id"].to_numpy()[prod_idx],
            "qty": qty,
            "unit_price": unit_price,
        }
    )

    totals = np.zeros(n_orders)
    np.add.at(totals, line_order_idx, qty * unit_price)
    total_amount = pd.Series(np.round(totals, 2)).astype("object")

    bad_idx = rng.choice(n_orders, size=max(1, int(n_orders * BAD_AMOUNT_RATE)), replace=False)
    for i in bad_idx:
        total_amount.iloc[i] = None if rng.random() < 0.5 else -abs(float(total_amount.iloc[i]))
    edge["bad_amounts"] = [order_ids[i] for i in bad_idx]

    orders = pd.DataFrame(
        {
            "order_id": order_ids,
            "customer_id": customer_ids,
            "order_ts": order_ts,
            "updated_at": updated_at,
            "status": rng.choice(STATUSES, size=n_orders, p=STATUS_WEIGHTS),
            "total_amount": total_amount,
            "channel": rng.choice(CHANNELS, size=n_orders, p=CHANNEL_WEIGHTS),
        }
    )
    return orders, items, edge


def generate(days: int, orders_per_day: int, end_date: date, seed: int, out_dir: Path) -> dict:
    rng = np.random.default_rng(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    day_list = [end_date - timedelta(days=d) for d in range(days - 1, -1, -1)]

    products = build_products(200, rng)
    customers, bad_email_ids = build_customers(8000, day_list[0], rng)
    products.to_csv(out_dir / "products.csv", index=False)
    customers.to_csv(out_dir / "customers.csv", index=False)

    manifest: dict = {
        "seed": seed,
        "days": days,
        "orders_per_day": orders_per_day,
        "start_date": str(day_list[0]),
        "end_date": str(end_date),
        "edge_cases": {
            "duplicates": [],
            "retro_status_changes": [],
            "late_arriving": [],
            "bad_amounts": [],
            "orphan_customers": [],
            "invalid_emails": bad_email_ids,
        },
        "totals": {"orders": 0, "order_rows_emitted": 0, "items": 0},
    }
    ec = manifest["edge_cases"]

    # file_date -> list of row DataFrames destined for that file
    order_files: dict[date, list[pd.DataFrame]] = {d: [] for d in day_list}
    item_files: dict[date, list[pd.DataFrame]] = {d: [] for d in day_list}

    for day in day_list:
        orders, items, edge = build_day_orders(day, orders_per_day, products, len(customers), rng)
        ec["bad_amounts"] += edge["bad_amounts"]
        ec["orphan_customers"] += edge["orphan_customers"]
        manifest["totals"]["orders"] += len(orders)
        manifest["totals"]["items"] += len(items)

        # Late-arriving: order belongs to `day` but lands in the next day's file.
        file_assignment = np.full(len(orders), 0)  # 0 = own day, 1 = next day
        if day != end_date:
            late_idx = rng.choice(
                len(orders), size=max(1, int(len(orders) * LATE_RATE)), replace=False
            )
            file_assignment[late_idx] = 1
            ec["late_arriving"] += orders["order_id"].iloc[late_idx].tolist()

        own = orders[file_assignment == 0]
        late = orders[file_assignment == 1]
        order_files[day].append(own)
        item_files[day].append(items[items["order_id"].isin(own["order_id"])])
        if len(late):
            next_day = day + timedelta(days=1)
            order_files[next_day].append(late)
            item_files[next_day].append(items[items["order_id"].isin(late["order_id"])])

        # Retroactive refunds: emitted as a NEW row in a LATER day's file.
        refundable = orders[
            orders["status"].isin(REFUNDABLE)
            & ~orders["order_id"].isin(edge["bad_amounts"])
        ]
        n_refunds = int(len(orders) * REFUND_RATE)
        candidates = refundable.sample(
            n=min(n_refunds, len(refundable)), random_state=int(rng.integers(2**31))
        )
        for _, row in candidates.iterrows():
            arrival = day + timedelta(days=1 if row["order_id"] in set(late["order_id"]) else 0)
            refund_day = arrival + timedelta(days=int(rng.integers(1, 8)))
            if refund_day > end_date:
                continue
            update = row.copy()
            update["status"] = "refunded"
            refund_ts = pd.Timestamp(
                datetime.combine(refund_day, datetime.min.time()), tz="UTC"
            ) + pd.to_timedelta(int(rng.integers(0, 86400)), unit="s")
            # A status update must happen strictly after the version it
            # replaces — late-evening orders (+2h update lag) can otherwise
            # cross midnight past a next-day refund timestamp.
            update["updated_at"] = max(refund_ts, row["updated_at"] + pd.Timedelta(minutes=1))
            order_files[refund_day].append(update.to_frame().T)
            ec["retro_status_changes"].append(row["order_id"])

    for day in day_list:
        df = pd.concat(order_files[day], ignore_index=True)

        # Source resend: exact duplicate rows within the same file.
        dup = df.sample(
            n=max(1, int(len(df) * DUP_RATE)), random_state=int(rng.integers(2**31))
        )
        ec["duplicates"] += dup["order_id"].tolist()
        df = pd.concat([df, dup], ignore_index=True)

        df["order_ts"] = _mixed_tz_strings(df["order_ts"], rng)
        df["updated_at"] = _mixed_tz_strings(df["updated_at"], rng)
        df = df.sample(frac=1, random_state=int(rng.integers(2**31))).reset_index(drop=True)
        df.to_csv(out_dir / f"orders_{day}.csv", index=False)
        manifest["totals"]["order_rows_emitted"] += len(df)

        items_df = pd.concat(item_files[day], ignore_index=True)
        items_df.to_csv(out_dir / f"order_items_{day}.csv", index=False)

    manifest["edge_counts"] = {k: len(v) for k, v in ec.items()}
    (out_dir / "_manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--orders-per-day", type=int, default=20000)
    parser.add_argument("--end-date", type=lambda s: date.fromisoformat(s), default=date(2026, 6, 30))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "raw")
    args = parser.parse_args()

    manifest = generate(args.days, args.orders_per_day, args.end_date, args.seed, args.out_dir)
    print(f"Generated {manifest['totals']['orders']} orders "
          f"({manifest['totals']['order_rows_emitted']} rows emitted) "
          f"over {args.days} days into {args.out_dir}")
    print(json.dumps(manifest["edge_counts"], indent=2))


if __name__ == "__main__":
    main()
