"""Tests for industry constituent (stock list) storage and display (v5.2)."""

import re

import pandas as pd
import pytest

from src.constants import CONSTITUENT_COLUMNS
from src.data_processor import (
    TICKER_LINK_PATTERN,
    finviz_chart_url,
    prepare_constituents_table,
    style_constituent_row,
    summarize_constituents,
)



def _constituents(rows):
    """Build a constituent DataFrame from (ticker, company, cap, uptrend) tuples."""
    return pd.DataFrame(
        [
            {
                "ticker": t, "company": c, "market_cap": cap, "change": 0.01,
                "perf_week": 0.02, "perf_ytd": 0.10, "is_uptrend": up,
            }
            for t, c, cap, up in rows
        ],
        columns=CONSTITUENT_COLUMNS,
    )


# ---------------------------------------------------------------------------
# DBClient constituent storage
# ---------------------------------------------------------------------------
class TestReadPathDoesNotWrite:
    """The committed DB on main has no industry_constituents table yet.

    Page loads must not change it (schema DDL is a write) and must still work
    on a read-only DB.
    """

    def _legacy_db(self, tmp_path):
        import sqlite3
        path = tmp_path / "legacy.db"
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE uptrend_raw (date TEXT, worksheet TEXT, count INTEGER, "
                         "total INTEGER, PRIMARY KEY (date, worksheet))")
            conn.execute("CREATE INDEX idx_uptrend_raw_worksheet ON uptrend_raw (worksheet, date)")
            conn.execute("INSERT INTO uptrend_raw VALUES ('2026-11-20', 'all', 1, 2)")
        return path

    def test_reads_leave_legacy_db_byte_identical(self, tmp_path):
        from src.db_client import DBClient
        path = self._legacy_db(tmp_path)
        before = path.read_bytes()
        client = DBClient(str(path))
        assert client.fetch_constituents("ind_copper").empty
        assert client.fetch_all_constituents().empty
        assert path.read_bytes() == before

    def test_reads_work_on_read_only_legacy_db(self, tmp_path):
        import os
        from src.db_client import DBClient
        path = self._legacy_db(tmp_path)
        os.chmod(path, 0o444)
        try:
            client = DBClient(str(path))
            assert client.fetch_all_constituents().empty
        finally:
            os.chmod(path, 0o644)

    def test_first_write_creates_the_table(self, tmp_path):
        from src.db_client import DBClient
        client = DBClient(str(self._legacy_db(tmp_path)))
        client.replace_all_constituents("2026-11-20", {"ind_gold": _constituents([("NEM", "N", 2.0, False)])})
        assert client.fetch_constituents("ind_gold")["ticker"].tolist() == ["NEM"]


class TestConstituentStorage:

    def test_fetch_all_returns_every_industry_with_worksheet(self, db_client):
        db_client.replace_constituents("ind_copper", "2026-11-20", _constituents([("FCX", "F", 1.0, True)]))
        db_client.replace_constituents("ind_gold", "2026-11-20", _constituents([("NEM", "N", 2.0, False)]))
        result = db_client.fetch_all_constituents()
        assert dict(zip(result["ticker"], result["worksheet"])) == {"FCX": "ind_copper", "NEM": "ind_gold"}
        assert result["is_uptrend"].dtype == bool

    def test_replace_all_is_one_transaction(self, db_client):
        db_client.replace_constituents("ind_copper", "2026-11-19", _constituents([("OLD", "O", 1.0, False)]))
        bad = _constituents([("X", "X", 1.0, False)]).drop(columns=["company"])
        with pytest.raises(ValueError):
            db_client.replace_all_constituents("2026-11-20", {
                "ind_gold": _constituents([("NEM", "N", 2.0, False)]),
                "ind_copper": bad,
            })
        assert db_client.fetch_constituents("ind_gold").empty
        assert db_client.fetch_constituents("ind_copper")["ticker"].tolist() == ["OLD"]

    def test_replace_all_writes_every_industry(self, db_client):
        db_client.replace_all_constituents("2026-11-20", {
            "ind_gold": _constituents([("NEM", "N", 2.0, False)]),
            "ind_copper": _constituents([]),
        })
        assert db_client.fetch_constituents("ind_gold")["ticker"].tolist() == ["NEM"]
        assert db_client.fetch_constituents("ind_copper").empty

    def test_fetch_all_empty(self, db_client):
        result = db_client.fetch_all_constituents()
        assert result.empty
        assert "worksheet" in result.columns

    def test_round_trip(self, db_client):
        df = _constituents([("AAA", "Alpha", 100.0, True), ("BBB", "Beta", 50.0, False)])
        db_client.replace_constituents("ind_copper", "2026-11-20", df)
        result = db_client.fetch_constituents("ind_copper")
        assert sorted(result["ticker"]) == ["AAA", "BBB"]
        assert set(result["date"]) == {"2026-11-20"}
        flags = dict(zip(result["ticker"], result["is_uptrend"]))
        assert flags == {"AAA": True, "BBB": False}

    def test_replace_drops_previous_snapshot(self, db_client):
        db_client.replace_constituents(
            "ind_copper", "2026-11-19", _constituents([("OLD", "Old Co", 1.0, False)])
        )
        db_client.replace_constituents(
            "ind_copper", "2026-11-20", _constituents([("NEW", "New Co", 2.0, True)])
        )
        result = db_client.fetch_constituents("ind_copper")
        assert result["ticker"].tolist() == ["NEW"]

    def test_replace_does_not_touch_other_industries(self, db_client):
        db_client.replace_constituents(
            "ind_gold", "2026-11-20", _constituents([("GLD1", "Gold", 1.0, False)])
        )
        db_client.replace_constituents(
            "ind_copper", "2026-11-20", _constituents([("CU1", "Copper", 1.0, False)])
        )
        assert db_client.fetch_constituents("ind_gold")["ticker"].tolist() == ["GLD1"]

    def test_replace_with_empty_clears(self, db_client):
        db_client.replace_constituents(
            "ind_copper", "2026-11-19", _constituents([("OLD", "Old Co", 1.0, False)])
        )
        db_client.replace_constituents("ind_copper", "2026-11-20", _constituents([]))
        assert db_client.fetch_constituents("ind_copper").empty

    def test_nan_values_stored_as_null(self, db_client):
        df = _constituents([("AAA", "Alpha", float("nan"), False)])
        db_client.replace_constituents("ind_copper", "2026-11-20", df)
        assert pd.isna(db_client.fetch_constituents("ind_copper").iloc[0]["market_cap"])

    def test_fetch_unknown_returns_empty_with_columns(self, db_client):
        result = db_client.fetch_constituents("ind_copper")
        assert result.empty
        assert set(CONSTITUENT_COLUMNS) <= set(result.columns)
        assert "date" in result.columns

    def test_rejects_non_industry_worksheet(self, db_client):
        with pytest.raises(ValueError, match="industry"):
            db_client.replace_constituents("sec_technology", "2026-11-20", _constituents([]))

    def test_rejects_invalid_date(self, db_client):
        with pytest.raises(ValueError, match="date"):
            db_client.replace_constituents("ind_copper", "2026/11/20", _constituents([]))

    def test_rejects_missing_columns(self, db_client):
        with pytest.raises(ValueError, match="missing"):
            db_client.replace_constituents(
                "ind_copper", "2026-11-20", pd.DataFrame({"ticker": ["A"]})
            )


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------
class TestPrepareConstituentsTable:

    def _stored(self):
        df = _constituents([
            ("SMALL", "Small Up", 10.0, True),
            ("BIG", "Big Down", 900.0, False),
            ("MID", "Mid Up", 500.0, True),
        ])
        df["date"] = "2026-11-20"
        return df

    def test_uptrend_first_then_market_cap_desc(self):
        table = prepare_constituents_table(self._stored())
        tickers = [re.search(TICKER_LINK_PATTERN, u).group(1) for u in table["Ticker"]]
        assert tickers == ["MID", "SMALL", "BIG"]

    def test_ticker_column_links_to_finviz_weekly_chart(self):
        table = prepare_constituents_table(self._stored())
        assert table["Ticker"].iloc[0] == "https://finviz.com/quote.ashx?t=MID&p=w"

    def test_finviz_chart_url(self):
        assert finviz_chart_url("AAPL") == "https://finviz.com/quote.ashx?t=AAPL&p=w"

    @pytest.mark.parametrize("ticker", ["AAPL", "BRK-B", "NA", "BF.B"])
    def test_link_pattern_recovers_ticker_for_display(self, ticker):
        """LinkColumn(display_text=TICKER_LINK_PATTERN) must show the bare ticker."""
        match = re.search(TICKER_LINK_PATTERN, finviz_chart_url(ticker))
        assert match.group(1) == ticker

    def test_display_columns(self):
        table = prepare_constituents_table(self._stored())
        assert list(table.columns) == [
            "Ticker", "Company", "Uptrend", "Market Cap ($M)", "Change", "Perf Week", "Perf YTD",
        ]
        assert table["Uptrend"].tolist() == [True, True, False]

    def test_empty_input(self):
        table = prepare_constituents_table(pd.DataFrame())
        assert table.empty
        assert "Ticker" in table.columns

    def test_summary_counts_and_date(self):
        summary = summarize_constituents(self._stored())
        assert summary == {"total": 3, "uptrend": 2, "as_of": "2026-11-20"}

    def test_style_highlights_uptrend_ticker_and_signs(self):
        row = pd.Series({
            "Ticker": "AAA", "Company": "A", "Uptrend": True, "Market Cap ($M)": 1.0,
            "Change": -0.01, "Perf Week": 0.02, "Perf YTD": float("nan"),
        })
        styles = dict(zip(row.index, style_constituent_row(row)))
        assert "#00cc96" in styles["Ticker"]
        assert "#ef553b" in styles["Change"]
        assert "#00cc96" in styles["Perf Week"]
        assert styles["Perf YTD"] == ""
        assert styles["Company"] == ""

    def test_style_non_uptrend_ticker_plain(self):
        row = pd.Series({"Ticker": "BBB", "Uptrend": False, "Change": 0.0})
        styles = dict(zip(row.index, style_constituent_row(row)))
        assert styles["Ticker"] == ""
        assert styles["Change"] == ""

    def test_summary_empty(self):
        assert summarize_constituents(pd.DataFrame()) == {
            "total": 0, "uptrend": 0, "as_of": None,
        }
