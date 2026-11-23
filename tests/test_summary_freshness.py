"""Per-row freshness (As Of / Stale) in sector and industry summaries (Issue #6)."""

import pandas as pd

from src.constants import STALE_AFTER_SESSIONS
from src.data_processor import (
    build_industry_summary,
    build_industry_summary_with_sector,
    build_sector_summary,
    split_stale_rows,
    stale_rows_caption,
)
from src.indicator_calculator import calculate_indicators


def _series(dates):
    n = len(dates)
    return calculate_indicators(pd.DataFrame({
        "date": pd.to_datetime(dates), "count": [100 + i for i in range(n)], "total": [500] * n,
    }))


def _data():
    full = pd.bdate_range("2026-03-02", "2026-10-02").strftime("%Y-%m-%d").tolist()
    old = [d for d in full if d <= "2026-03-27"]
    return {
        "all": _series(full),
        "sec_technology": _series(full),
        "sec_energy": _series(full[:-1]),            # one session behind
        "ind_semiconductors": _series(full),
        "ind_infrastructureoperations": _series(old),  # Issue #6 example
    }


class TestIndustryFreshness:

    def test_rows_carry_as_of_and_stale(self):
        summary = build_industry_summary(_data()).set_index("_key")
        assert summary.loc["ind_semiconductors", "As Of"] == "2026-10-02"
        assert not summary.loc["ind_semiconductors", "Stale"]
        assert summary.loc["ind_infrastructureoperations", "As Of"] == "2026-03-27"
        assert summary.loc["ind_infrastructureoperations", "Stale"]

    def test_new_columns_are_appended_after_existing_ones(self):
        cols = list(build_industry_summary(_data()).columns)
        assert cols[:7] == ["Industry", "Ratio", "10MA", "Trend", "Slope", "Status", "_key"]
        assert cols[7:] == ["As Of", "Stale"]

    def test_empty_summary_has_freshness_columns(self):
        assert {"As Of", "Stale"} <= set(build_industry_summary({}).columns)

    def test_with_sector_keeps_freshness(self):
        summary = build_industry_summary_with_sector(_data()).set_index("_key")
        assert summary.loc["ind_infrastructureoperations", "Stale"]
        assert {"Sector", "Total"} <= set(summary.columns)

    def test_freshness_reference_is_latest_date_across_all_data(self):
        # A sector page passes a subset; the market row still defines "today"
        data = _data()
        subset = {k: data[k] for k in ("all", "ind_infrastructureoperations")}
        assert build_industry_summary(subset).iloc[0]["Stale"]


class TestSectorFreshness:

    def test_one_session_behind_is_stale(self):
        assert STALE_AFTER_SESSIONS == 1
        summary = build_sector_summary(_data()).set_index("_key")
        assert summary.loc["sec_energy", "As Of"] == "2026-10-01"
        assert summary.loc["sec_energy", "Stale"]
        assert not summary.loc["sec_technology", "Stale"]


class TestStaleHelpers:

    def test_split_stale_rows(self):
        fresh, stale = split_stale_rows(build_industry_summary(_data()))
        assert fresh["_key"].tolist() == ["ind_semiconductors"]
        assert stale["_key"].tolist() == ["ind_infrastructureoperations"]

    def test_split_without_column_treats_all_as_fresh(self):
        df = pd.DataFrame({"Industry": ["A"]})
        fresh, stale = split_stale_rows(df)
        assert len(fresh) == 1 and stale.empty

    def test_caption_names_stale_rows_with_dates(self):
        _, stale = split_stale_rows(build_industry_summary(_data()))
        text = stale_rows_caption(stale, "Industry")
        assert "1" in text and "Infrastructure Operations" in text and "2026-03-27" in text

    def test_caption_empty_when_nothing_stale(self):
        assert stale_rows_caption(pd.DataFrame(columns=["Industry", "As Of"]), "Industry") == ""


class TestStaleStyling:

    def test_stale_as_of_is_highlighted(self):
        from src.data_processor import style_status_row
        row = pd.Series({"Trend": "Up", "Status": "Normal", "As Of": "2026-03-27", "Stale": True})
        styles = dict(zip(row.index, style_status_row(row)))
        assert "font-weight: bold" in styles["As Of"]
        assert styles["Stale"] == styles["As Of"]

    def test_fresh_as_of_is_plain(self):
        from src.data_processor import style_status_row
        row = pd.Series({"Trend": "Up", "Status": "Normal", "As Of": "2026-10-02", "Stale": False})
        styles = dict(zip(row.index, style_status_row(row)))
        assert styles["As Of"] == "" and styles["Stale"] == ""


class TestRobustReference:
    """The reference session is the median worksheet's latest date, not the max."""

    def _base(self):
        full = pd.bdate_range("2026-09-01", "2026-10-02").strftime("%Y-%m-%d").tolist()
        data = {"all": _series(full)}
        for k in ("ind_semiconductors", "ind_banksregional", "ind_gold", "ind_solar"):
            data[k] = _series(full)
        return data, full

    def test_one_outlier_future_date_does_not_make_everything_stale(self):
        data, full = self._base()
        data["all"] = _series(full + ["2026-10-09"])
        assert not build_industry_summary(data)["Stale"].any()

    def test_market_ahead_of_industries_mid_collection(self):
        data, full = self._base()
        data["all"] = _series(full + ["2026-10-05"])
        data["sec_technology"] = _series(full + ["2026-10-05"])
        assert not build_industry_summary(data)["Stale"].any()

    def test_genuinely_old_industry_still_stale(self):
        data, full = self._base()
        data["ind_infrastructureoperations"] = _series(full[:5])
        summary = build_industry_summary(data).set_index("_key")
        assert summary.loc["ind_infrastructureoperations", "Stale"]
        assert not summary.loc["ind_gold", "Stale"]


class TestStaleVisibility:

    def test_stale_column_kept_on_phones(self):
        from src.mobile_ui import mobile_columns
        assert "Stale" in mobile_columns(build_industry_summary(_data()).columns, True)

    def test_order_stale_last_keeps_fresh_order(self):
        from src.data_processor import order_stale_last
        df = pd.DataFrame({"k": ["a", "b", "c"], "Stale": [False, True, False]})
        assert order_stale_last(df)["k"].tolist() == ["a", "c", "b"]
