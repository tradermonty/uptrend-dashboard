"""Tests for import_excel module."""

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from import_excel import import_excel
from src.constants import VALID_WORKSHEETS


@pytest.fixture
def sample_excel(tmp_path):
    """Create a sample Excel file for testing."""
    filepath = tmp_path / "test_export.xlsx"
    with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
        # "all" sheet
        df_all = pd.DataFrame({
            "Date": ["1/2/2024", "1/3/2024", "1/4/2024"],
            "Count": [150, 160, 170],
            "Total": [500, 500, 500],
            "Ratio": [0.3, 0.32, 0.34],  # extra column, should be ignored
        })
        df_all.to_excel(writer, sheet_name="all", index=False)

        # "sec_technology" sheet
        df_tech = pd.DataFrame({
            "Date": ["1/2/2024", "1/3/2024"],
            "Count": [50, 55],
            "Total": [100, 100],
        })
        df_tech.to_excel(writer, sheet_name="sec_technology", index=False)

    return str(filepath)


@pytest.fixture
def excel_with_unknown_sheet(tmp_path):
    """Create an Excel file with an unknown sheet name."""
    filepath = tmp_path / "unknown.xlsx"
    with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
        df = pd.DataFrame({
            "Date": ["1/2/2024"],
            "Count": [100],
            "Total": [500],
        })
        df.to_excel(writer, sheet_name="unknown_sheet", index=False)
        df.to_excel(writer, sheet_name="all", index=False)
    return str(filepath)


@pytest.fixture
def excel_with_empty_dates(tmp_path):
    """Create an Excel file with empty date rows."""
    filepath = tmp_path / "empty_dates.xlsx"
    with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
        df = pd.DataFrame({
            "Date": ["1/2/2024", "", "1/4/2024", None],
            "Count": [150, 0, 170, 0],
            "Total": [500, 0, 500, 0],
        })
        df.to_excel(writer, sheet_name="all", index=False)
    return str(filepath)


@pytest.fixture
def excel_with_invalid_counts(tmp_path):
    """Create an Excel file containing invalid Count/Total rows."""
    filepath = tmp_path / "invalid_counts.xlsx"
    with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
        df = pd.DataFrame({
            "Date": ["1/2/2024", "1/3/2024", "1/4/2024", "1/5/2024"],
            "Count": [150.5, -1, 600, 80],
            "Total": [500, 500, 500, 100],
        })
        df.to_excel(writer, sheet_name="all", index=False)
    return str(filepath)


class TestImportExcel:
    """Tests for import_excel function."""

    def test_import_single_sheet(self, sample_excel, tmp_db):
        """Should import a single specified sheet."""
        result = import_excel(sample_excel, db_path=tmp_db, sheets=["all"])
        assert result["all"] == 3

        conn = sqlite3.connect(tmp_db)
        cursor = conn.execute("SELECT COUNT(*) FROM uptrend_raw WHERE worksheet='all'")
        count = cursor.fetchone()[0]
        conn.close()
        assert count == 3

    def test_import_all_sheets(self, sample_excel, tmp_db):
        """Should import all valid sheets."""
        result = import_excel(sample_excel, db_path=tmp_db)
        assert "all" in result
        assert "sec_technology" in result
        assert result["all"] == 3
        assert result["sec_technology"] == 2

    def test_skip_unknown_sheet(self, excel_with_unknown_sheet, tmp_db):
        """Should skip sheets with unrecognized names."""
        result = import_excel(excel_with_unknown_sheet, db_path=tmp_db)
        assert "unknown_sheet" not in result
        assert "all" in result

    def test_skip_empty_date_rows(self, excel_with_empty_dates, tmp_db):
        """Should skip rows where Date is empty."""
        result = import_excel(excel_with_empty_dates, db_path=tmp_db)
        assert result["all"] == 2  # Only 2 valid date rows

    def test_date_format_conversion(self, sample_excel, tmp_db):
        """Dates should be stored as YYYY-MM-DD in SQLite."""
        import_excel(sample_excel, db_path=tmp_db, sheets=["all"])
        conn = sqlite3.connect(tmp_db)
        cursor = conn.execute("SELECT date FROM uptrend_raw WHERE worksheet='all' ORDER BY date")
        dates = [row[0] for row in cursor.fetchall()]
        conn.close()
        assert dates == ["2024-01-02", "2024-01-03", "2024-01-04"]

    def test_dry_run(self, sample_excel, tmp_db):
        """Dry run counts valid rows without creating the target DB."""
        result = import_excel(sample_excel, db_path=tmp_db, dry_run=True)
        assert result["all"] == 3

        assert not Path(tmp_db).exists()

    def test_invalid_count_total_rows_are_dropped(self, excel_with_invalid_counts, tmp_db):
        """Non-integer/negative/count>total rows should be excluded from import."""
        result = import_excel(excel_with_invalid_counts, db_path=tmp_db)
        assert result["all"] == 1

        conn = sqlite3.connect(tmp_db)
        cursor = conn.execute(
            "SELECT date, count, total FROM uptrend_raw WHERE worksheet='all' ORDER BY date"
        )
        rows = cursor.fetchall()
        conn.close()
        assert rows == [("2024-01-05", 80, 100)]

    def test_import_industry_sheet(self, tmp_path, tmp_db):
        """Industry worksheet names (ind_*) should be accepted."""
        filepath = tmp_path / "industry.xlsx"
        with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
            df = pd.DataFrame({
                "Date": ["1/2/2024", "1/3/2024"],
                "Count": [30, 35],
                "Total": [80, 80],
            })
            df.to_excel(writer, sheet_name="ind_semiconductors", index=False)
        result = import_excel(str(filepath), db_path=tmp_db)
        assert "ind_semiconductors" in result
        assert result["ind_semiconductors"] == 2
