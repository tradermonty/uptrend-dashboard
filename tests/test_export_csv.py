"""Tests for export_csv module."""

import os
import subprocess
import sys

import pandas as pd
import pytest

from src.db_client import DBClient
from src.data_loader import load_all_data
from src.constants import VALID_WORKSHEETS


@pytest.fixture
def populated_db(tmp_path):
    """Create a temporary DB with sample data for all 12 worksheets."""
    db_path = str(tmp_path / "test.db")
    client = DBClient(db_path)
    dates = pd.bdate_range("2024-01-02", periods=20, freq="B")
    counts = [
        150, 170, 190, 200, 210,
        220, 230, 240, 250, 245,
        230, 210, 195, 180, 170,
        175, 185, 195, 210, 220,
    ]
    for ws in VALID_WORKSHEETS:
        for date, count in zip(dates, counts):
            client.upsert_raw_data(
                date.strftime("%Y-%m-%d"), ws, count, 500,
            )
    return db_path


@pytest.fixture
def empty_db(tmp_path):
    """Create a temporary DB with no data."""
    db_path = str(tmp_path / "empty.db")
    DBClient(db_path)  # creates tables but no data
    return db_path


class TestExportCsv:
    """Tests for export_csv() function."""

    def test_creates_timeseries_file(self, populated_db, tmp_path):
        """CSV timeseries file should be created."""
        from export_csv import export_csv

        output_dir = str(tmp_path / "output")
        os.makedirs(output_dir)
        result = export_csv(populated_db, output_dir)
        assert os.path.isfile(result["timeseries"]["path"])

    def test_creates_summary_file(self, populated_db, tmp_path):
        """CSV summary file should be created."""
        from export_csv import export_csv

        output_dir = str(tmp_path / "output")
        os.makedirs(output_dir)
        result = export_csv(populated_db, output_dir)
        assert os.path.isfile(result["summary"]["path"])

    def test_timeseries_has_worksheet_column(self, populated_db, tmp_path):
        """Generated timeseries CSV should have worksheet column."""
        from export_csv import export_csv

        output_dir = str(tmp_path / "output")
        os.makedirs(output_dir)
        result = export_csv(populated_db, output_dir)
        df = pd.read_csv(result["timeseries"]["path"])
        assert "worksheet" in df.columns

    def test_summary_excludes_key_column(self, populated_db, tmp_path):
        """Generated summary CSV should not have _key column."""
        from export_csv import export_csv

        output_dir = str(tmp_path / "output")
        os.makedirs(output_dir)
        result = export_csv(populated_db, output_dir)
        df = pd.read_csv(result["summary"]["path"])
        assert "_key" not in df.columns

    def test_returns_results(self, populated_db, tmp_path):
        """Return value should have timeseries and summary with path and rows."""
        from export_csv import export_csv

        output_dir = str(tmp_path / "output")
        os.makedirs(output_dir)
        result = export_csv(populated_db, output_dir)
        assert "timeseries" in result
        assert "summary" in result
        assert "path" in result["timeseries"]
        assert "rows" in result["timeseries"]
        assert result["timeseries"]["rows"] > 0
        assert "path" in result["summary"]
        assert "rows" in result["summary"]
        assert result["summary"]["rows"] == 11

    def test_creates_industry_summary_file(self, populated_db, tmp_path):
        """CSV industry summary file should be created."""
        from export_csv import export_csv

        output_dir = str(tmp_path / "output")
        os.makedirs(output_dir)
        result = export_csv(populated_db, output_dir)
        assert "industry_summary" in result
        assert os.path.isfile(result["industry_summary"]["path"])

    def test_industry_summary_excludes_key_column(self, populated_db, tmp_path):
        """Industry summary CSV should not have _key column."""
        from export_csv import export_csv

        output_dir = str(tmp_path / "output")
        os.makedirs(output_dir)
        result = export_csv(populated_db, output_dir)
        df = pd.read_csv(result["industry_summary"]["path"])
        assert "_key" not in df.columns

    def test_empty_db(self, empty_db, tmp_path):
        """Empty DB should return empty dict."""
        from export_csv import export_csv

        output_dir = str(tmp_path / "output")
        os.makedirs(output_dir)
        result = export_csv(empty_db, output_dir)
        assert result == {}


    def test_creates_dispersion_csv(self, populated_db, tmp_path):
        """Dispersion CSV should always be created."""
        from export_csv import export_csv

        output_dir = str(tmp_path / "output")
        os.makedirs(output_dir)
        result = export_csv(populated_db, output_dir)
        assert "dispersion" in result
        assert os.path.isfile(result["dispersion"]["path"])
        df = pd.read_csv(result["dispersion"]["path"])
        expected_cols = {"date", "dispersion", "mean_ratio", "range", "regime", "level_regime",
                         "sector_count", "expected_sector_count", "coverage_complete"}
        assert expected_cols == set(df.columns)

    def test_dispersion_exposes_insufficient_sector_coverage(self, tmp_path):
        """A sparse input exports diagnostic dates, never market metrics."""
        from export_csv import export_csv

        db_path = str(tmp_path / "sparse.db")
        client = DBClient(db_path)
        dates = pd.bdate_range("2024-01-02", periods=20, freq="B")
        # Only 'all' and 1 sector
        for ws in ["all", "sec_technology"]:
            data = pd.DataFrame({
                "date": dates.strftime("%Y-%m-%d"),
                "worksheet": ws,
                "count": range(100, 120),
                "total": [500] * 20,
            })
            client.upsert_bulk(data)

        output_dir = str(tmp_path / "output")
        os.makedirs(output_dir)
        result = export_csv(db_path, output_dir)
        assert "dispersion" in result
        df = pd.read_csv(result["dispersion"]["path"])
        assert len(df) == 20
        assert df["dispersion"].isna().all()
        assert df["regime"].isna().all()
        assert not df["coverage_complete"].any()
        assert df["sector_count"].iloc[-1] == 1
        assert set(df.columns) == {"date", "dispersion", "mean_ratio", "range", "regime", "level_regime",
                         "sector_count", "expected_sector_count", "coverage_complete"}


class TestExportCsvCli:
    """Tests for export_csv CLI entry point."""

    def test_cli_db_not_found(self, tmp_path):
        """Non-existent DB should exit with code 1."""
        result = subprocess.run(
            [sys.executable, "export_csv.py", "--db", str(tmp_path / "nonexistent.db")],
            capture_output=True, text=True,
        )
        assert result.returncode == 1

    def test_cli_output_dir_not_found(self, populated_db, tmp_path):
        """Non-existent output directory should exit with code 1."""
        result = subprocess.run(
            [
                sys.executable, "export_csv.py",
                "--db", populated_db,
                "--output-dir", str(tmp_path / "nonexistent_dir"),
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
