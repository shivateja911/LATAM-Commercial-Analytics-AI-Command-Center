"""In-memory access to the generated tables (loaded once from DuckDB)."""
from __future__ import annotations

import threading
from functools import cached_property

import duckdb
import pandas as pd

from .config import DB_PATH


class Store:
    def __init__(self):
        if not DB_PATH.exists():
            from .datagen import generate
            generate()
        self._con = duckdb.connect(str(DB_PATH), read_only=True)
        self._lock = threading.Lock()
        self._tables: dict[str, pd.DataFrame] = {}

    def table(self, name: str) -> pd.DataFrame:
        if name not in self._tables:
            with self._lock:
                df = self._con.execute(f"SELECT * FROM {name}").df()
            for col in df.columns:
                if col in ("WEEK_START", "PDATU", "PSTTR", "EDATU", "VFDAT", "DATE", "MONTH", "DATBG", "week_start"):
                    df[col] = pd.to_datetime(df[col])
            self._tables[name] = df
        return self._tables[name]

    def sql(self, query: str) -> pd.DataFrame:
        with self._lock:
            return self._con.execute(query).df()

    def row_counts(self) -> dict[str, int]:
        with self._lock:
            rows = self._con.execute("SELECT table_name, estimated_size FROM duckdb_tables()").fetchall()
        return {r[0]: int(r[1]) for r in rows}

    @cached_property
    def weeks(self) -> pd.DataFrame:
        return self.table("WEEKS")


_store: Store | None = None


def store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store
