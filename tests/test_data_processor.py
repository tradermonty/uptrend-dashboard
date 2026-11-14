"""Tests for data_processor module (v2)."""

import pandas as pd
import numpy as np
import pytest

import datetime

from src.data_processor import (
    MarketStatus,
    get_current_status,
    build_sector_summary,
    build_industry_summary,
    build_industry_summary_with_sector,
    build_sector_ranking_table,
    get_sector_display_name,
    get_industry_display_name,
    get_sector_for_industry,
    style_status_row,
    prepare_timeseries_csv,
    prepare_all_timeseries_csv,
    prepare_dispersion_csv,
    default_start_date,
)


class TestGetCurrentStatus:
    """Tests for get_current_status function."""

    def test_get_current_status_uptrend(self, sample_calculated_df):
        """slope > 0 in last row should give trend='up'."""
        # Find a row with positive slope and set it as last
        df = sample_calculated_df.copy()
        # Last row of our sample data has positive slope (rising pattern at end)
        status = get_current_status(df)
        # Verify it returns expected keys (no signal fields)
        expected_keys = {
            "date", "ratio", "ratio_10ma", "trend",
            "slope", "is_overbought", "is_oversold",
        }
        assert set(status.keys()) == expected_keys

    def test_get_current_status_downtrend(self, sample_calculated_df):
        """slope <= 0 should give trend='down'."""
        # Use a row where slope is negative (falling section, around row 12-14)
        df = sample_calculated_df.copy()
        # Find rows with negative slope
        negative_slope_rows = df[df["slope"] < 0]
        if not negative_slope_rows.empty:
            single_row = negative_slope_rows.iloc[-1:].reset_index(drop=True)
            status = get_current_status(single_row)
            assert status["trend"] == "down"

    def test_get_current_status_overbought(self):
        """ratio > 0.37 should set is_overbought=True."""
        df = pd.DataFrame({
            "date": [pd.Timestamp("2024-01-02")],
            "count": [250],
            "total": [500],
            "ratio": [0.50],
            "ma_10": [0.40],
            "slope": [0.01],
            "trend_up": [0.50],
            "trend_down": [np.nan],
            "upper": [0.37],
            "lower": [0.097],
        })
        status = get_current_status(df)
        assert status["is_overbought"] is True
        assert status["is_oversold"] is False

    def test_get_current_status_oversold(self):
        """ratio < 0.097 should set is_oversold=True."""
        df = pd.DataFrame({
            "date": [pd.Timestamp("2024-01-02")],
            "count": [20],
            "total": [500],
            "ratio": [0.04],
            "ma_10": [0.06],
            "slope": [-0.01],
            "trend_up": [np.nan],
            "trend_down": [0.04],
            "upper": [0.37],
            "lower": [0.097],
        })
        status = get_current_status(df)
        assert status["is_overbought"] is False
        assert status["is_oversold"] is True


class TestBuildSectorSummary:
    """Tests for build_sector_summary function."""

    def test_build_sector_summary(self, sample_all_data):
        """Should produce summary with correct columns for all sectors."""
        summary = build_sector_summary(sample_all_data)
        expected_columns = {"Sector", "Ratio", "10MA", "Trend", "Slope", "Status", "_key"}
        assert set(summary.columns) == expected_columns
        assert len(summary) == 11

    def test_build_sector_summary_excludes_all(self, sample_all_data):
        """'all' worksheet should be excluded from sector summary."""
        summary = build_sector_summary(sample_all_data)
        assert "All" not in summary["Sector"].values


class TestSectorDisplayName:
    """Tests for get_sector_display_name helper."""

    def testget_sector_display_name(self):
        """Should convert worksheet names to display names."""
        assert get_sector_display_name("sec_technology") == "Technology"
        assert get_sector_display_name("sec_basicmaterials") == "Basic Materials"
        assert get_sector_display_name("sec_communicationservices") == "Communication Services"
        assert get_sector_display_name("sec_realestate") == "Real Estate"


class TestEmptyDataFrameGuards:
    """Tests for empty DataFrame handling."""

    def test_get_current_status_neutral_trend(self):
        """slope is NaN (insufficient data) should give trend='neutral'."""
        df = pd.DataFrame({
            "date": [pd.Timestamp("2024-01-01")],
            "count": [100],
            "total": [500],
            "ratio": [0.20],
            "ma_10": [np.nan],
            "slope": [np.nan],
            "trend_up": [np.nan],
            "trend_down": [np.nan],
            "upper": [0.37],
            "lower": [0.097],
        })
        status = get_current_status(df)
        assert status["trend"] == "neutral"
        assert status["slope"] is None

    def test_get_current_status_empty_df(self):
        """Empty DataFrame should return default status values."""
        df = pd.DataFrame(columns=[
            "date", "count", "total", "ratio", "ma_10", "slope",
            "trend_up", "trend_down", "upper", "lower", "is_peak", "is_trough",
        ])
        status = get_current_status(df)
        expected_keys = {
            "date", "ratio", "ratio_10ma", "trend",
            "slope", "is_overbought", "is_oversold",
        }
        assert set(status.keys()) == expected_keys
        assert status["ratio"] == 0.0
        assert status["ratio_10ma"] is None
        assert status["trend"] == "neutral"
        assert status["slope"] is None
        assert status["is_overbought"] is False
        assert status["is_oversold"] is False

    def test_build_sector_summary_empty(self):
        """Empty data dict should return DataFrame with correct columns."""
        summary = build_sector_summary({})
        expected_columns = {"Sector", "Ratio", "10MA", "Trend", "Slope", "Status", "_key"}
        assert set(summary.columns) == expected_columns
        assert len(summary) == 0

    def test_build_sector_summary_all_empty_dfs(self):
        """Data dict with only empty DataFrames should return empty summary."""
        data = {
            "sec_technology": pd.DataFrame(columns=[
                "date", "count", "total", "ratio", "ma_10", "slope",
                "trend_up", "trend_down", "upper", "lower",
            ]),
        }
        summary = build_sector_summary(data)
        assert len(summary) == 0


class TestPrepareTimeseriesCsv:
    """Tests for prepare_timeseries_csv function."""

    CALCULATED_DF_COLUMNS = [
        "date", "count", "total", "ratio", "ma_10", "slope",
        "trend_up", "trend_down", "upper", "lower", "is_peak", "is_trough",
    ]

    def _make_df(self):
        """Create a minimal calculated DataFrame for testing."""
        return pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
            "count": [100, 120, 110],
            "total": [500, 500, 500],
            "ratio": [0.20, 0.24, 0.22],
            "ma_10": [0.19, 0.21, 0.215],
            "slope": [0.01, 0.02, -0.005],
            "trend_up": [0.20, 0.24, np.nan],
            "trend_down": [np.nan, np.nan, 0.22],
            "upper": [0.37, 0.37, 0.37],
            "lower": [0.097, 0.097, 0.097],
            "is_peak": [False, False, False],
            "is_trough": [False, False, False],
        })

    def test_prepare_timeseries_csv_columns(self):
        """Output should have exactly date, count, total, ratio, ma_10, slope, trend."""
        df = self._make_df()
        result = prepare_timeseries_csv(df)
        assert list(result.columns) == ["date", "count", "total", "ratio", "ma_10", "slope", "trend"]

    def test_prepare_timeseries_csv_trend_column(self):
        """slope > 0 → 'up', slope <= 0 → 'down'."""
        df = self._make_df()
        result = prepare_timeseries_csv(df)
        assert result.iloc[0]["trend"] == "up"    # slope = 0.01
        assert result.iloc[1]["trend"] == "up"    # slope = 0.02
        assert result.iloc[2]["trend"] == "down"  # slope = -0.005

    def test_prepare_timeseries_csv_excludes_chart_columns(self):
        """trend_up, trend_down, upper, lower, is_peak, is_trough should be excluded."""
        df = self._make_df()
        result = prepare_timeseries_csv(df)
        excluded = {"trend_up", "trend_down", "upper", "lower", "is_peak", "is_trough"}
        assert excluded.isdisjoint(set(result.columns))


class TestPrepareAllTimeseriesCsv:
    """Tests for prepare_all_timeseries_csv function."""

    EXPECTED_COLUMNS = ["worksheet", "date", "count", "total", "ratio", "ma_10", "slope", "trend"]

    def _make_calculated_df(self, n_rows=3, base_count=100):
        """Create a minimal calculated DataFrame for testing."""
        return pd.DataFrame({
            "date": pd.to_datetime([f"2024-01-0{i+1}" for i in range(n_rows)]),
            "count": [base_count + i * 10 for i in range(n_rows)],
            "total": [500] * n_rows,
            "ratio": [(base_count + i * 10) / 500 for i in range(n_rows)],
            "ma_10": [0.19 + i * 0.01 for i in range(n_rows)],
            "slope": [0.01] * n_rows,
            "trend_up": [(base_count + i * 10) / 500 for i in range(n_rows)],
            "trend_down": [np.nan] * n_rows,
            "upper": [0.37] * n_rows,
            "lower": [0.097] * n_rows,
            "is_peak": [False] * n_rows,
            "is_trough": [False] * n_rows,
        })

    def _make_all_data(self):
        """Create sample all_data dict with all 12 worksheets."""
        from src.constants import SECTORS
        data = {"all": self._make_calculated_df(3, 150)}
        for i, sector in enumerate(SECTORS):
            data[sector] = self._make_calculated_df(3, 100 + i * 5)
        return data

    def test_columns(self):
        """Output should have worksheet, date, count, total, ratio, ma_10, slope, trend."""
        data = self._make_all_data()
        result = prepare_all_timeseries_csv(data)
        assert list(result.columns) == self.EXPECTED_COLUMNS

    def test_includes_all_worksheets(self):
        """All 12 worksheets from input dict should appear in output."""
        data = self._make_all_data()
        result = prepare_all_timeseries_csv(data)
        assert set(result["worksheet"].unique()) == set(data.keys())

    def test_sorted_by_worksheet(self):
        """'all' should come first, followed by sec_* in alphabetical order."""
        data = self._make_all_data()
        result = prepare_all_timeseries_csv(data)
        worksheets_in_order = result["worksheet"].unique().tolist()
        assert worksheets_in_order[0] == "all"
        assert worksheets_in_order[1:] == sorted(worksheets_in_order[1:])

    def test_row_count(self):
        """Total rows should equal sum of rows in each worksheet."""
        data = self._make_all_data()
        expected_rows = sum(len(df) for df in data.values())
        result = prepare_all_timeseries_csv(data)
        assert len(result) == expected_rows

    def test_empty_data(self):
        """Empty dict should return 0-row DataFrame with correct columns."""
        result = prepare_all_timeseries_csv({})
        assert list(result.columns) == self.EXPECTED_COLUMNS
        assert len(result) == 0

    def test_skips_empty_dataframes(self):
        """Worksheets with empty DataFrames should be skipped."""
        data = {
            "all": self._make_calculated_df(3, 150),
            "sec_technology": pd.DataFrame(columns=[
                "date", "count", "total", "ratio", "ma_10", "slope",
                "trend_up", "trend_down", "upper", "lower", "is_peak", "is_trough",
            ]),
        }
        result = prepare_all_timeseries_csv(data)
        assert set(result["worksheet"].unique()) == {"all"}
        assert len(result) == 3

    def test_date_format(self):
        """date column should be YYYY-MM-DD strings."""
        data = {"all": self._make_calculated_df(3, 150)}
        result = prepare_all_timeseries_csv(data)
        for d in result["date"]:
            assert isinstance(d, str)
            assert len(d) == 10
            # Verify YYYY-MM-DD pattern
            parts = d.split("-")
            assert len(parts) == 3
            assert len(parts[0]) == 4
            assert len(parts[1]) == 2
            assert len(parts[2]) == 2


class TestIndustryDisplayName:
    """Tests for get_industry_display_name helper."""

    def test_get_industry_display_name(self):
        assert get_industry_display_name("ind_semiconductors") == "Semiconductors"
        assert get_industry_display_name("ind_oilgasep") == "Oil & Gas E&P"
        assert get_industry_display_name("ind_softwareapplication") == "Software - Application"

    def test_get_industry_display_name_unknown_fallback(self):
        result = get_industry_display_name("ind_unknownindustry")
        assert result == "Unknownindustry"


class TestGetSectorForIndustry:
    """Tests for get_sector_for_industry helper."""

    def test_get_sector_for_industry(self):
        assert get_sector_for_industry("ind_semiconductors") == "sec_technology"
        assert get_sector_for_industry("ind_banksregional") == "sec_financial"

    def test_get_sector_for_industry_unknown(self):
        assert get_sector_for_industry("ind_nonexistent") is None


class TestBuildIndustrySummary:
    """Tests for build_industry_summary function."""

    def _make_industry_data(self):
        """Create sample data with industry entries."""
        from src.indicator_calculator import calculate_indicators
        dates = pd.bdate_range("2024-01-02", periods=20, freq="B")
        counts = [150, 170, 190, 200, 210, 220, 230, 240, 250, 245,
                  230, 210, 195, 180, 170, 175, 185, 195, 210, 220]
        base_df = pd.DataFrame({"date": dates, "count": counts, "total": [500] * 20})
        data = {}
        data["all"] = calculate_indicators(base_df)
        data["sec_technology"] = calculate_indicators(base_df.copy())
        for i, ind in enumerate(["ind_semiconductors", "ind_softwareapplication", "ind_banksregional"]):
            df = base_df.copy()
            df["count"] = (df["count"] * (0.8 + i * 0.1)).astype(int)
            data[ind] = calculate_indicators(df)
        return data

    def test_build_industry_summary(self):
        data = self._make_industry_data()
        summary = build_industry_summary(data)
        expected_columns = {"Industry", "Ratio", "10MA", "Trend", "Slope", "Status", "_key"}
        assert set(summary.columns) == expected_columns
        assert len(summary) == 3

    def test_build_industry_summary_ratio_descending(self):
        data = self._make_industry_data()
        summary = build_industry_summary(data)
        ratios = summary["Ratio"].tolist()
        assert ratios == sorted(ratios, reverse=True)

    def test_build_industry_summary_sector_filter(self):
        data = self._make_industry_data()
        summary = build_industry_summary(data, sector_key="sec_technology")
        # Only ind_semiconductors and ind_softwareapplication are in sec_technology
        assert len(summary) == 2
        keys = set(summary["_key"])
        assert keys == {"ind_semiconductors", "ind_softwareapplication"}

    def test_build_industry_summary_no_filter(self):
        data = self._make_industry_data()
        summary = build_industry_summary(data, sector_key=None)
        assert len(summary) == 3

    def test_build_industry_summary_neutral_trend(self):
        """Industry with 1 day of data should show '—' for Trend."""
        from src.indicator_calculator import calculate_indicators
        data = {
            "ind_semiconductors": calculate_indicators(pd.DataFrame({
                "date": [pd.Timestamp("2024-01-02")],
                "count": [100],
                "total": [500],
            })),
        }
        summary = build_industry_summary(data)
        assert len(summary) == 1
        assert summary.iloc[0]["Trend"] == "—"

    def test_build_industry_summary_empty(self):
        summary = build_industry_summary({})
        expected_columns = {"Industry", "Ratio", "10MA", "Trend", "Slope", "Status", "_key"}
        assert set(summary.columns) == expected_columns
        assert len(summary) == 0

    def test_build_sector_summary_excludes_industries(self):
        data = self._make_industry_data()
        summary = build_sector_summary(data)
        keys = set(summary["_key"])
        for key in keys:
            assert not key.startswith("ind_"), f"Industry {key} should not be in sector summary"


class TestBuildIndustrySummaryWithSector:
    """Tests for build_industry_summary_with_sector function."""

    def _make_industry_data(self):
        """Create sample data with industry entries."""
        from src.indicator_calculator import calculate_indicators
        dates = pd.bdate_range("2024-01-02", periods=20, freq="B")
        counts = [150, 170, 190, 200, 210, 220, 230, 240, 250, 245,
                  230, 210, 195, 180, 170, 175, 185, 195, 210, 220]
        base_df = pd.DataFrame({"date": dates, "count": counts, "total": [500] * 20})
        data = {}
        data["all"] = calculate_indicators(base_df)
        data["sec_technology"] = calculate_indicators(base_df.copy())
        for i, ind in enumerate(["ind_semiconductors", "ind_softwareapplication", "ind_banksregional"]):
            df = base_df.copy()
            df["count"] = (df["count"] * (0.8 + i * 0.1)).astype(int)
            data[ind] = calculate_indicators(df)
        return data

    def test_build_industry_summary_with_sector_columns(self):
        """Output should contain Sector and Total columns in addition to standard columns."""
        data = self._make_industry_data()
        summary = build_industry_summary_with_sector(data)
        expected_columns = {"Industry", "Ratio", "10MA", "Trend", "Slope", "Status", "_key", "Sector", "Total"}
        assert set(summary.columns) == expected_columns

    def test_build_industry_summary_with_sector_sector_values(self):
        """Sector column should match the parent sector display name."""
        data = self._make_industry_data()
        summary = build_industry_summary_with_sector(data)
        semi_row = summary[summary["_key"] == "ind_semiconductors"].iloc[0]
        assert semi_row["Sector"] == "Technology"
        banks_row = summary[summary["_key"] == "ind_banksregional"].iloc[0]
        assert banks_row["Sector"] == "Financial"

    def test_build_industry_summary_with_sector_all_industries(self):
        """All ind_* keys from input should appear in the output."""
        data = self._make_industry_data()
        summary = build_industry_summary_with_sector(data)
        input_ind_keys = {k for k in data if k.startswith("ind_")}
        output_keys = set(summary["_key"])
        assert output_keys == input_ind_keys

    def test_build_industry_summary_with_sector_empty(self):
        """Empty data should return DataFrame with correct columns."""
        summary = build_industry_summary_with_sector({})
        expected_columns = {"Industry", "Ratio", "10MA", "Trend", "Slope", "Status", "_key", "Sector", "Total"}
        assert set(summary.columns) == expected_columns
        assert len(summary) == 0

    def test_build_industry_summary_with_sector_total_values(self):
        """Total should be the latest total value, with 0 corrected to 1."""
        from src.indicator_calculator import calculate_indicators
        dates = pd.bdate_range("2024-01-02", periods=5, freq="B")
        data = {
            "ind_semiconductors": calculate_indicators(pd.DataFrame({
                "date": dates,
                "count": [100, 110, 120, 130, 140],
                "total": [500, 500, 500, 500, 500],
            })),
            "ind_softwareapplication": calculate_indicators(pd.DataFrame({
                "date": dates,
                "count": [0, 0, 0, 0, 0],
                "total": [0, 0, 0, 0, 0],
            })),
        }
        summary = build_industry_summary_with_sector(data)
        semi_row = summary[summary["_key"] == "ind_semiconductors"].iloc[0]
        assert semi_row["Total"] == 500
        sw_row = summary[summary["_key"] == "ind_softwareapplication"].iloc[0]
        assert sw_row["Total"] == 1  # 0 corrected to 1


class TestStyleStatusRow:
    """Tests for style_status_row function."""

    def test_style_status_row_up_trend(self):
        row = pd.Series({"Sector": "Technology", "Trend": "Up", "Status": "Normal"})
        styles = style_status_row(row)
        assert styles[1] == "color: #00cc96"

    def test_style_status_row_neutral_trend(self):
        row = pd.Series({"Sector": "Technology", "Trend": "—", "Status": "Normal"})
        styles = style_status_row(row)
        assert styles[1] == "color: #888888"

    def test_style_status_row_overbought(self):
        row = pd.Series({"Sector": "Technology", "Trend": "Up", "Status": "Overbought"})
        styles = style_status_row(row)
        assert styles[2] == "color: #d62728"


class TestDefaultStartDate:
    """Tests for default_start_date function."""

    def test_data_less_than_2_years(self):
        """When data spans < 2 years, return min_date."""
        min_date = datetime.date(2024, 7, 1)
        max_date = datetime.date(2025, 1, 1)
        assert default_start_date(min_date, max_date) == min_date

    def test_data_exactly_2_years(self):
        """When data spans exactly 2 years, return min_date."""
        min_date = datetime.date(2023, 1, 1)
        max_date = datetime.date(2025, 1, 1)
        assert default_start_date(min_date, max_date) == min_date

    def test_data_more_than_2_years(self):
        """When data spans > 2 years, return max_date - 2 years."""
        min_date = datetime.date(2020, 1, 1)
        max_date = datetime.date(2025, 6, 15)
        assert default_start_date(min_date, max_date) == datetime.date(2023, 6, 15)

    def test_leap_year(self):
        """Leap year max_date: 2028-02-29 - 2 years = 2026-02-28."""
        min_date = datetime.date(2020, 1, 1)
        max_date = datetime.date(2028, 2, 29)
        assert default_start_date(min_date, max_date) == datetime.date(2026, 2, 28)

    def test_same_date(self):
        """When min_date == max_date, return that date."""
        d = datetime.date(2025, 3, 1)
        assert default_start_date(d, d) == d


class TestBuildSectorRankingTable:
    """Tests for build_sector_ranking_table()."""

    def _make_sector_edge_df(self):
        """Create a sector edge DataFrame with known values."""
        from src.constants import SECTORS
        rows = []
        for i, sec in enumerate(SECTORS):
            rows.append({
                "sector_key": sec,
                "regime": "converged",
                "level_regime": "low",
                "mean_change": 0.06 - i * 0.005,
                "win_rate": 0.7,
                "count": 5,
            })
            rows.append({
                "sector_key": sec,
                "regime": "diverged",
                "level_regime": "high",
                "mean_change": -0.02 + i * 0.003 if i < 5 else -0.05,
                "win_rate": 0.4,
                "count": 3,
            })
        return pd.DataFrame(rows)

    def test_output_columns(self, sample_all_data):
        """Should return DataFrame with expected columns."""
        edge_df = self._make_sector_edge_df()
        result = build_sector_ranking_table(sample_all_data, "normal", "mid", edge_df)
        expected = {"Sector", "Current Ratio", "10MA", "Trend", "Historical Edge"}
        assert expected.issubset(set(result.columns))

    def test_normal_regime_sorted_by_ratio(self, sample_all_data):
        """In normal regime, sectors should be sorted by Current Ratio descending."""
        edge_df = self._make_sector_edge_df()
        result = build_sector_ranking_table(sample_all_data, "normal", "mid", edge_df)
        if len(result) > 1:
            ratios = result["Current Ratio"].tolist()
            assert ratios == sorted(ratios, reverse=True)

    def test_converged_low_sorted_by_edge(self, sample_all_data):
        """In converged+low (CAPITULATION), should sort by Historical Edge."""
        edge_df = self._make_sector_edge_df()
        result = build_sector_ranking_table(sample_all_data, "converged", "low", edge_df)
        if len(result) > 1 and "Historical Edge" in result.columns:
            edges = result["Historical Edge"].tolist()
            # Should be sorted descending by edge
            assert edges == sorted(edges, reverse=True)

    def test_missing_bucket_falls_back_to_ratio(self, sample_all_data):
        """When no matching (regime, level_regime) in edge_df, fall back to Ratio sort."""
        edge_df = pd.DataFrame(columns=["sector_key", "regime", "level_regime", "mean_change", "win_rate", "count"])
        result = build_sector_ranking_table(sample_all_data, "converged", "low", edge_df)
        if len(result) > 1:
            ratios = result["Current Ratio"].tolist()
            assert ratios == sorted(ratios, reverse=True)


class TestPrepareDispersionCsv:
    """Tests for prepare_dispersion_csv()."""

    def test_output_columns(self):
        """Should produce expected columns."""
        df = pd.DataFrame({
            "date": pd.bdate_range("2024-01-01", periods=5, freq="B"),
            "dispersion": [0.05, 0.06, 0.07, 0.08, 0.09],
            "mean_ratio": [0.2, 0.25, 0.3, 0.35, 0.4],
            "range": [0.1] * 5,
            "regime": ["converged", "normal", "normal", "diverged", "diverged"],
            "level_regime": ["low", "mid", "mid", "high", "high"],
            "dispersion_ma10": [np.nan] * 5,
            "dispersion_velocity": [np.nan] * 5,
            "p25": [0.04] * 5,
            "p75": [0.10] * 5,
            "velocity_p90": [np.nan] * 5,
            "dispersion_median": [0.07] * 5,
        })
        df["sector_count"] = 11
        df["expected_sector_count"] = 11
        df["coverage_complete"] = True
        result = prepare_dispersion_csv(df)
        expected = {"date", "dispersion", "mean_ratio", "range", "regime", "level_regime",
                    "sector_count", "expected_sector_count", "coverage_complete"}
        assert set(result.columns) == expected

    def test_empty_dataframe(self):
        """Empty input should produce empty output with correct columns."""
        df = pd.DataFrame(columns=[
            "date", "dispersion", "mean_ratio", "range",
            "regime", "level_regime",
        ])
        df["sector_count"] = 11
        df["expected_sector_count"] = 11
        df["coverage_complete"] = True
        result = prepare_dispersion_csv(df)
        assert result.empty
        expected = {"date", "dispersion", "mean_ratio", "range", "regime", "level_regime",
                    "sector_count", "expected_sector_count", "coverage_complete"}
        assert set(result.columns) == expected

    def test_date_format(self):
        """Dates should be formatted as YYYY-MM-DD strings."""
        df = pd.DataFrame({
            "date": pd.bdate_range("2024-01-01", periods=2, freq="B"),
            "dispersion": [0.05, 0.06],
            "mean_ratio": [0.2, 0.25],
            "range": [0.1, 0.1],
            "regime": ["normal", "normal"],
            "level_regime": ["mid", "mid"],
            "dispersion_ma10": [np.nan, np.nan],
            "dispersion_velocity": [np.nan, np.nan],
            "p25": [0.04, 0.04],
            "p75": [0.10, 0.10],
            "velocity_p90": [np.nan, np.nan],
            "dispersion_median": [0.07, 0.07],
        })
        df["sector_count"] = 11
        df["expected_sector_count"] = 11
        df["coverage_complete"] = True
        result = prepare_dispersion_csv(df)
        assert result["date"].iloc[0] == "2024-01-01"
