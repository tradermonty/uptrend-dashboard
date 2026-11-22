"""Tests for industry constituent (stock list) storage and display (v5.2)."""

import re
from unittest.mock import MagicMock

import pandas as pd
import pytest
import requests

from src.data_collector import (
    CONSTITUENT_COLUMNS,
    CollectorConfig,
    DataCollector,
    extract_constituents,
)
from src.data_processor import (
    TICKER_LINK_PATTERN,
    finviz_chart_url,
    prepare_constituents_table,
    style_constituent_row,
    summarize_constituents,
)


# Real Finviz export (v=151) header, verified against the live API on 2026-11-22.
FINVIZ_HEADER = (
    "No.,Ticker,Company,Industry,Market Cap,EPS Growth This Year,EPS Growth Next Year,"
    "Sales Growth Past 5 Years,Sales Growth Quarter Over Quarter,"
    "EPS Growth Quarter Over Quarter,EPS Surprise,Revenue Surprise,"
    "Performance (Week),Performance (YTD),Earnings Date,Relative Volume,Change,"
    "After-Hours Change\n"
)
TOTAL_CSV = FINVIZ_HEADER + (
    "1,ERO,Ero Copper Corp,Copper,2241.90,89.98%,15.60%,19.38%,96.53%,217.18%,"
    "19.83%,1.49%,-26.12%,-24.11%,11/2/2026 4:30:00 PM,3.81,-8.05%,1.91%\n"
    "2,FCX,Freeport-McMoRan Inc,Copper,65992.71,76.88%,38.08%,12.62%,8.23%,74.95%,"
    "7.95%,2.52%,-22.37%,-9.03%,10/27/2026 8:30:00 AM,2.34,-6.37%,1.98%\n"
    "3,HBM,Hudbay Minerals Inc,Copper,7190.79,126.24%,28.20%,14.84%,128.28%,-40.15%,"
    "-0.56%,5.86%,-24.28%,-18.44%,11/12/2026 8:30:00 AM,2.03,-6.31%,1.73%\n"
)
UPTREND_CSV = FINVIZ_HEADER + (
    "1,HBM,Hudbay Minerals Inc,Copper,7190.79,126.24%,28.20%,14.84%,128.28%,-40.15%,"
    "-0.56%,5.86%,-24.28%,-18.44%,11/12/2026 8:30:00 AM,2.03,-6.31%,1.73%\n"
)
EMPTY_CSV = FINVIZ_HEADER


def _df(csv_text):
    import io
    return pd.read_csv(io.StringIO(csv_text))


def _csv_response(csv_text):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = 200
    resp.content = csv_text.encode("utf-8")
    resp.raise_for_status = MagicMock()
    return resp


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
# extract_constituents
# ---------------------------------------------------------------------------
class TestExtractConstituents:

    def test_maps_columns_and_flags_uptrend(self):
        result = extract_constituents(_df(TOTAL_CSV), _df(UPTREND_CSV))
        assert list(result.columns) == CONSTITUENT_COLUMNS
        assert result["ticker"].tolist() == ["ERO", "FCX", "HBM"]
        flags = dict(zip(result["ticker"], result["is_uptrend"]))
        assert flags == {"ERO": False, "FCX": False, "HBM": True}

    def test_parses_percent_strings_to_fractions(self):
        result = extract_constituents(_df(TOTAL_CSV), _df(UPTREND_CSV))
        ero = result[result["ticker"] == "ERO"].iloc[0]
        assert ero["change"] == pytest.approx(-0.0805)
        assert ero["perf_week"] == pytest.approx(-0.2612)
        assert ero["perf_ytd"] == pytest.approx(-0.2411)
        assert ero["market_cap"] == pytest.approx(2241.90)
        assert ero["company"] == "Ero Copper Corp"

    def test_empty_total_returns_empty_frame_with_columns(self):
        result = extract_constituents(_df(EMPTY_CSV), _df(EMPTY_CSV))
        assert result.empty
        assert list(result.columns) == CONSTITUENT_COLUMNS

    def test_completely_empty_frames(self):
        """_make_request returns a bare DataFrame() on an empty CSV body."""
        result = extract_constituents(pd.DataFrame(), pd.DataFrame())
        assert result.empty
        assert list(result.columns) == CONSTITUENT_COLUMNS

    def test_missing_optional_columns_become_nan(self):
        total = pd.DataFrame({"Ticker": ["AAPL"], "Company": ["Apple"]})
        result = extract_constituents(total, pd.DataFrame())
        assert result.iloc[0]["ticker"] == "AAPL"
        assert pd.isna(result.iloc[0]["market_cap"])
        assert pd.isna(result.iloc[0]["change"])
        assert result.iloc[0]["is_uptrend"] == False  # noqa: E712

    def test_drops_null_and_duplicate_tickers(self):
        total = pd.DataFrame({"Ticker": ["AAA", None, "AAA", "BBB"]})
        result = extract_constituents(total, pd.DataFrame())
        assert result["ticker"].tolist() == ["AAA", "BBB"]

    def test_unparseable_percent_becomes_nan(self):
        total = pd.DataFrame({"Ticker": ["AAPL"], "Change": ["-"]})
        result = extract_constituents(total, pd.DataFrame())
        assert pd.isna(result.iloc[0]["change"])


# ---------------------------------------------------------------------------
# DBClient constituent storage
# ---------------------------------------------------------------------------
class TestConstituentStorage:

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
# DataCollector integration
# ---------------------------------------------------------------------------
class TestCollectorSavesConstituents:

    @pytest.fixture
    def collector(self, db_client):
        config = CollectorConfig(
            finviz_api_key="test_key", max_retries=1, retry_delay=0.0, request_interval=0.0,
        )
        collector = DataCollector(db_client=db_client, config=config)
        # Freeze "today" so the collect date 2026-11-20 counts as a current snapshot
        collector._today = lambda: "2026-11-20"
        return collector

    def _mock_get(self, collector, mocker, uptrend_csv, total_csv):
        # collect order: uptrend request first, then total request
        mocker.patch.object(
            collector._session, "get",
            side_effect=[_csv_response(uptrend_csv), _csv_response(total_csv)],
        )

    def test_industry_collect_saves_constituents(self, collector, db_client, mocker):
        self._mock_get(collector, mocker, UPTREND_CSV, TOTAL_CSV)
        count, total = collector.collect_worksheet("ind_copper", date="2026-11-20")
        assert (count, total) == (1, 3)
        result = db_client.fetch_constituents("ind_copper")
        assert sorted(result["ticker"]) == ["ERO", "FCX", "HBM"]
        assert result[result["is_uptrend"]]["ticker"].tolist() == ["HBM"]

    def test_sector_collect_does_not_save_constituents(self, collector, db_client, mocker):
        mock_replace = mocker.patch.object(db_client, "replace_constituents")
        self._mock_get(collector, mocker, UPTREND_CSV, TOTAL_CSV)
        collector.collect_worksheet("sec_basicmaterials", date="2026-11-20")
        mock_replace.assert_not_called()

    def test_dry_run_does_not_save_constituents(self, collector, db_client, mocker):
        self._mock_get(collector, mocker, UPTREND_CSV, TOTAL_CSV)
        collector.collect_worksheet("ind_copper", date="2026-11-20", dry_run=True)
        assert db_client.fetch_constituents("ind_copper").empty

    def test_industry_total_zero_clears_stale_constituents(self, collector, db_client, mocker):
        db_client.replace_constituents(
            "ind_copper", "2026-11-19", _constituents([("OLD", "Old Co", 1.0, False)])
        )
        self._mock_get(collector, mocker, EMPTY_CSV, EMPTY_CSV)
        collector.collect_worksheet("ind_copper", date="2026-11-20")
        assert db_client.fetch_constituents("ind_copper").empty

    def test_blank_response_keeps_previous_constituents(self, collector, db_client, mocker):
        """A blank body (no header) is a glitch, not 'zero stocks': keep the old list."""
        db_client.replace_constituents(
            "ind_copper", "2026-11-19", _constituents([("OLD", "Old Co", 1.0, False)])
        )
        self._mock_get(collector, mocker, "", "")
        collector.collect_worksheet("ind_copper", date="2026-11-20")
        assert db_client.fetch_constituents("ind_copper")["ticker"].tolist() == ["OLD"]

    def test_backfill_date_does_not_save_constituents(self, collector, db_client, mocker):
        """Finviz returns today's screen, so a past --date must not relabel it."""
        mock_replace = mocker.patch.object(db_client, "replace_constituents")
        self._mock_get(collector, mocker, UPTREND_CSV, TOTAL_CSV)
        collector.collect_worksheet("ind_copper", date="2020-01-02")
        mock_replace.assert_not_called()
        assert len(db_client.fetch_raw_data("ind_copper")) == 1

    def test_count_written_before_constituents(self, collector, db_client, mocker):
        mocker.patch.object(db_client, "upsert_raw_data", side_effect=ValueError("db down"))
        self._mock_get(collector, mocker, UPTREND_CSV, TOTAL_CSV)
        with pytest.raises(ValueError, match="db down"):
            collector.collect_worksheet("ind_copper", date="2026-11-20")
        assert db_client.fetch_constituents("ind_copper").empty

    def test_ticker_na_survives_csv_parsing(self, collector, db_client, mocker):
        """'NA' is a real ticker (Nano Labs); pandas would read it as NaN by default."""
        total = FINVIZ_HEADER + (
            "1,NA,Nano Labs Ltd,Copper,100.0,-,-,-,-,-,-,-,1.00%,2.00%,-,1.0,-3.00%,-\n"
        )
        self._mock_get(collector, mocker, EMPTY_CSV, total)
        collector.collect_worksheet("ind_copper", date="2026-11-20")
        row = db_client.fetch_constituents("ind_copper").iloc[0]
        assert row["ticker"] == "NA"
        assert row["change"] == pytest.approx(-0.03)

    def test_constituent_save_failure_keeps_count(self, collector, db_client, mocker):
        """Constituents are secondary data: a failure must not fail the count."""
        mocker.patch.object(
            db_client, "replace_constituents", side_effect=ValueError("boom"),
        )
        self._mock_get(collector, mocker, UPTREND_CSV, TOTAL_CSV)
        count, total = collector.collect_worksheet("ind_copper", date="2026-11-20")
        assert (count, total) == (1, 3)
        assert len(db_client.fetch_raw_data("ind_copper")) == 1


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
