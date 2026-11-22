"""SQLite data access layer for uptrend dashboard."""

import logging
import numbers
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime as _datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd

from src.constants import CONSTITUENT_COLUMNS, INDUSTRIES, VALID_WORKSHEETS


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
            # Latest constituent snapshot per industry (v5.2). Not historical:
            # each collect replaces the industry's rows to keep the committed DB small.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS industry_constituents (
                    worksheet  TEXT    NOT NULL,
                    ticker     TEXT    NOT NULL,
                    date       TEXT    NOT NULL,
                    company    TEXT,
                    market_cap REAL,
                    change     REAL,
                    perf_week  REAL,
                    perf_ytd   REAL,
                    is_uptrend INTEGER NOT NULL CHECK (is_uptrend IN (0, 1)),
                    PRIMARY KEY (worksheet, ticker)
                )
            """)

    def replace_constituents(self, worksheet: str, date: str, df: pd.DataFrame) -> None:
        """Atomically replace the constituent snapshot of one industry.

        An empty df clears the industry (e.g. no stocks passed the base filters).
        """
        if worksheet not in INDUSTRIES:
            raise ValueError(f"Constituents are stored for industry worksheets only: '{worksheet}'")
        self._validate_date(date)
        missing = set(CONSTITUENT_COLUMNS) - set(df.columns)
        if missing:
            raise ValueError(f"Constituent DataFrame missing columns: {sorted(missing)}")

        def _num(value):
            return None if pd.isna(value) else float(value)

        rows = [
            (
                worksheet,
                str(row["ticker"]),
                date,
                None if pd.isna(row["company"]) else str(row["company"]),
                _num(row["market_cap"]),
                _num(row["change"]),
                _num(row["perf_week"]),
                _num(row["perf_ytd"]),
                int(bool(row["is_uptrend"])),
            )
            for _, row in df.iterrows()
        ]
        with self._connection() as conn:
            conn.execute("DELETE FROM industry_constituents WHERE worksheet = ?", (worksheet,))
            conn.executemany(
                "INSERT INTO industry_constituents "
                "(worksheet, ticker, date, company, market_cap, change, perf_week, perf_ytd, is_uptrend) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        logger.debug("Replaced %d constituents for %s", len(rows), worksheet)

    def fetch_constituents(self, worksheet: str) -> pd.DataFrame:
        """Return the stored constituent snapshot of one industry (may be empty)."""
        columns = ["date"] + CONSTITUENT_COLUMNS
        with self._connection() as conn:
            df = pd.read_sql_query(
                f"SELECT {', '.join(columns)} FROM industry_constituents "
                "WHERE worksheet = ? ORDER BY ticker",
                conn,
                params=(worksheet,),
            )
        if df.empty:
            return pd.DataFrame(columns=columns)
        df["is_uptrend"] = df["is_uptrend"].astype(bool)
        return df

    @staticmethod
    def _coerce_whole_number(value, field_name: str) -> int:
        """Coerce integer-like values to int, rejecting non-integers."""
        if isinstance(value, bool):
            raise ValueError(f"{field_name} must be an integer, got bool")
        if isinstance(value, numbers.Integral):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        raise ValueError(f"{field_name} must be an integer, got {value!r}")

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

        counts = pd.to_numeric(df["count"], errors="coerce")
        totals = pd.to_numeric(df["total"], errors="coerce")

        if counts.isna().any() or totals.isna().any():
            raise ValueError("count/total contain non-numeric values")

        non_integer_mask = (counts % 1 != 0) | (totals % 1 != 0)
        if non_integer_mask.any():
            bad_rows = non_integer_mask[non_integer_mask].index.tolist()
            raise ValueError(f"count/total must be integers (bad rows: {bad_rows})")

        negative_mask = (counts < 0) | (totals < 0)
        if negative_mask.any():
            bad_rows = negative_mask[negative_mask].index.tolist()
            raise ValueError(f"count/total must be non-negative (bad rows: {bad_rows})")

        exceeds_mask = counts > totals
        if exceeds_mask.any():
            bad_rows = exceeds_mask[exceeds_mask].index.tolist()
            raise ValueError(f"count cannot exceed total (bad rows: {bad_rows})")

        rows = [
            (
                str(row["date"]),
                str(row["worksheet"]),
                int(counts.loc[idx]),
                int(totals.loc[idx]),
            )
            for idx, row in df.iterrows()
        ]
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

