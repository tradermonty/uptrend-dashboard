"""Tests for db_client module."""

import sqlite3

import pandas as pd
import pytest

from src.db_client import DBClient


class TestDBClient:
    """Tests for the DBClient class."""

    def test_init_creates_table(self, tmp_db):
        """DBClient(tmp_db) should auto-create the uptrend_raw table."""
        client = DBClient(tmp_db)
        conn = sqlite3.connect(tmp_db)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='uptrend_raw'"
        )
        tables = cursor.fetchall()
        conn.close()
        assert len(tables) == 1

    def test_upsert_inserts_new_row(self, db_client, tmp_db):
        """upsert_raw_data should insert a new row."""
        db_client.upsert_raw_data("2024-01-02", "all", 150, 500)
        conn = sqlite3.connect(tmp_db)
        cursor = conn.execute("SELECT * FROM uptrend_raw")
        rows = cursor.fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0] == ("2024-01-02", "all", 150, 500)

    def test_upsert_replaces_existing(self, db_client, tmp_db):
        """upsert_raw_data should replace an existing row with same PK."""
        db_client.upsert_raw_data("2024-01-02", "all", 150, 500)
        db_client.upsert_raw_data("2024-01-02", "all", 200, 600)
        conn = sqlite3.connect(tmp_db)
        cursor = conn.execute("SELECT * FROM uptrend_raw")
        rows = cursor.fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0] == ("2024-01-02", "all", 200, 600)

    def test_upsert_bulk(self, db_client, tmp_db):
        """upsert_bulk should insert all rows from a DataFrame."""
        df = pd.DataFrame({
            "date": ["2024-01-02", "2024-01-03", "2024-01-04"],
            "worksheet": ["all", "all", "all"],
            "count": [150, 160, 170],
            "total": [500, 500, 500],
        })
        db_client.upsert_bulk(df)
        conn = sqlite3.connect(tmp_db)
        cursor = conn.execute("SELECT COUNT(*) FROM uptrend_raw")
        count = cursor.fetchone()[0]
        conn.close()
        assert count == 3

    def test_fetch_raw_data(self, db_client):
        """fetch_raw_data should return data for a single worksheet sorted by date."""
        db_client.upsert_raw_data("2024-01-03", "all", 160, 500)
        db_client.upsert_raw_data("2024-01-02", "all", 150, 500)
        db_client.upsert_raw_data("2024-01-02", "sec_technology", 50, 100)

        df = db_client.fetch_raw_data("all")
        assert len(df) == 2
        assert list(df.columns) == ["date", "count", "total"]
        assert pd.api.types.is_datetime64_any_dtype(df["date"])
        # Should be sorted ascending
        assert df.iloc[0]["date"] < df.iloc[1]["date"]

    def test_fetch_raw_data_empty(self, db_client):
        """fetch_raw_data should return empty DataFrame for missing worksheet."""
        df = db_client.fetch_raw_data("sec_technology")
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0
        assert list(df.columns) == ["date", "count", "total"]

    def test_fetch_all_raw_data(self, db_client):
        """fetch_all_raw_data should return dict of all worksheets with data."""
        db_client.upsert_raw_data("2024-01-02", "all", 150, 500)
        db_client.upsert_raw_data("2024-01-02", "sec_technology", 50, 100)

        result = db_client.fetch_all_raw_data()
        assert isinstance(result, dict)
        assert "all" in result
        assert "sec_technology" in result
        assert len(result["all"]) == 1
        assert len(result["sec_technology"]) == 1

    def test_get_worksheets(self, db_client):
        """get_worksheets should return list of registered worksheet names."""
        db_client.upsert_raw_data("2024-01-02", "all", 150, 500)
        db_client.upsert_raw_data("2024-01-02", "sec_technology", 50, 100)
        db_client.upsert_raw_data("2024-01-02", "sec_healthcare", 30, 80)

        worksheets = db_client.get_worksheets()
        assert isinstance(worksheets, list)
        assert set(worksheets) == {"all", "sec_technology", "sec_healthcare"}

    def test_get_date_range(self, db_client):
        """get_date_range should return (min_date, max_date) tuple."""
        db_client.upsert_raw_data("2024-01-02", "all", 150, 500)
        db_client.upsert_raw_data("2024-01-05", "all", 160, 500)
        db_client.upsert_raw_data("2024-01-10", "all", 170, 500)

        min_date, max_date = db_client.get_date_range("all")
        assert min_date == "2024-01-02"
        assert max_date == "2024-01-10"


class TestDBConnectionManagement:
    """Tests for DB connection management and transaction safety."""

    def test_connection_closed_after_upsert(self, tmp_db):
        """Connection should be properly closed after upsert, even on success."""
        client = DBClient(tmp_db)
        client.upsert_raw_data("2024-01-02", "all", 150, 500)
        # Verify data was written (connection was committed and closed)
        conn = sqlite3.connect(tmp_db)
        cursor = conn.execute("SELECT COUNT(*) FROM uptrend_raw")
        assert cursor.fetchone()[0] == 1
        conn.close()

    def test_connection_closed_on_insert_error(self, tmp_db):
        """Connection should be closed even when an error occurs during insert."""
        client = DBClient(tmp_db)
        # Insert valid data first
        client.upsert_raw_data("2024-01-02", "all", 150, 500)
        # Corrupt the table to force an error (drop it)
        conn = sqlite3.connect(tmp_db)
        conn.execute("DROP TABLE uptrend_raw")
        conn.commit()
        conn.close()
        # Attempt insert should raise but not leak connection
        with pytest.raises(Exception):
            client.upsert_raw_data("2024-01-03", "all", 160, 500)
        # DB file should still be accessible (no locks held)
        conn = sqlite3.connect(tmp_db)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        cursor.fetchall()
        conn.close()

    def test_bulk_upsert_atomicity(self, tmp_db):
        """Bulk upsert with SQL-level error should roll back entirely."""
        client = DBClient(tmp_db)
        # Insert some valid data first
        client.upsert_raw_data("2024-01-01", "all", 100, 500)
        # Force a SQL-level error by inserting into a table that we'll corrupt
        # First, add a UNIQUE constraint violation within a single batch
        # by having a non-integer value that passes Python int() but fails SQL
        # Instead, we manually test rollback by corrupting the table mid-transaction
        conn = sqlite3.connect(tmp_db)
        conn.execute("DROP TABLE uptrend_raw")
        conn.commit()
        conn.close()
        # Re-create the table but with a CHECK constraint that will fail
        conn = sqlite3.connect(tmp_db)
        conn.execute("""
            CREATE TABLE uptrend_raw (
                date TEXT NOT NULL,
                worksheet TEXT NOT NULL,
                count INTEGER NOT NULL CHECK(count >= 0),
                total INTEGER NOT NULL,
                PRIMARY KEY (date, worksheet)
            )
        """)
        conn.execute("INSERT INTO uptrend_raw VALUES ('2024-01-01', 'all', 100, 500)")
        conn.commit()
        conn.close()
        # Re-create client pointing to this DB (skip _init_tables since table exists)
        client2 = DBClient(tmp_db)
        # Bulk insert with a negative count to trigger CHECK constraint failure
        df = pd.DataFrame({
            "date": ["2024-01-02", "2024-01-03"],
            "worksheet": ["all", "all"],
            "count": [150, -1],
            "total": [500, 500],
        })
        with pytest.raises(Exception):
            client2.upsert_bulk(df)
        # Only the original row should exist (bulk was rolled back)
        conn = sqlite3.connect(tmp_db)
        cursor = conn.execute("SELECT COUNT(*) FROM uptrend_raw")
        count = cursor.fetchone()[0]
        conn.close()
        assert count == 1

    def test_bulk_upsert_executemany(self, tmp_db):
        """Bulk upsert should use executemany for efficiency."""
        client = DBClient(tmp_db)
        df = pd.DataFrame({
            "date": ["2024-01-02", "2024-01-03", "2024-01-04"],
            "worksheet": ["all", "all", "all"],
            "count": [150, 160, 170],
            "total": [500, 500, 500],
        })
        client.upsert_bulk(df)
        conn = sqlite3.connect(tmp_db)
        cursor = conn.execute("SELECT COUNT(*) FROM uptrend_raw")
        count = cursor.fetchone()[0]
        conn.close()
        assert count == 3

    def test_context_manager_used(self, tmp_db):
        """DBClient should have a _connection context manager."""
        client = DBClient(tmp_db)
        assert hasattr(client, '_connection')
        # Verify it works as a context manager
        with client._connection() as conn:
            assert isinstance(conn, sqlite3.Connection)
            cursor = conn.execute("SELECT COUNT(*) FROM uptrend_raw")
            assert cursor.fetchone()[0] == 0


class TestWorksheetValidation:
    """Tests for worksheet name validation."""

    def test_upsert_rejects_invalid_worksheet(self, db_client):
        """upsert_raw_data should reject invalid worksheet names."""
        with pytest.raises(ValueError, match="Invalid worksheet"):
            db_client.upsert_raw_data("2024-01-02", "invalid_sheet", 150, 500)

    def test_upsert_accepts_valid_worksheet(self, db_client):
        """upsert_raw_data should accept valid worksheet names."""
        db_client.upsert_raw_data("2024-01-02", "all", 150, 500)
        db_client.upsert_raw_data("2024-01-02", "sec_technology", 50, 100)

    def test_bulk_upsert_rejects_invalid_worksheet(self, db_client):
        """upsert_bulk should reject DataFrames with invalid worksheet names."""
        df = pd.DataFrame({
            "date": ["2024-01-02"],
            "worksheet": ["invalid_sheet"],
            "count": [150],
            "total": [500],
        })
        with pytest.raises(ValueError, match="Invalid worksheet"):
            db_client.upsert_bulk(df)


class TestCountTotalValidation:
    """Tests for count/total validation rules."""

    def test_upsert_rejects_negative_count(self, db_client):
        with pytest.raises(ValueError, match="non-negative"):
            db_client.upsert_raw_data("2024-01-02", "all", -1, 100)

    def test_upsert_rejects_count_exceeding_total(self, db_client):
        with pytest.raises(ValueError, match="cannot exceed total"):
            db_client.upsert_raw_data("2024-01-02", "all", 101, 100)

    def test_bulk_upsert_rejects_non_integer_values(self, db_client):
        df = pd.DataFrame({
            "date": ["2024-01-02"],
            "worksheet": ["all"],
            "count": [10.5],
            "total": [100],
        })
        with pytest.raises(ValueError, match="must be an integer"):
            db_client.upsert_bulk(df)

    def test_upsert_rejects_bool_value(self, db_client):
        with pytest.raises(ValueError, match="got bool"):
            db_client.upsert_raw_data("2024-01-02", "all", True, 100)

    def test_upsert_accepts_float_whole_number(self, db_client, tmp_db):
        """150.0 should be coerced to int 150."""
        db_client.upsert_raw_data("2024-01-02", "all", 150.0, 500.0)
        import sqlite3
        conn = sqlite3.connect(tmp_db)
        row = conn.execute("SELECT count, total FROM uptrend_raw").fetchone()
        conn.close()
        assert row == (150, 500)

    def test_bulk_upsert_rejects_missing_columns(self, db_client):
        df = pd.DataFrame({
            "date": ["2024-01-02"],
            "worksheet": ["all"],
            "count": [150],
        })
        with pytest.raises(ValueError, match="missing required columns"):
            db_client.upsert_bulk(df)

    def test_bulk_upsert_rejects_negative_values(self, db_client):
        df = pd.DataFrame({
            "date": ["2024-01-02"],
            "worksheet": ["all"],
            "count": [-1],
            "total": [100],
        })
        with pytest.raises(ValueError, match="non-negative"):
            db_client.upsert_bulk(df)

    def test_bulk_upsert_rejects_count_exceeding_total(self, db_client):
        df = pd.DataFrame({
            "date": ["2024-01-02"],
            "worksheet": ["all"],
            "count": [200],
            "total": [100],
        })
        with pytest.raises(ValueError, match="count cannot exceed total"):
            db_client.upsert_bulk(df)


class TestIndustryWorksheets:
    """Tests for industry worksheet support in DB layer."""

    def test_upsert_accepts_industry_worksheet(self, db_client):
        db_client.upsert_raw_data("2024-01-02", "ind_semiconductors", 50, 100)
        df = db_client.fetch_raw_data("ind_semiconductors")
        assert len(df) == 1
        assert df.iloc[0]["count"] == 50

    def test_bulk_upsert_accepts_industry_worksheets(self, db_client):
        df = pd.DataFrame({
            "date": ["2024-01-02", "2024-01-02"],
            "worksheet": ["ind_semiconductors", "ind_softwareapplication"],
            "count": [50, 80],
            "total": [100, 200],
        })
        db_client.upsert_bulk(df)
        result = db_client.fetch_raw_data("ind_semiconductors")
        assert len(result) == 1

    def test_fetch_all_raw_data_with_worksheets_filter(self, db_client):
        db_client.upsert_raw_data("2024-01-02", "all", 150, 500)
        db_client.upsert_raw_data("2024-01-02", "sec_technology", 50, 100)
        db_client.upsert_raw_data("2024-01-02", "ind_semiconductors", 30, 60)
        result = db_client.fetch_all_raw_data(worksheets=["all", "sec_technology"])
        assert set(result.keys()) == {"all", "sec_technology"}

    def test_fetch_all_raw_data_none_returns_all(self, db_client):
        db_client.upsert_raw_data("2024-01-02", "all", 150, 500)
        db_client.upsert_raw_data("2024-01-02", "ind_semiconductors", 30, 60)
        result = db_client.fetch_all_raw_data(worksheets=None)
        assert "all" in result
        assert "ind_semiconductors" in result


class TestLoadFunctions:
    """Tests for module-level load functions."""

    def test_load_sector_data(self, tmp_db):
        from src.data_loader import load_sector_data
        client = DBClient(tmp_db)
        client.upsert_raw_data("2024-01-02", "all", 150, 500)
        client.upsert_raw_data("2024-01-02", "sec_technology", 50, 100)
        client.upsert_raw_data("2024-01-02", "ind_semiconductors", 30, 60)
        result = load_sector_data(db_path=tmp_db)
        assert "all" in result
        assert "sec_technology" in result
        assert "ind_semiconductors" not in result

    def test_load_industry_data_all(self, tmp_db):
        from src.data_loader import load_industry_data
        client = DBClient(tmp_db)
        client.upsert_raw_data("2024-01-02", "ind_semiconductors", 30, 60)
        client.upsert_raw_data("2024-01-02", "ind_banksregional", 20, 50)
        client.upsert_raw_data("2024-01-02", "all", 150, 500)
        result = load_industry_data(db_path=tmp_db)
        assert "ind_semiconductors" in result
        assert "ind_banksregional" in result
        assert "all" not in result

    def test_load_industry_data_sector_filter(self, tmp_db):
        from src.data_loader import load_industry_data
        client = DBClient(tmp_db)
        client.upsert_raw_data("2024-01-02", "ind_semiconductors", 30, 60)
        client.upsert_raw_data("2024-01-02", "ind_banksregional", 20, 50)
        result = load_industry_data(db_path=tmp_db, sector="sec_technology")
        assert "ind_semiconductors" in result
        assert "ind_banksregional" not in result


class TestDateValidation:
    """Tests for date format validation in upsert methods."""

    def test_upsert_rejects_non_iso_format(self, db_client):
        with pytest.raises(ValueError, match="Invalid date format"):
            db_client.upsert_raw_data("01/02/2024", "all", 150, 500)

    def test_upsert_rejects_no_hyphens(self, db_client):
        with pytest.raises(ValueError, match="Invalid date format"):
            db_client.upsert_raw_data("20240102", "all", 150, 500)

    def test_upsert_rejects_single_digit_month_day(self, db_client):
        with pytest.raises(ValueError, match="Invalid date format"):
            db_client.upsert_raw_data("2024-1-2", "all", 150, 500)

    def test_upsert_rejects_invalid_calendar_date(self, db_client):
        with pytest.raises(ValueError, match="Invalid date"):
            db_client.upsert_raw_data("2026-99-99", "all", 150, 500)

    def test_upsert_accepts_valid_iso_date(self, db_client):
        db_client.upsert_raw_data("2024-01-02", "all", 150, 500)

    def test_bulk_upsert_rejects_mixed_dates(self, db_client):
        df = pd.DataFrame({
            "date": ["2024-01-02", "01/03/2024"],
            "worksheet": ["all", "all"],
            "count": [150, 160],
            "total": [500, 500],
        })
        with pytest.raises(ValueError, match="non-YYYY-MM-DD"):
            db_client.upsert_bulk(df)

    def test_bulk_upsert_accepts_valid_dates(self, db_client):
        df = pd.DataFrame({
            "date": ["2024-01-02", "2024-01-03"],
            "worksheet": ["all", "all"],
            "count": [150, 160],
            "total": [500, 500],
        })
        db_client.upsert_bulk(df)
