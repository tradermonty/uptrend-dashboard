"""Tests for the daily constituent details collector (v5.9)."""

from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest
import requests

from src.constants import CONSTITUENT_COLUMNS, INDUSTRIES
from src.constituent_collector import (
    DETAIL_COLUMN_IDS,
    ConstituentCollector,
    build_constituent_snapshots,
    collect_constituents_safely,
    build_details_url,
    industry_key_for,
)
from src.data_collector import CollectorConfig, DataCollector
from src.finviz_universe import BASE_FILTERS, FUND_WORKSHEETS, UPTREND_FILTERS

# Header verified against the live export (c=1,2,3,4,6,42,47,66) on 2026-11-22
DETAILS_CSV = (
    '"Ticker","Company","Sector","Industry","Market Cap","Performance (Week)",'
    '"Performance (YTD)","Change"\n'
    '"CAAP","Corporacion America Airports SA","Industrials","Airports & Air Services",'
    '"3611.14","-11.44%","-14.88%","-2.64%"\n'
    '"OMAB","Grupo Aeroportuario del Centro Norte","Industrials","Airports & Air Services",'
    '"4268.50","-7.19%","-6.67%","-1.92%"\n'
    '"FCX","Freeport-McMoRan Inc","Basic Materials","Copper","65992.71","-22.37%",'
    '"-9.03%","-6.37%"\n'
    '"NA","Nano Labs Ltd","Technology","Semiconductors","100.0","1.00%","2.00%","-"\n'
)
UPTREND_CSV = '"Ticker"\n"OMAB"\n"FCX"\n'


def _details_df():
    import io
    return pd.read_csv(io.StringIO(DETAILS_CSV), dtype=str, keep_default_na=False)


class TestIndustryKeyFor:
    @pytest.mark.parametrize("name,key", [
        ("Airports & Air Services", "ind_airportsairservices"),
        ("Copper", "ind_copper"),
        ("Oil & Gas E&P", "ind_oilgasep"),
        ("REIT - Healthcare Facilities", "ind_reithealthcarefacilities"),
    ])
    def test_maps_finviz_industry_name_to_worksheet(self, name, key):
        assert key in INDUSTRIES
        assert industry_key_for(name) == key

    def test_unknown_industry_returns_none(self):
        assert industry_key_for("Not An Industry") is None
        assert industry_key_for("") is None


class TestBuildDetailsUrl:
    def _params(self, url):
        return parse_qs(urlparse(url).query)

    def test_details_url_uses_base_filters_and_detail_columns(self):
        params = self._params(build_details_url("https://elite.finviz.com", "KEY", uptrend=False))
        assert params["f"] == [",".join(BASE_FILTERS)]
        assert params["c"] == [DETAIL_COLUMN_IDS]
        assert params["type"] == ["stocks"]
        assert params["auth"] == ["KEY"]

    def test_uptrend_url_uses_uptrend_filters_and_ticker_only(self):
        params = self._params(build_details_url("https://elite.finviz.com", "KEY", uptrend=True))
        assert params["f"] == [",".join(UPTREND_FILTERS)]
        assert params["c"] == ["1"]

    def test_detail_columns_include_industry_and_market_cap(self):
        ids = DETAIL_COLUMN_IDS.split(",")
        for col in ("1", "4", "6", "66"):  # Ticker, Industry, Market Cap, Change
            assert col in ids


class TestBuildConstituentSnapshots:
    def test_groups_stocks_by_industry_with_uptrend_flag(self):
        snaps = build_constituent_snapshots(_details_df(), {"OMAB", "FCX"})
        airports = snaps["ind_airportsairservices"]
        assert list(airports.columns) == CONSTITUENT_COLUMNS
        assert sorted(airports["ticker"]) == ["CAAP", "OMAB"]
        flags = dict(zip(airports["ticker"], airports["is_uptrend"]))
        assert flags == {"CAAP": False, "OMAB": True}

    def test_parses_numbers_and_percent_strings(self):
        snaps = build_constituent_snapshots(_details_df(), set())
        caap = snaps["ind_airportsairservices"].set_index("ticker").loc["CAAP"]
        assert caap["market_cap"] == pytest.approx(3611.14)
        assert caap["change"] == pytest.approx(-0.0264)
        assert caap["perf_week"] == pytest.approx(-0.1144)
        assert caap["perf_ytd"] == pytest.approx(-0.1488)
        assert caap["company"] == "Corporacion America Airports SA"

    def test_ticker_na_kept_and_dash_becomes_nan(self):
        snaps = build_constituent_snapshots(_details_df(), set())
        row = snaps["ind_semiconductors"].iloc[0]
        assert row["ticker"] == "NA"
        assert pd.isna(row["change"])

    def test_every_stock_industry_gets_a_frame_even_if_empty(self):
        """An industry with no stocks today must be cleared, not left stale."""
        snaps = build_constituent_snapshots(_details_df(), set())
        assert snaps["ind_gold"].empty
        assert list(snaps["ind_gold"].columns) == CONSTITUENT_COLUMNS

    def test_fund_industries_are_skipped(self):
        """ETF/closed-end fund industries come from the ETF universe, not this export."""
        snaps = build_constituent_snapshots(_details_df(), set())
        for ws in FUND_WORKSHEETS:
            assert ws not in snaps

    def test_unknown_industry_rows_are_ignored(self):
        df = _details_df()
        df.loc[0, "Industry"] = "Brand New Industry"
        snaps = build_constituent_snapshots(df, set())
        assert snaps["ind_airportsairservices"]["ticker"].tolist() == ["OMAB"]


def _csv_response(text):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = 200
    resp.content = text.encode("utf-8")
    resp.raise_for_status = MagicMock()
    return resp


@pytest.fixture
def after_close_observation_clock(mocker):
    """Freeze the session policy clock after the 2026-11-13 XNYS close."""
    from datetime import datetime, timezone
    mocker.patch("src.collection_session.utc_now", return_value=datetime(2026, 11, 13, 22, tzinfo=timezone.utc))


@pytest.mark.usefixtures("after_close_observation_clock")
class TestConstituentCollector:
    @pytest.fixture
    def collector(self, db_client):
        config = CollectorConfig(
            finviz_api_key="test_key", max_retries=1, retry_delay=0.0, request_interval=0.0,
        )
        data_collector = DataCollector(db_client=db_client, config=config)
        return ConstituentCollector(data_collector, db_client)

    def _mock(self, collector, mocker, details=DETAILS_CSV, uptrend=UPTREND_CSV):
        return mocker.patch.object(
            collector._collector._session, "get",
            side_effect=[_csv_response(details), _csv_response(uptrend)],
        )

    def test_collect_saves_every_stock_industry(self, collector, db_client, mocker):
        self._mock(collector, mocker)
        saved = collector.collect("2026-11-13")
        assert saved == len(INDUSTRIES) - len(FUND_WORKSHEETS)
        airports = db_client.fetch_constituents("ind_airportsairservices")
        assert sorted(airports["ticker"]) == ["CAAP", "OMAB"]
        assert airports[airports["is_uptrend"]]["ticker"].tolist() == ["OMAB"]

    def test_makes_exactly_two_requests(self, collector, db_client, mocker):
        get = self._mock(collector, mocker)
        collector.collect("2026-11-13")
        assert get.call_count == 2

    def test_clears_industry_that_has_no_stocks_today(self, collector, db_client, mocker):
        stale = pd.DataFrame(
            [{"ticker": "OLD", "company": "Old", "market_cap": 1.0, "change": 0.0,
              "perf_week": 0.0, "perf_ytd": 0.0, "is_uptrend": False}],
            columns=CONSTITUENT_COLUMNS,
        )
        db_client.replace_constituents("ind_gold", "2026-11-12", stale)
        self._mock(collector, mocker)
        collector.collect("2026-11-13")
        assert db_client.fetch_constituents("ind_gold").empty

    def test_uptrend_ticker_outside_details_is_rejected(self, collector, db_client, mocker):
        """Uptrend list must be a subset of the details universe, else keep old data."""
        self._mock(collector, mocker, uptrend='"Ticker"\n"ZZZZ"\n')
        with pytest.raises(ValueError, match="subset"):
            collector.collect("2026-11-13")
        assert db_client.fetch_constituents("ind_airportsairservices").empty

    def test_safe_wrapper_never_raises(self, collector, db_client, mocker):
        """Stock lists are secondary data: a failure must not fail the daily collect."""
        self._mock(collector, mocker, details="<html>error</html>")
        assert collect_constituents_safely(collector._collector, db_client, "2026-11-13") is False

    def test_safe_wrapper_reports_success(self, collector, db_client, mocker):
        self._mock(collector, mocker)
        assert collect_constituents_safely(collector._collector, db_client, "2026-11-13") is True

    def test_invalid_response_writes_nothing(self, collector, db_client, mocker):
        self._mock(collector, mocker, details="<html>error</html>")
        with pytest.raises(ValueError):
            collector.collect("2026-11-13")
        assert db_client.fetch_constituents("ind_airportsairservices").empty
