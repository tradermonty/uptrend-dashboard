"""S&P 500 price panel above the market Uptrend Ratio (v6.5)."""

import json
from pathlib import Path

import pandas as pd
import pytest

from src.chart_builder import DOWNTREND_BAND_NAME, PANEL_DIVIDER_NAME, build_market_chart, build_ratio_chart, has_price_panel
from src.data_loader import load_sp500_prices

ROOT = Path(__file__).resolve().parents[1]

CSV = (
    "Date,S&P500_Price,Breadth_Index_Raw\n"
    "2024-01-03,470.5,0.5\n"
    "2024-01-02,472.6,0.5\n"
    "2024-01-04,,0.5\n"
)


@pytest.fixture
def csv_file(tmp_path):
    path = tmp_path / "market_breadth_data.csv"
    path.write_text(CSV)
    return str(path)


def _ratio_df(sample_calculated_df):
    return sample_calculated_df


def _prices(dates, start=100.0):
    return pd.DataFrame({"date": pd.to_datetime(dates), "close": [start + i for i in range(len(dates))]})


class TestLoadSp500Prices:

    def test_reads_date_and_close_sorted_without_blanks(self, csv_file):
        df = load_sp500_prices(csv_file)
        assert list(df.columns) == ["date", "close"]
        assert list(df["date"].dt.strftime("%Y-%m-%d")) == ["2024-01-02", "2024-01-03"]
        assert list(df["close"]) == [472.6, 470.5]

    def test_missing_source_gives_an_empty_frame(self, tmp_path):
        df = load_sp500_prices(str(tmp_path / "nope.csv"))
        assert df.empty and list(df.columns) == ["date", "close"]

    def test_missing_price_column_gives_an_empty_frame(self, tmp_path):
        path = tmp_path / "x.csv"
        path.write_text("Date,Other\n2024-01-02,1\n")
        assert load_sp500_prices(str(path)).empty

    def test_blank_source_disables_the_panel(self):
        assert load_sp500_prices("").empty

    def test_source_defaults_to_the_env_setting(self, csv_file, monkeypatch):
        monkeypatch.setenv("SP500_PRICE_CSV", csv_file)
        assert len(load_sp500_prices()) == 2

    def test_http_failure_gives_an_empty_frame(self, mocker):
        mocker.patch("requests.get", side_effect=OSError("network down"))
        assert load_sp500_prices("https://example.invalid/x.csv").empty


class TestBuildMarketChart:

    def test_price_panel_on_top_ratio_below(self, sample_calculated_df):
        prices = _prices(sample_calculated_df["date"])
        fig = build_market_chart(sample_calculated_df, prices, title="T")
        price = [t for t in fig.data if t.name == "S&P 500"]
        assert len(price) == 1 and price[0].yaxis == "y"
        ratio = [t for t in fig.data if t.name != "S&P 500"]
        assert ratio and all(t.yaxis == "y2" for t in ratio)
        assert fig.layout.yaxis.type == "log"
        assert fig.layout.yaxis.domain[0] > fig.layout.yaxis2.domain[1]  # price above ratio
        assert fig.layout.yaxis2.tickformat == ".0%"

    def test_panels_share_the_time_axis(self, sample_calculated_df):
        fig = build_market_chart(sample_calculated_df, _prices(sample_calculated_df["date"]), title="T")
        assert fig.layout.xaxis.matches == "x2" or fig.layout.xaxis2.matches == "x"

    def test_ratio_panel_is_taller(self, sample_calculated_df):
        fig = build_market_chart(sample_calculated_df, _prices(sample_calculated_df["date"]), title="T")
        top, bottom = fig.layout.yaxis.domain, fig.layout.yaxis2.domain
        assert (bottom[1] - bottom[0]) > (top[1] - top[0])

    def test_prices_are_cut_to_the_ratio_date_range(self, sample_calculated_df):
        dates = list(pd.bdate_range("2023-12-01", "2024-03-01"))
        fig = build_market_chart(sample_calculated_df, _prices(dates), title="T")
        x = pd.to_datetime(next(t for t in fig.data if t.name == "S&P 500").x)
        assert x.min() >= sample_calculated_df["date"].min()
        assert x.max() <= sample_calculated_df["date"].max()

    def test_price_label_shows_latest_close_and_date(self, sample_calculated_df):
        prices = _prices(sample_calculated_df["date"])
        fig = build_market_chart(sample_calculated_df, prices, title="T")
        labels = " ".join(a.text for a in fig.layout.annotations)
        last = prices.iloc[-1]
        assert "S&P 500 (SPY)" in labels
        assert f"{last['close']:,.2f}" in labels
        assert last["date"].strftime("%-m/%-d") in labels

    def test_without_prices_it_is_the_plain_ratio_chart(self, sample_calculated_df):
        empty = pd.DataFrame(columns=["date", "close"])
        fig = build_market_chart(sample_calculated_df, empty, title="T")
        plain = build_ratio_chart(sample_calculated_df, title="T")
        assert [t.name for t in fig.data] == [t.name for t in plain.data]
        assert "yaxis2" not in fig.layout.to_plotly_json()

    def test_no_prices_inside_the_range_falls_back_too(self, sample_calculated_df):
        fig = build_market_chart(sample_calculated_df, _prices(pd.bdate_range("2020-01-01", periods=5)), title="T")
        assert all(t.name != "S&P 500" for t in fig.data)


class TestUptrendRatioPage:

    @pytest.fixture(autouse=True)
    def _fresh_cache(self):
        import streamlit as st
        st.cache_data.clear()  # the price CSV is cached across pages and tests
        yield
        st.cache_data.clear()

    def test_page_draws_the_price_panel(self, tmp_path, monkeypatch):
        from streamlit.testing.v1 import AppTest
        from src.data_loader import load_sector_data
        dates = load_sector_data()["all"]["date"].tail(30)
        path = tmp_path / "prices.csv"
        pd.DataFrame({"Date": dates.dt.strftime("%Y-%m-%d"), "S&P500_Price": range(500, 530)}).to_csv(path, index=False)
        monkeypatch.setenv("SP500_PRICE_CSV", str(path))
        app = AppTest.from_file(str(ROOT / "views/0_Uptrend_Ratio.py"), default_timeout=30).run()
        assert not app.exception
        spec = json.loads(app.get("plotly_chart")[0].proto.spec)
        assert "S&P 500" in [t.get("name") for t in spec["data"]]
        assert spec["layout"]["yaxis"]["type"] == "log"
        assert spec["layout"]["title"]["text"] == "US Market Uptrend Ratio"

    def test_page_works_without_the_price_source(self, monkeypatch):
        from streamlit.testing.v1 import AppTest
        monkeypatch.setenv("SP500_PRICE_CSV", "")
        app = AppTest.from_file(str(ROOT / "views/0_Uptrend_Ratio.py"), default_timeout=30).run()
        assert not app.exception
        spec = json.loads(app.get("plotly_chart")[0].proto.spec)
        assert spec["layout"]["title"]["text"] == "US Market Uptrend Ratio"


class TestDowntrendShading:
    """Pink bands where the ratio's 10MA slope is down, across both panels (like Market Breadth)."""

    @staticmethod
    def _df(slopes):
        dates = pd.bdate_range("2024-01-02", periods=len(slopes))
        return pd.DataFrame({
            "date": dates, "ratio": 0.2, "ma_10": 0.2, "slope": slopes,
            "upper": 0.37, "lower": 0.097, "is_peak": False, "is_trough": False,
        })

    def _bands(self, slopes):
        df = self._df(slopes)
        fig = build_market_chart(df, _prices(df["date"]), title="T")
        return df, [s for s in fig.layout.shapes if s.name == DOWNTREND_BAND_NAME]

    def test_one_band_per_down_run_in_each_panel(self):
        _, bands = self._bands([0.1, -0.1, -0.2, 0.1, 0.1, -0.1, 0.2])
        assert len(bands) == 4
        assert sorted(b.yref for b in bands) == ["y domain", "y domain", "y2 domain", "y2 domain"]

    def test_bands_fill_each_panel_but_not_the_gap(self):
        _, bands = self._bands([0.1, -0.1, -0.2, 0.1])
        for b in bands:
            assert b.yref in ("y domain", "y2 domain") and (b.y0, b.y1) == (0, 1)
            assert b.layer == "below" and b.line.width == 0

    def test_a_divider_line_sits_in_the_gap_between_panels(self):
        df = self._df([0.1, -0.1, 0.1])
        fig = build_market_chart(df, _prices(df["date"]), title="T")
        lines = [s for s in fig.layout.shapes if s.name == PANEL_DIVIDER_NAME]
        assert len(lines) == 1
        line = lines[0]
        assert line.type == "line" and line.xref == "paper" and line.yref == "paper"
        assert (line.x0, line.x1) == (0, 1) and line.y0 == line.y1
        assert fig.layout.yaxis2.domain[1] < line.y0 < fig.layout.yaxis.domain[0]

    def test_no_divider_on_the_plain_fallback_chart(self):
        df = self._df([0.1, -0.1, 0.1])
        fig = build_market_chart(df, pd.DataFrame(columns=["date", "close"]), title="T")
        assert all(s.name != PANEL_DIVIDER_NAME for s in fig.layout.shapes)

    def test_band_runs_from_first_down_day_to_the_next_day(self):
        df, bands = self._bands([0.1, -0.1, -0.2, 0.1])
        assert pd.Timestamp(bands[0].x0) == df["date"][1]
        assert pd.Timestamp(bands[0].x1) == df["date"][3]  # continuous with the next session

    def test_down_run_at_the_end_stops_at_the_last_day(self):
        df, bands = self._bands([0.1, -0.1, -0.2])
        assert pd.Timestamp(bands[-1].x1) == df["date"][2]

    def test_no_bands_without_down_slopes(self):
        _, bands = self._bands([0.1, float("nan"), 0.2])
        assert bands == []


class TestReviewFixes:

    def test_http_error_status_gives_an_empty_frame(self, mocker):
        resp = mocker.Mock()
        resp.raise_for_status.side_effect = OSError("503")
        mocker.patch("requests.get", return_value=resp)
        assert load_sp500_prices("https://example.invalid/x.csv").empty

    def test_html_body_gives_an_empty_frame(self, mocker):
        resp = mocker.Mock(text="<html>maintenance</html>")
        mocker.patch("requests.get", return_value=resp)
        assert load_sp500_prices("https://example.invalid/x.csv").empty

    def test_request_uses_a_short_timeout(self, mocker):
        get = mocker.patch("requests.get", side_effect=OSError("x"))
        load_sp500_prices("https://example.invalid/x.csv")
        connect, read = get.call_args.kwargs["timeout"]
        assert connect <= 3 and read <= 5

    def test_a_failed_fetch_is_not_cached(self, csv_file, monkeypatch):
        import streamlit as st
        from src.data_loader import cached_load_sp500_prices
        st.cache_data.clear()
        monkeypatch.setenv("SP500_PRICE_CSV", csv_file + ".missing")
        assert cached_load_sp500_prices().empty
        monkeypatch.setenv("SP500_PRICE_CSV", csv_file)  # the source recovers
        assert len(cached_load_sp500_prices()) == 2
        st.cache_data.clear()

    def test_has_price_panel(self, sample_calculated_df):
        with_price = build_market_chart(sample_calculated_df, _prices(sample_calculated_df["date"]), title="T")
        without = build_market_chart(sample_calculated_df, pd.DataFrame(columns=["date", "close"]), title="T")
        assert has_price_panel(with_price) and not has_price_panel(without)

    def test_price_hover_names_the_index(self, sample_calculated_df):
        fig = build_market_chart(sample_calculated_df, _prices(sample_calculated_df["date"]), title="T")
        price = next(t for t in fig.data if t.name == "S&P 500")
        assert price.hovertemplate.startswith("S&P 500")
