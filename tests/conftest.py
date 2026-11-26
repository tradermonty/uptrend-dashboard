"""Pytest configuration and fixtures for the uptrend dashboard tests (v2)."""

import pytest
import pandas as pd
import numpy as np

from src.constants import SECTORS, SECTOR_INDUSTRIES, VALID_WORKSHEETS as ALL_WORKSHEET_NAMES


@pytest.fixture(autouse=True)
def _no_sp500_network(monkeypatch):
    """Pages must not fetch the S&P 500 CSV in tests; tests that need it set a local path."""
    monkeypatch.setenv("SP500_PRICE_CSV", "")


@pytest.fixture
def tmp_db(tmp_path):
    """Temporary database path for testing."""
    return str(tmp_path / "test_uptrend.db")


@pytest.fixture
def db_client(tmp_db):
    """DBClient instance using a temporary database."""
    from src.db_client import DBClient

    return DBClient(tmp_db)


@pytest.fixture
def sample_raw_df():
    """Raw DataFrame with 20 rows of (date, count, total) sample data.

    Dates: 2024-01-02 to 2024-01-29 (20 business days).
    Count varies 150-250 with slope pattern: positive -> negative -> positive.
    Total fixed at 500.
    """
    dates = pd.bdate_range("2024-01-02", periods=20, freq="B")
    # Pattern: rising (150->250), then falling (250->170), then rising (170->220)
    counts = [
        150, 170, 190, 200, 210,   # rising (slope positive)
        220, 230, 240, 250, 245,   # peak area
        230, 210, 195, 180, 170,   # falling (slope negative)
        175, 185, 195, 210, 220,   # rising again (slope positive)
    ]
    return pd.DataFrame({
        "date": dates,
        "count": counts,
        "total": [500] * 20,
    })


@pytest.fixture
def sample_calculated_df(sample_raw_df):
    """DataFrame with indicator calculations applied."""
    from src.indicator_calculator import calculate_indicators

    return calculate_indicators(sample_raw_df)


@pytest.fixture
def sample_all_data(sample_raw_df):
    """Dict of worksheet name -> calculated DataFrame for all 12 categories."""
    from src.indicator_calculator import calculate_indicators

    data = {}
    base_df = calculate_indicators(sample_raw_df)
    data["all"] = base_df.copy()
    for i, sector in enumerate(SECTORS):
        df = sample_raw_df.copy()
        # Vary counts slightly per sector
        factor = 0.8 + i * 0.04
        df["count"] = (df["count"] * factor).astype(int)
        data[sector] = calculate_indicators(df)
    return data


@pytest.fixture
def sample_industry_data(sample_raw_df):
    """Dict of 3 industry worksheet names -> calculated DataFrames."""
    from src.indicator_calculator import calculate_indicators

    keys = ["ind_semiconductors", "ind_softwareapplication", "ind_banksregional"]
    data = {}
    for i, key in enumerate(keys):
        df = sample_raw_df.copy()
        factor = 0.7 + i * 0.1
        df["count"] = (df["count"] * factor).astype(int)
        data[key] = calculate_indicators(df)
    return data


@pytest.fixture
def sample_all_data_with_industries(sample_all_data, sample_industry_data):
    """sample_all_data extended with 3 industry entries."""
    return {**sample_all_data, **sample_industry_data}


@pytest.fixture
def sample_sector_only_data(sample_all_data):
    """Dict with only sec_* keys (11 sectors), no 'all'."""
    return {k: v for k, v in sample_all_data.items() if k.startswith("sec_")}
