"""Tests for data_loader module."""

from src.db_client import DBClient
from src.data_loader import (
    load_constituents,
    load_industry_data,
    load_sector_data,
)


class TestLoadFunctions:
    """Tests for load functions."""

    def test_load_constituents(self, tmp_path):
        import pandas as pd
        tmp_db = str(tmp_path / "test.db")
        client = DBClient(tmp_db)
        client.replace_constituents("ind_copper", "2026-11-20", pd.DataFrame([{
            "ticker": "FCX", "company": "Freeport", "market_cap": 65992.71, "change": -0.06,
            "perf_week": -0.22, "perf_ytd": -0.09, "is_uptrend": False,
        }]))
        result = load_constituents("ind_copper", db_path=tmp_db)
        assert result["ticker"].tolist() == ["FCX"]

    def test_load_constituents_empty(self, tmp_path):
        tmp_db = str(tmp_path / "test.db")
        DBClient(tmp_db)
        assert load_constituents("ind_copper", db_path=tmp_db).empty

    def test_load_sector_data(self, tmp_path):
        tmp_db = str(tmp_path / "test.db")
        client = DBClient(tmp_db)
        client.upsert_raw_data("2024-01-02", "all", 150, 500)
        client.upsert_raw_data("2024-01-02", "sec_technology", 50, 100)
        client.upsert_raw_data("2024-01-02", "ind_semiconductors", 30, 60)
        result = load_sector_data(db_path=tmp_db)
        assert "all" in result
        assert "sec_technology" in result
        assert "ind_semiconductors" not in result

    def test_load_industry_data_all(self, tmp_path):
        tmp_db = str(tmp_path / "test.db")
        client = DBClient(tmp_db)
        client.upsert_raw_data("2024-01-02", "ind_semiconductors", 30, 60)
        client.upsert_raw_data("2024-01-02", "ind_banksregional", 20, 50)
        client.upsert_raw_data("2024-01-02", "all", 150, 500)
        result = load_industry_data(db_path=tmp_db)
        assert "ind_semiconductors" in result
        assert "ind_banksregional" in result
        assert "all" not in result

    def test_load_industry_data_sector_filter(self, tmp_path):
        tmp_db = str(tmp_path / "test.db")
        client = DBClient(tmp_db)
        client.upsert_raw_data("2024-01-02", "ind_semiconductors", 30, 60)
        client.upsert_raw_data("2024-01-02", "ind_banksregional", 20, 50)
        result = load_industry_data(db_path=tmp_db, sector="sec_technology")
        assert "ind_semiconductors" in result
        assert "ind_banksregional" not in result
