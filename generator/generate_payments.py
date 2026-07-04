"""Simulate payment-gateway files and internal ledger entries for
reconciliation — derived from the SAME orders the orders pipeline ingests
(last 7 days, money statuses only), so the platform tells one coherent story:
these payments belong to real orders in the warehouse.

Two sources that *almost* agree:
- gateway_txns_YYYY-MM-DD.csv   (payment gateway daily settlement file, UTC)
- ledger_entries_YYYY-MM-DD.csv (internal accounting system, Asia/Bangkok)

Injected mismatches (recorded in raw/_payments_manifest.json):
- 1.5%  in gateway, missing in ledger
- 1.0%  in ledger, missing in gateway (synthetic refs)
- 2.0%  amount differs by rounding (0.01-0.05)
- 1.0%  amount differs by exactly the fee (ledger already net of fee)
- 0.5%  duplicate ledger posting (same txn, new entry_id)
- 0.3%  dirty currency strings ("thb", " THB")
- ~5%   ledger ref missing the "GW-" prefix
- natural: posted_at serialized in +07:00 while gateway stays UTC
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]

FEE_RATE = 0.029
MISSING_IN_LEDGER_RATE = 0.015
MISSING_IN_GATEWAY_RATE = 0.010
ROUNDING_RATE = 0.020
FEE_TIMING_RATE = 0.010
DUP_LEDGER_RATE = 0.005
DIRTY_CURRENCY_RATE = 0.003
NO_PREFIX_RATE = 0.05

PAYMENT_METHODS = ["card", "promptpay", "truemoney", "banktransfer"]
METHOD_WEIGHTS = [0.35, 0.40, 0.15, 0.10]
CURRENCY_VARIANTS = ["thb", " THB", "THB "]


def load_paid_orders(raw_dir: Path, start: date, end: date) -> pd.DataFrame:
    """Current version per order from the raw CSVs, money statuses only —
    the same dedup semantics the orders pipeline applies in staging."""
    con = duckdb.connect()
    con.execute("SET timezone = 'UTC'")
    return con.execute(
        f"""
        WITH parsed AS (
            SELECT
                order_id,
                TRY_CAST(order_ts AS TIMESTAMPTZ)        AS order_ts,
                TRY_CAST(updated_at AS TIMESTAMPTZ)      AS updated_at,
                lower(trim(status))                      AS status,
                TRY_CAST(total_amount AS DECIMAL(14, 2)) AS total_amount
            FROM read_csv('{raw_dir}/orders_*.csv', all_varchar = true, header = true)
        ),
        latest AS (
            SELECT * FROM parsed
            QUALIFY row_number() OVER (PARTITION BY order_id ORDER BY updated_at DESC NULLS LAST) = 1
        )
        SELECT order_id, order_ts, total_amount
        FROM latest
        WHERE status IN ('paid', 'shipped', 'delivered', 'refunded')
          AND total_amount IS NOT NULL AND total_amount > 0
          AND CAST(timezone('UTC', order_ts) AS DATE) BETWEEN DATE '{start}' AND DATE '{end}'
        ORDER BY order_ts
        """
    ).fetchdf()


def generate(raw_dir: Path, end_date: date, days: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    start = end_date - timedelta(days=days - 1)
    orders = load_paid_orders(raw_dir, start, end_date)
    n = len(orders)
    if n == 0:
        raise SystemExit("no paid orders found — run generate_orders.py first")

    ec: dict[str, list[str]] = {k: [] for k in [
        "missing_in_ledger", "missing_in_gateway", "rounding", "fee_timing",
        "duplicate_posting", "dirty_currency", "no_prefix_ref",
    ]}

    # --- gateway side -------------------------------------------------------
    amount = orders["total_amount"].astype(float).round(2).to_numpy()
    created = pd.to_datetime(orders["order_ts"], utc=True) + pd.to_timedelta(
        rng.integers(0, 1800, size=n), unit="s"
    )
    gateway = pd.DataFrame(
        {
            "txn_id": [f"T-{i:08d}" for i in range(1, n + 1)],
            "gateway_ref": "GW-" + orders["order_id"],
            "amount": amount,
            "currency": "THB",
            "fee": np.round(amount * FEE_RATE, 2),
            "status": "captured",
            "created_at": created.dt.strftime("%Y-%m-%d %H:%M:%S+00:00"),
            "merchant_id": [f"M{i:03d}" for i in rng.integers(1, 21, size=n)],
            "payment_method": rng.choice(PAYMENT_METHODS, size=n, p=METHOD_WEIGHTS),
        }
    )
    gateway_utc_date = created.dt.date

    # --- ledger side, derived from gateway ---------------------------------
    ledger = pd.DataFrame(
        {
            "external_ref": gateway["gateway_ref"].copy(),
            "amount": amount.copy(),
            "currency": "THB",
            "posted_at_utc": created + pd.to_timedelta(rng.integers(60, 3600, size=n), unit="s"),
        }
    )

    # Disjoint injection targets so every txn lands in exactly one scenario.
    idx = rng.permutation(n)
    cursor = 0

    def take(rate: float) -> np.ndarray:
        nonlocal cursor
        k = max(1, int(n * rate))
        chosen = idx[cursor:cursor + k]
        cursor += k
        return chosen

    miss_ledger = take(MISSING_IN_LEDGER_RATE)
    ec["missing_in_ledger"] = orders["order_id"].iloc[miss_ledger].tolist()

    rounding = take(ROUNDING_RATE)
    ledger.loc[rounding, "amount"] = (
        ledger.loc[rounding, "amount"]
        + rng.choice([-1, 1], size=len(rounding)) * rng.integers(1, 6, size=len(rounding)) / 100
    ).round(2)
    ec["rounding"] = orders["order_id"].iloc[rounding].tolist()

    fee_timing = take(FEE_TIMING_RATE)
    ledger.loc[fee_timing, "amount"] = (
        ledger.loc[fee_timing, "amount"] - gateway["fee"].iloc[fee_timing].to_numpy()
    ).round(2)
    ec["fee_timing"] = orders["order_id"].iloc[fee_timing].tolist()

    dirty = take(DIRTY_CURRENCY_RATE)
    ledger.loc[dirty, "currency"] = rng.choice(CURRENCY_VARIANTS, size=len(dirty))
    ec["dirty_currency"] = orders["order_id"].iloc[dirty].tolist()

    no_prefix = take(NO_PREFIX_RATE)
    ledger.loc[no_prefix, "external_ref"] = ledger.loc[no_prefix, "external_ref"].str.removeprefix("GW-")
    ec["no_prefix_ref"] = orders["order_id"].iloc[no_prefix].tolist()

    # Drop the missing-in-ledger rows AFTER other injections used stable indices.
    ledger = ledger.drop(index=miss_ledger).reset_index(drop=True)

    # Duplicate postings: same txn again under a new entry_id.
    dup_pool = ledger.sample(n=max(1, int(len(ledger) * DUP_LEDGER_RATE)),
                             random_state=int(rng.integers(2**31)))
    ec["duplicate_posting"] = dup_pool["external_ref"].str.removeprefix("GW-").tolist()
    ledger = pd.concat([ledger, dup_pool], ignore_index=True)

    # Ledger-only entries: refs the gateway has never heard of.
    # Timestamps are sampled by INDEX, not via an int64 round-trip — pandas 3
    # stores tz-aware datetimes at microsecond resolution, so astype('int64')
    # gives µs while to_datetime() assumes ns (everything lands in 1970).
    n_ghost = max(1, int(n * MISSING_IN_GATEWAY_RATE))
    ghosts = pd.DataFrame(
        {
            "external_ref": [f"GW-X-{i:07d}" for i in rng.integers(1, 9_999_999, size=n_ghost)],
            "amount": np.round(rng.uniform(100, 30000, size=n_ghost), 2),
            "currency": "THB",
            "posted_at_utc": created.iloc[rng.integers(0, n, size=n_ghost)].reset_index(drop=True),
        }
    )
    ec["missing_in_gateway"] = ghosts["external_ref"].tolist()
    ledger = pd.concat([ledger, ghosts], ignore_index=True)

    ledger = ledger.sample(frac=1, random_state=int(rng.integers(2**31))).reset_index(drop=True)
    ledger.insert(0, "entry_id", [f"L-{i:08d}" for i in range(1, len(ledger) + 1)])
    ledger["account_code"] = "1102-cash-in-transit"
    ledger["entry_type"] = "debit"
    # Internal system serializes in local time — the classic +07:00 trap.
    ledger["posted_at"] = ledger["posted_at_utc"].dt.tz_convert("Asia/Bangkok").dt.strftime(
        "%Y-%m-%d %H:%M:%S+07:00"
    )
    ledger_utc_date = ledger["posted_at_utc"].dt.date
    ledger = ledger.drop(columns=["posted_at_utc"])
    ledger = ledger[["entry_id", "external_ref", "amount", "currency", "posted_at",
                     "account_code", "entry_type"]]

    # --- write daily files --------------------------------------------------
    # Clamp file assignment into the window: a settlement that crosses the
    # final midnight still has to land in SOME file, or it silently vanishes
    # from the simulation and poisons every recall count downstream.
    day_list = [start + timedelta(days=i) for i in range(days)]
    clamp = lambda s: s.map(lambda d: min(max(d, start), end_date))  # noqa: E731
    gateway_file_day = clamp(gateway_utc_date)
    ledger_file_day = clamp(ledger_utc_date)
    for day in day_list:
        g = gateway[gateway_file_day == day]
        led = ledger[ledger_file_day == day]
        g.to_csv(raw_dir / f"gateway_txns_{day}.csv", index=False)
        led.to_csv(raw_dir / f"ledger_entries_{day}.csv", index=False)

    manifest = {
        "seed": seed,
        "start_date": str(start),
        "end_date": str(end_date),
        "fee_rate": FEE_RATE,
        "totals": {"gateway_txns": len(gateway), "ledger_entries": len(ledger)},
        "edge_cases": ec,
        "edge_counts": {k: len(v) for k, v in ec.items()},
    }
    (raw_dir / "_payments_manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--end-date", type=lambda s: date.fromisoformat(s), default=None,
                        help="default: end_date of the orders manifest")
    parser.add_argument("--seed", type=int, default=43)
    parser.add_argument("--raw-dir", type=Path, default=REPO_ROOT / "raw")
    args = parser.parse_args()

    end = args.end_date
    if end is None:
        orders_manifest = json.loads((args.raw_dir / "_manifest.json").read_text())
        end = date.fromisoformat(orders_manifest["end_date"])

    manifest = generate(args.raw_dir, end, args.days, args.seed)
    print(f"Generated {manifest['totals']['gateway_txns']} gateway txns, "
          f"{manifest['totals']['ledger_entries']} ledger entries "
          f"({manifest['start_date']} .. {manifest['end_date']})")
    print(json.dumps(manifest["edge_counts"], indent=2))


if __name__ == "__main__":
    main()
