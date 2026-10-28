"""Loads config.toml and exposes project paths."""
from __future__ import annotations

import tomllib
from datetime import date
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB_PATH = DATA / "cabi.duckdb"
EXTRACTS = DATA / "sap_extracts"
CACHE_PATH = DATA / "llm_cache.json"
AUDIT_LOG = DATA / "audit.log"
FRONTEND = ROOT / "frontend"


@lru_cache
def settings() -> dict:
    with open(ROOT / "config.toml", "rb") as f:
        cfg = tomllib.load(f)
    cfg["demo"]["today_date"] = date.fromisoformat(cfg["demo"]["today"])
    return cfg


def today() -> date:
    return settings()["demo"]["today_date"]
