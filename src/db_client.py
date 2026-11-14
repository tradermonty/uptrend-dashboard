"""SQLite data access layer for uptrend dashboard."""

import logging
import numbers
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime as _datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.constants import VALID_WORKSHEETS


logger = logging.getLogger(__name__)


class DBClient:
    """Client for reading and writing uptrend data to SQLite."""

    _DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    def __init__(self, db_path: str = "data/uptrend.db"):
        self.db_path = db_path
        self._init_tables()

    @staticmethod
    def _validate_date(date_str: str) -> None:
        """Validate date string is exactly YYYY-MM-DD and a real calendar date."""
        if not isinstance(date_str, str) or not DBClient._DATE_RE.match(date_str):
            raise ValueError(f"Invalid date format: '{date_str}'. Must be YYYY-MM-DD")
        try:
            _datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"Invalid date: '{date_str}'. Not a valid calendar date")

    @contextmanager
    def _connection(self):
        """Context manager for database connections with automatic cleanup."""
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_tables(self) -> None:
        with self._connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS uptrend_raw (
                    date      TEXT    NOT NULL,
                    worksheet TEXT    NOT NULL,
                    count     INTEGER NOT NULL CHECK (count >= 0),
                    total     INTEGER NOT NULL CHECK (total >= 0),
                    CHECK (count <= total),
                    PRIMARY KEY (date, worksheet)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_uptrend_raw_worksheet
                    ON uptrend_raw (worksheet, date)
            """)

    @staticmethod
    def _coerce_whole_number(value, field_name: str) -> int:
        """Return an exact native int suitable for a signed SQLite INTEGER."""
        if isinstance(value, (bool, np.bool_)):
            raise ValueError(f"{field_name} must be an integer, got bool")
        # NumPy durations are registered as Integral, but units are not counts.
        if isinstance(value, np.timedelta64):
            raise ValueError(f"{field_name} must be an integer, got a duration")
        if isinstance(value, numbers.Integral):
            normalized = int(value)
        elif isinstance(value, (float, np.floating)) and np.isfinite(value) and value == np.trunc(value):
            normalized = int(value)
        else:
            raise ValueError(f"{field_name} must be an integer, got {value!r}")
        if not -(2**63) <= normalized <= 2**63 - 1:
            raise ValueError(f"{field_name} is outside SQLite's signed 64-bit integer range")
        return normalized

    def _validate_counts(self, count, total) -> Tuple[int, int]:
        """Validate count/total values and return coerced ints."""
        count_i = self._coerce_whole_number(count, "count")
        total_i = self._coerce_whole_number(total, "total")
        if count_i < 0 or total_i < 0:
            raise ValueError(f"count and total must be non-negative: count={count_i}, total={total_i}")
        if count_i > total_i:
            raise ValueError(f"count cannot exceed total: count={count_i}, total={total_i}")
        return count_i, total_i

    def upsert_raw_data(self, date: str, worksheet: str, count: int, total: int) -> None:
        if worksheet not in VALID_WORKSHEETS:
            raise ValueError(f"Invalid worksheet: '{worksheet}'. Must be one of {VALID_WORKSHEETS}")
        self._validate_date(date)
        count, total = self._validate_counts(count, total)
        with self._connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO uptrend_raw (date, worksheet, count, total) VALUES (?, ?, ?, ?)",
                (date, worksheet, count, total),
            )
        logger.debug("Upserted row: date=%s, worksheet=%s", date, worksheet)

    def upsert_bulk(self, df: pd.DataFrame) -> None:
        required_columns = {"date", "worksheet", "count", "total"}
        missing = required_columns - set(df.columns)
        if missing:
            raise ValueError(f"DataFrame missing required columns: {sorted(missing)}")

        duplicate = required_columns & set(df.columns[df.columns.duplicated()])
        if duplicate:
            raise ValueError(f"DataFrame has duplicate required columns: {sorted(duplicate)}")

        invalid = set(df["worksheet"].unique()) - set(VALID_WORKSHEETS)
        if invalid:
            raise ValueError(f"Invalid worksheet(s): {invalid}. Must be one of {VALID_WORKSHEETS}")

        # Validate date format: must be exactly YYYY-MM-DD and real dates
        date_strs = df["date"].astype(str)
        bad_format = date_strs[~date_strs.str.match(r"^\d{4}-\d{2}-\d{2}$")]
        if not bad_format.empty:
            raise ValueError(f"date column contains non-YYYY-MM-DD values: {bad_format.tolist()[:5]}")
        parsed = pd.to_datetime(date_strs, format="%Y-%m-%d", errors="coerce")
        bad_dates = date_strs[parsed.isna()]
        if not bad_dates.empty:
            raise ValueError(f"date column contains invalid dates: {bad_dates.tolist()[:5]}")

        # Validate actual scalar values positionally, without pandas numeric
        # coercion or index-label lookup. This preserves large integer precision
        # and leaves all existing rows untouched if any later row is invalid.
        rows = []
        values = df[["date", "worksheet", "count", "total"]].itertuples(index=False, name=None)
        for position, (day, worksheet, count, total) in enumerate(values):
            try:
                count, total = self._validate_counts(count, total)
            except ValueError as exc:
                raise ValueError(f"Invalid count/total at row position {position}: {exc}") from None
            rows.append((str(day), str(worksheet), count, total))
        with self._connection() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO uptrend_raw (date, worksheet, count, total) VALUES (?, ?, ?, ?)",
                rows,
            )
        logger.info("Bulk upserted %d rows", len(rows))

    def fetch_raw_data(self, worksheet: str) -> pd.DataFrame:
        with self._connection() as conn:
            df = pd.read_sql_query(
                "SELECT date, count, total FROM uptrend_raw WHERE worksheet = ? ORDER BY date ASC",
                conn,
                params=(worksheet,),
            )
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
        else:
            df = pd.DataFrame(columns=["date", "count", "total"])
        return df

    def fetch_all_raw_data(self, worksheets: Optional[List[str]] = None) -> Dict[str, pd.DataFrame]:
        """Fetch raw data for specified worksheets or all available.

        Args:
            worksheets: List of worksheet keys to fetch. None fetches all.
        """
        if worksheets is None:
            target = self.get_worksheets()
        else:
            target = worksheets
        return {ws: self.fetch_raw_data(ws) for ws in target}

    def get_worksheets(self) -> List[str]:
        with self._connection() as conn:
            cursor = conn.execute("SELECT DISTINCT worksheet FROM uptrend_raw ORDER BY worksheet")
            result = [row[0] for row in cursor.fetchall()]
        return result

    def get_date_range(self, worksheet: str) -> Tuple[str, str]:
        with self._connection() as conn:
            cursor = conn.execute(
                "SELECT MIN(date), MAX(date) FROM uptrend_raw WHERE worksheet = ?",
                (worksheet,),
            )
            row = cursor.fetchone()
        return (row[0], row[1])

