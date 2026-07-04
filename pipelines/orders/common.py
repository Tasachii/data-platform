"""Shared paths, DB connection and logging for the orders pipeline."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = Path(os.environ.get("PLATFORM_RAW_DIR", REPO_ROOT / "raw"))
WAREHOUSE_PATH = Path(os.environ.get("PLATFORM_DB", REPO_ROOT / "warehouse" / "platform.duckdb"))

SCHEMAS = ["raw", "meta", "staging", "intermediate", "marts"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    WAREHOUSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(WAREHOUSE_PATH), read_only=read_only)
    # Never depend on the host machine's timezone: this laptop is Asia/Bangkok,
    # CI is UTC. All implicit casts must behave identically on both.
    con.execute("SET timezone = 'UTC'")
    if not read_only:
        for schema in SCHEMAS:
            con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    return con
