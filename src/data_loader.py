"""Data loading and caching layer for uptrend dashboard."""

import logging
import os
from typing import Dict, List, Optional

import pandas as pd

from src.constants import INDUSTRIES, SECTORS, SECTOR_INDUSTRIES
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
