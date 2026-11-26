"""Data loading and caching layer for uptrend dashboard."""

import logging
import os
from typing import Dict, List, Optional

import pandas as pd

from src.constants import (
    INDUSTRIES, SECTORS, SECTOR_INDUSTRIES, SP500_PRICE_COLUMN, SP500_PRICE_CSV_URL,
)
from src.db_client import DBClient
from src.indicator_calculator import calculate_indicators

logger = logging.getLogger(__name__)


def _load_data_for_worksheets(db_path: str, worksheets: Optional[List[str]]) -> Dict[str, pd.DataFrame]:
    """Shared loader: fetch raw data for given worksheets and calculate indicators."""
    if db_path is None:
        db_path = os.environ.get("DB_PATH", "data/uptrend.db")
    client = DBClient(db_path)
    raw_data = client.fetch_all_raw_data(worksheets=worksheets)
    return {name: calculate_indicators(df) for name, df in raw_data.items() if not df.empty}


def load_all_data(db_path: str = None) -> Dict[str, pd.DataFrame]:
    """Load all data from SQLite and calculate indicators."""
    return _load_data_for_worksheets(db_path, worksheets=None)


def load_sector_data(db_path: str = None) -> Dict[str, pd.DataFrame]:
    """Load only 'all' + sector data (no industries)."""
    return _load_data_for_worksheets(db_path, worksheets=["all"] + SECTORS)


def load_industry_data(db_path: str = None, sector: str = None) -> Dict[str, pd.DataFrame]:
    """Load industry data. If sector given, only its child industries."""
    if sector is not None:
        target = SECTOR_INDUSTRIES.get(sector, [])
    else:
        target = INDUSTRIES
    return _load_data_for_worksheets(db_path, worksheets=target)


# Streamlit cache wrappers — pages import these for cross-page cache sharing
try:
    import streamlit as st
    _cache = st.cache_data(ttl=3600)
except ImportError:
    _cache = lambda f: f

@_cache
def cached_load_sector_data(db_path=None):
    return load_sector_data(db_path)

@_cache
def cached_load_all_data(db_path=None):
    return load_all_data(db_path)


def load_constituents(worksheet: str, db_path: str = None) -> pd.DataFrame:
    """Load the latest stock list (constituent snapshot) of one industry."""
    if db_path is None:
        db_path = os.environ.get("DB_PATH", "data/uptrend.db")
    return DBClient(db_path).fetch_constituents(worksheet)


@_cache
def cached_load_constituents(worksheet, db_path=None):
    return load_constituents(worksheet, db_path)


def load_all_constituents(db_path: str = None) -> pd.DataFrame:
    """Load every industry's latest stock list (for the heatmap stock level)."""
    if db_path is None:
        db_path = os.environ.get("DB_PATH", "data/uptrend.db")
    return DBClient(db_path).fetch_all_constituents()


@_cache
def cached_load_all_constituents(db_path=None):
    return load_all_constituents(db_path)


_PRICE_COLUMNS = ["date", "close"]


# (connect, read) seconds: the page waits for this call, so keep it short
SP500_FETCH_TIMEOUT = (3, 5)


def load_sp500_prices(source: Optional[str] = None, timeout=SP500_FETCH_TIMEOUT) -> pd.DataFrame:
    """S&P 500 daily closes as (date, close), oldest first.

    ``source`` is a URL or a local CSV path with ``Date`` and ``S&P500_Price``
    columns (default: env SP500_PRICE_CSV, else the Market Breadth CSV). Any
    failure gives an empty frame, so the page falls back to the plain ratio chart.
    """
    if source is None:
        source = os.environ.get("SP500_PRICE_CSV", SP500_PRICE_CSV_URL)
    empty = pd.DataFrame(columns=_PRICE_COLUMNS)
    if not source:
        return empty
    try:
        if source.startswith(("http://", "https://")):
            import io
            import requests
            resp = requests.get(source, timeout=timeout)
            resp.raise_for_status()
            raw = pd.read_csv(io.StringIO(resp.text), usecols=["Date", SP500_PRICE_COLUMN])
        else:
            raw = pd.read_csv(source, usecols=["Date", SP500_PRICE_COLUMN])
    except Exception as exc:  # network, missing file or column: the panel is optional
        logger.warning("S&P 500 prices unavailable from %s: %s", source, exc)
        return empty
    df = pd.DataFrame({
        "date": pd.to_datetime(raw["Date"], errors="coerce"),
        "close": pd.to_numeric(raw[SP500_PRICE_COLUMN], errors="coerce"),
    }).dropna()
    return df.sort_values("date").reset_index(drop=True)


class _NoPrices(Exception):
    """Raised inside the cached loader so a failed fetch is not cached."""


@_cache
def _cached_sp500_prices(source):
    df = load_sp500_prices(source)
    if df.empty:
        raise _NoPrices(source)  # st.cache_data does not store exceptions
    return df


def cached_load_sp500_prices() -> pd.DataFrame:
    """Cached S&P 500 closes; a failure is retried on the next run instead of
    hiding the panel for the whole cache TTL."""
    source = os.environ.get("SP500_PRICE_CSV", SP500_PRICE_CSV_URL)
    try:
        return _cached_sp500_prices(source)
    except _NoPrices:
        return pd.DataFrame(columns=_PRICE_COLUMNS)


def load_collection_manifest() -> Optional[dict]:
    """The latest collection manifest next to DB_PATH, or None (Issue #6)."""
    from src.collection_manifest import load_manifest
    return load_manifest()


@_cache
def cached_load_manifest():
    # Cached with the data (cleared by the sidebar Refresh), so the caption and the
    # charts it describes come from the same deploy.
    return load_collection_manifest()
