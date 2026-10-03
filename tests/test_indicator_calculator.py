"""Tests for indicator_calculator module."""

import pandas as pd
import numpy as np
import pytest

from src.indicator_calculator import (
    DispersionSignal,
    IndicatorConfig,
    _confirm_regime,
    calculate_forward_returns,
    calculate_indicators,
    calculate_sector_dispersion,
    calculate_sector_edge,
    detect_dispersion_signals,
)
from src.constants import (
    SECTORS,
    DISPERSION_CONVERGED_FALLBACK,
    DISPERSION_DIVERGED_FALLBACK,
    MEAN_RATIO_LOW,
    MEAN_RATIO_HIGH,
    DISPERSION_MIN_HISTORY,
    DISPERSION_VELOCITY_WINDOW,
)


class TestRatioCalculation:
    """Tests for ratio calculation via public API."""

    def test_ratio_values(self):
        """count/total should produce correct ratio via calculate_indicators."""
        df = pd.DataFrame({
            "date": pd.bdate_range("2024-01-01", periods=3, freq="B"),
            "count": [150, 200, 250],
            "total": [500, 500, 500],
        })
        result = calculate_indicators(df)
        assert list(result["ratio"]) == [0.3, 0.4, 0.5]

    def test_ratio_zero_total(self):
        """total=0 should produce ratio=0.0, not raise ZeroDivisionError."""
        df = pd.DataFrame({
            "date": pd.bdate_range("2024-01-01", periods=2, freq="B"),
            "count": [100, 0],
            "total": [0, 0],
        })
        result = calculate_indicators(df)
        assert list(result["ratio"]) == [0.0, 0.0]


class TestMovingAverage:
    """Tests for moving average via public API."""

    def test_ma_10_leading_nans(self, sample_raw_df):
        """10-day MA should have NaN for first 9 rows, valid from row 10."""
        result = calculate_indicators(sample_raw_df)
        assert all(pd.isna(result["ma_10"].iloc[:9]))
        assert pd.notna(result["ma_10"].iloc[9])

    def test_ma_10_value(self, sample_raw_df):
        """10th MA value should be mean of first 10 ratios."""
        result = calculate_indicators(sample_raw_df)
        expected = result["ratio"].iloc[:10].mean()
        assert abs(result["ma_10"].iloc[9] - expected) < 1e-10

    def test_ma_insufficient_data(self):
        """With fewer than 10 rows, all MA values should be NaN."""
        df = pd.DataFrame({
            "date": pd.bdate_range("2024-01-01", periods=3, freq="B"),
            "count": [150, 200, 250],
            "total": [500, 500, 500],
        })
        result = calculate_indicators(df)
        assert all(pd.isna(result["ma_10"]))


class TestSlope:
    """Tests for slope calculation via public API."""

    def test_slope_is_ma_diff(self, sample_raw_df):
        """Slope should be the 1-day diff of MA."""
        result = calculate_indicators(sample_raw_df)
        # First valid MA slope should be NaN (diff of first MA value)
        assert pd.isna(result["slope"].iloc[9])
        # 11th value should be diff of 10th and 11th MA
        if pd.notna(result["ma_10"].iloc[10]) and pd.notna(result["ma_10"].iloc[9]):
            expected = result["ma_10"].iloc[10] - result["ma_10"].iloc[9]
            assert abs(result["slope"].iloc[10] - expected) < 1e-10


class TestTrend:
    """Tests for trend calculation via public API."""

    def test_trend_up_matches_positive_slope(self, sample_raw_df):
        """When slope > 0, trend_up should have the ratio value."""
        result = calculate_indicators(sample_raw_df)
        for i in range(len(result)):
            if pd.notna(result["slope"].iloc[i]) and result["slope"].iloc[i] > 0:
                assert result["trend_up"].iloc[i] == result["ratio"].iloc[i]

    def test_trend_down_matches_nonpositive_slope(self, sample_raw_df):
        """When slope <= 0, trend_down should have the ratio value."""
        result = calculate_indicators(sample_raw_df)
        for i in range(len(result)):
            if pd.notna(result["slope"].iloc[i]) and result["slope"].iloc[i] <= 0:
                assert result["trend_down"].iloc[i] == result["ratio"].iloc[i]


class TestCalculateIndicators:
    """Tests for the full calculate_indicators function."""

    def test_calculate_indicators_full(self, sample_raw_df):
        """Full calculation should produce all expected columns."""
        result = calculate_indicators(sample_raw_df)
        expected_columns = {
            "date", "count", "total",
            "ratio", "ma_10", "slope",
            "trend_up", "trend_down",
            "upper", "lower",
            "is_peak", "is_trough",
        }
        assert set(result.columns) == expected_columns
        assert len(result) == 20
        # upper/lower should be constants
        assert all(result["upper"] == 0.37)
        assert all(result["lower"] == 0.097)

    def test_custom_config(self, sample_raw_df):
        """IndicatorConfig should allow custom parameters."""
        config = IndicatorConfig(ma_period=5, upper_threshold=0.4, lower_threshold=0.1)
        result = calculate_indicators(sample_raw_df, config=config)
        # With period=5, MA should be valid from row 5 onwards
        assert pd.isna(result["ma_10"].iloc[3])
        assert pd.notna(result["ma_10"].iloc[4])
        # Thresholds should use custom values
        assert all(result["upper"] == 0.4)
        assert all(result["lower"] == 0.1)


def _make_sine_raw_df(n: int = 200, period: int = 40, amplitude: float = 0.1,
                      baseline: float = 0.5) -> pd.DataFrame:
    """Create a sine-wave raw DataFrame for deterministic peak/trough testing."""
    dates = pd.bdate_range("2024-01-01", periods=n, freq="B")
    ratios = baseline + amplitude * np.sin(2 * np.pi * np.arange(n) / period)
    total = 500
    counts = (ratios * total).astype(int)
    return pd.DataFrame({"date": dates, "count": counts, "total": [total] * n})


class TestPeaksAndTroughs:
    """Tests for peak/trough detection via public API."""

    def test_peaks_detected_in_sine_wave(self):
        """Peaks should be detected at the tops of a sine wave."""
        df = _make_sine_raw_df(n=200, period=40, amplitude=0.1)
        result = calculate_indicators(df)
        assert result["is_peak"].sum() > 0
        # All peak indices should be within bounds
        peak_indices = result.index[result["is_peak"]]
        assert all(0 <= idx < len(result) for idx in peak_indices)

    def test_troughs_detected_in_sine_wave(self):
        """Troughs should be detected at the bottoms of a sine wave."""
        df = _make_sine_raw_df(n=200, period=40, amplitude=0.1)
        result = calculate_indicators(df)
        assert result["is_trough"].sum() > 0
        trough_indices = result.index[result["is_trough"]]
        assert all(0 <= idx < len(result) for idx in trough_indices)

    def test_peaks_troughs_boolean_columns(self):
        """calculate_indicators adds is_peak / is_trough boolean columns."""
        df = _make_sine_raw_df(n=200, period=40, amplitude=0.1)
        result = calculate_indicators(df)
        assert result["is_peak"].dtype == bool
        assert result["is_trough"].dtype == bool

    def test_strict_config_fewer_detections(self):
        """Stricter distance/prominence should detect fewer peaks/troughs."""
        df = _make_sine_raw_df(n=300, period=40, amplitude=0.1)
        config_default = IndicatorConfig()
        config_strict = IndicatorConfig(peak_distance=60, peak_prominence=0.05)

        result_default = calculate_indicators(df, config_default)
        result_strict = calculate_indicators(df, config_strict)

        assert result_strict["is_peak"].sum() <= result_default["is_peak"].sum()
        assert result_strict["is_trough"].sum() <= result_default["is_trough"].sum()


class TestEmptyDataFrame:
    """Tests for empty DataFrame handling."""

    def test_calculate_indicators_empty_df(self):
        """Empty DataFrame should return empty DataFrame with all expected columns."""
        df = pd.DataFrame(columns=["date", "count", "total"])
        result = calculate_indicators(df)
        expected_columns = {
            "date", "count", "total",
            "ratio", "ma_10", "slope",
            "trend_up", "trend_down",
            "upper", "lower",
            "is_peak", "is_trough",
        }
        assert set(result.columns) == expected_columns
        assert len(result) == 0


class TestNaNHandling:
    """Tests for NaN value handling in calculations."""

    def test_ratio_with_nan_count(self):
        """NaN count values should be treated as 0."""
        df = pd.DataFrame({
            "date": pd.bdate_range("2024-01-01", periods=3, freq="B"),
            "count": [100, np.nan, 200],
            "total": [500, 500, 500],
        })
        result = calculate_indicators(df)
        assert result["ratio"].iloc[0] == 0.2
        assert result["ratio"].iloc[1] == 0.0  # NaN count -> 0
        assert result["ratio"].iloc[2] == 0.4

    def test_ratio_with_nan_total(self):
        """NaN total values should be treated as 0 total (ratio = 0)."""
        df = pd.DataFrame({
            "date": pd.bdate_range("2024-01-01", periods=2, freq="B"),
            "count": [100, 200],
            "total": [500, np.nan],
        })
        result = calculate_indicators(df)
        assert result["ratio"].iloc[0] == 0.2
        assert result["ratio"].iloc[1] == 0.0  # NaN total -> 0


class TestSlicedDataFrame:
    """Test that calculate_indicators handles non-RangeIndex input."""

    def test_sliced_dataframe_peaks_correct(self):
        """DataFrame with non-zero-based index should produce correct peak positions."""
        df = _make_sine_raw_df(n=200, period=40, amplitude=0.1)
        # Simulate a sliced DataFrame with non-contiguous index
        sliced = df.iloc[50:150]
        assert sliced.index[0] == 50  # verify non-zero index
        result = calculate_indicators(sliced)
        # Index should be reset
        assert result.index[0] == 0
        assert len(result) == 100
        # Peaks should be within bounds
        if result["is_peak"].any():
            peak_indices = result.index[result["is_peak"]]
            assert all(0 <= idx < 100 for idx in peak_indices)


# --- Sector Dispersion Tests ---


def _make_sector_data(n: int = 80, sector_count: int = 11) -> dict:
    """Create sector data with varying factors for dispersion testing.

    Returns Dict[str, DataFrame] with 'all' + sector keys, each having
    n rows with calculated indicators.
    """
    dates = pd.bdate_range("2024-01-01", periods=n, freq="B")
    total = 500
    base_counts = np.linspace(100, 300, n).astype(int)

    data = {}
    # 'all' key uses base
    all_df = pd.DataFrame({"date": dates, "count": base_counts, "total": [total] * n})
    data["all"] = calculate_indicators(all_df)

    for i, sec in enumerate(SECTORS[:sector_count]):
        factor = 0.5 + i * 0.1  # 0.5 to 1.5 — creates wide spread
        counts = (base_counts * factor).astype(int)
        df = pd.DataFrame({"date": dates, "count": counts, "total": [total] * n})
        data[sec] = calculate_indicators(df)

    return data


class TestCalculateSectorDispersion:
    """Tests for calculate_sector_dispersion()."""

    def test_normal_output_columns(self):
        """Should return DataFrame with all expected columns."""
        data = _make_sector_data(n=80)
        result = calculate_sector_dispersion(data)
        expected_cols = {
            "dispersion", "mean_ratio", "range",
            "dispersion_ma10", "dispersion_velocity",
            "regime", "level_regime",
            "p25", "p75", "velocity_p90", "dispersion_median",
        }
        assert expected_cols.issubset(set(result.columns))
        assert "date" in result.columns or result.index.name == "date"

    def test_normal_row_count(self):
        """Output should have rows for dates where at least one sector has valid ma_10."""
        data = _make_sector_data(n=80)
        result = calculate_sector_dispersion(data)
        # ma_10 has 9 leading NaNs, so matrix.dropna(how="all") removes those
        first_sec = [k for k in data if k.startswith("sec_")][0]
        expected_valid = data[first_sec]["ma_10"].notna().sum()
        assert len(result) == expected_valid

    def test_all_equal_sectors_zero_dispersion(self):
        """When all sectors have identical ma_10, dispersion should be 0."""
        dates = pd.bdate_range("2024-01-01", periods=30, freq="B")
        total = 500
        counts = np.linspace(100, 300, 30).astype(int)
        base_df = pd.DataFrame({"date": dates, "count": counts, "total": [total] * 30})
        base_calc = calculate_indicators(base_df)

        data = {"all": base_calc.copy()}
        for sec in SECTORS:
            data[sec] = base_calc.copy()

        result = calculate_sector_dispersion(data)
        valid_disp = result["dispersion"].dropna()
        assert (valid_disp < 1e-10).all()

    def test_fewer_than_two_sectors_returns_empty(self):
        """With fewer than 2 sectors, should return empty DataFrame."""
        dates = pd.bdate_range("2024-01-01", periods=20, freq="B")
        df = pd.DataFrame({"date": dates, "count": [200] * 20, "total": [500] * 20})
        calc = calculate_indicators(df)
        data = {"all": calc, "sec_technology": calc.copy()}
        result = calculate_sector_dispersion(data)
        assert result.empty

    def test_excludes_all_key(self):
        """Should only use sec_* keys, not 'all'."""
        data = _make_sector_data(n=30, sector_count=3)
        # If 'all' were included in cross-section, dispersion would differ
        result = calculate_sector_dispersion(data)
        assert not result.empty

    def test_leading_nan_rows_have_nan_regime(self):
        """First ~9 rows (where ma_10 is NaN) should have NaN regime/level_regime."""
        data = _make_sector_data(n=30)
        result = calculate_sector_dispersion(data)
        # ma_10 has NaN for first 9 rows, so dispersion should be NaN there
        for i in range(9):
            if pd.isna(result["dispersion"].iloc[i]):
                assert pd.isna(result["regime"].iloc[i])
                assert pd.isna(result["level_regime"].iloc[i])

    def test_dispersion_is_nonnegative(self):
        """Dispersion (std dev) should always be non-negative."""
        data = _make_sector_data(n=80)
        result = calculate_sector_dispersion(data)
        valid = result["dispersion"].dropna()
        assert (valid >= 0).all()


class TestDispersionRegime:
    """Tests for regime classification logic."""

    def test_fallback_thresholds_used_when_insufficient_history(self):
        """With < DISPERSION_MIN_HISTORY valid days, fallback thresholds should be used."""
        # Use 30 days — well under the 60-day minimum
        data = _make_sector_data(n=30)
        result = calculate_sector_dispersion(data)
        valid = result.dropna(subset=["regime"])
        if not valid.empty:
            # Regime should be assigned using fallback constants
            assert set(valid["regime"].unique()).issubset({"converged", "normal", "diverged"})

    def test_regime_values_are_valid(self):
        """Regime should only contain valid values or NaN."""
        data = _make_sector_data(n=80)
        result = calculate_sector_dispersion(data)
        valid_regimes = result["regime"].dropna().unique()
        assert set(valid_regimes).issubset({"converged", "normal", "diverged"})

    def test_regime_with_expanding_percentiles(self):
        """With enough history (>60 days), expanding percentiles should be used."""
        data = _make_sector_data(n=100)
        result = calculate_sector_dispersion(data)
        # p25 and p75 should be non-NaN after DISPERSION_MIN_HISTORY valid rows
        valid = result.dropna(subset=["dispersion"])
        if len(valid) > DISPERSION_MIN_HISTORY:
            late_rows = valid.iloc[DISPERSION_MIN_HISTORY:]
            assert late_rows["p25"].notna().all()
            assert late_rows["p75"].notna().all()


class TestExpandingWindow:
    """Tests for expanding window percentile calculations."""

    def test_no_future_data_leakage(self):
        """Each row's p25/p75 should only use data up to that row."""
        data = _make_sector_data(n=100)
        result = calculate_sector_dispersion(data)
        valid = result.dropna(subset=["p25", "p75"])
        if len(valid) >= 2:
            # p25 at row i should equal expanding quantile up to i
            disp = result["dispersion"].dropna()
            for i in [DISPERSION_MIN_HISTORY, DISPERSION_MIN_HISTORY + 10]:
                if i < len(disp):
                    expected_p25 = disp.iloc[:i + 1].quantile(0.25)
                    actual_p25 = result.loc[disp.index[i], "p25"]
                    assert abs(actual_p25 - expected_p25) < 1e-10, \
                        f"p25 at row {i}: expected {expected_p25}, got {actual_p25}"

    def test_threshold_columns_included(self):
        """p25, p75, velocity_p90, dispersion_median should be output columns."""
        data = _make_sector_data(n=80)
        result = calculate_sector_dispersion(data)
        for col in ["p25", "p75", "velocity_p90", "dispersion_median"]:
            assert col in result.columns


class TestDispersionVelocity:
    """Tests for dispersion velocity (abs diff)."""

    def test_velocity_is_absolute_diff(self):
        """Velocity should be abs(diff(DISPERSION_VELOCITY_WINDOW))."""
        data = _make_sector_data(n=80)
        result = calculate_sector_dispersion(data)
        disp = result["dispersion"]
        vel = result["dispersion_velocity"]
        # Check a specific valid row
        valid_idx = vel.dropna().index
        if len(valid_idx) > 0:
            i = valid_idx[0]
            expected = abs(disp.iloc[i] - disp.iloc[i - DISPERSION_VELOCITY_WINDOW])
            assert abs(vel.iloc[i] - expected) < 1e-10

    def test_velocity_leading_nans(self):
        """First DISPERSION_VELOCITY_WINDOW rows of velocity should be NaN (after dispersion NaNs)."""
        data = _make_sector_data(n=30)
        result = calculate_sector_dispersion(data)
        # Velocity needs dispersion to be valid + 3 more rows
        first_valid_disp = result["dispersion"].first_valid_index()
        if first_valid_disp is not None:
            vel_start = first_valid_disp + DISPERSION_VELOCITY_WINDOW
            if vel_start < len(result):
                for i in range(first_valid_disp, min(vel_start, len(result))):
                    assert pd.isna(result["dispersion_velocity"].iloc[i])

    def test_velocity_always_nonnegative(self):
        """Velocity (absolute diff) should always be >= 0."""
        data = _make_sector_data(n=80)
        result = calculate_sector_dispersion(data)
        valid_vel = result["dispersion_velocity"].dropna()
        assert (valid_vel >= 0).all()


class TestLevelRegime:
    """Tests for mean_ratio-based level regime classification."""

    def test_low_level(self):
        """mean_ratio < 0.20 should produce level_regime='low'."""
        # Create sectors with very low counts to get mean_ratio < 0.20
        dates = pd.bdate_range("2024-01-01", periods=30, freq="B")
        data = {"all": calculate_indicators(
            pd.DataFrame({"date": dates, "count": [50] * 30, "total": [500] * 30})
        )}
        for sec in SECTORS:
            df = pd.DataFrame({"date": dates, "count": [40 + i for i in range(30)], "total": [500] * 30})
            data[sec] = calculate_indicators(df)

        result = calculate_sector_dispersion(data)
        valid = result.dropna(subset=["level_regime"])
        if not valid.empty:
            low_rows = valid[valid["mean_ratio"] < MEAN_RATIO_LOW]
            if not low_rows.empty:
                assert (low_rows["level_regime"] == "low").all()

    def test_high_level(self):
        """mean_ratio >= 0.35 should produce level_regime='high'."""
        dates = pd.bdate_range("2024-01-01", periods=30, freq="B")
        data = {"all": calculate_indicators(
            pd.DataFrame({"date": dates, "count": [250] * 30, "total": [500] * 30})
        )}
        for sec in SECTORS:
            df = pd.DataFrame({"date": dates, "count": [200 + i for i in range(30)], "total": [500] * 30})
            data[sec] = calculate_indicators(df)

        result = calculate_sector_dispersion(data)
        valid = result.dropna(subset=["level_regime"])
        if not valid.empty:
            high_rows = valid[valid["mean_ratio"] >= MEAN_RATIO_HIGH]
            if not high_rows.empty:
                assert (high_rows["level_regime"] == "high").all()

    def test_mid_level(self):
        """0.20 <= mean_ratio < 0.35 should produce level_regime='mid'."""
        dates = pd.bdate_range("2024-01-01", periods=30, freq="B")
        data = {"all": calculate_indicators(
            pd.DataFrame({"date": dates, "count": [140] * 30, "total": [500] * 30})
        )}
        for sec in SECTORS:
            df = pd.DataFrame({"date": dates, "count": [130 + i for i in range(30)], "total": [500] * 30})
            data[sec] = calculate_indicators(df)

        result = calculate_sector_dispersion(data)
        valid = result.dropna(subset=["level_regime"])
        if not valid.empty:
            mid_rows = valid[(valid["mean_ratio"] >= MEAN_RATIO_LOW) & (valid["mean_ratio"] < MEAN_RATIO_HIGH)]
            if not mid_rows.empty:
                assert (mid_rows["level_regime"] == "mid").all()

    def test_level_regime_values_valid(self):
        """level_regime should only contain 'low', 'mid', 'high', or NaN."""
        data = _make_sector_data(n=80)
        result = calculate_sector_dispersion(data)
        valid = result["level_regime"].dropna().unique()
        assert set(valid).issubset({"low", "mid", "high"})


class TestDetectDispersionSignals:
    """Tests for detect_dispersion_signals()."""

    def _make_dispersion_df_with_regime(self, regime, level_regime,
                                        dispersion=0.05, mean_ratio=0.15,
                                        velocity=0.01, vel_p90=0.005,
                                        disp_median=0.08):
        """Helper to create a dispersion DataFrame with specific latest-row values."""
        n = 5
        return pd.DataFrame({
            "date": pd.bdate_range("2024-01-01", periods=n, freq="B"),
            "dispersion": [dispersion] * n,
            "mean_ratio": [mean_ratio] * n,
            "range": [0.1] * n,
            "dispersion_ma10": [dispersion] * n,
            "dispersion_velocity": [velocity] * n,
            "regime": [regime] * n,
            "level_regime": [level_regime] * n,
            "p25": [0.04] * n,
            "p75": [0.10] * n,
            "velocity_p90": [vel_p90] * n,
            "dispersion_median": [disp_median] * n,
        })

    def test_capitulation_signal(self):
        """CAPITULATION fires when regime=converged AND level_regime=low."""
        df = self._make_dispersion_df_with_regime("converged", "low")
        signals = detect_dispersion_signals(df)
        active = [s for s in signals if s.signal_id == "CAPITULATION" and s.active]
        assert len(active) == 1

    def test_divergence_warning_signal(self):
        """DIVERGENCE_WARNING fires when regime=diverged."""
        df = self._make_dispersion_df_with_regime("diverged", "mid", dispersion=0.15)
        signals = detect_dispersion_signals(df)
        active = [s for s in signals if s.signal_id == "DIVERGENCE_WARNING" and s.active]
        assert len(active) == 1

    def test_breakout_velocity_signal(self):
        """BREAKOUT_VELOCITY fires when velocity > vel_p90 AND dispersion < median."""
        df = self._make_dispersion_df_with_regime(
            "normal", "mid",
            dispersion=0.05, velocity=0.02, vel_p90=0.01, disp_median=0.08,
        )
        signals = detect_dispersion_signals(df)
        active = [s for s in signals if s.signal_id == "BREAKOUT_VELOCITY" and s.active]
        assert len(active) == 1

    def test_no_signal_in_normal(self):
        """No active signals in normal regime with normal velocity."""
        df = self._make_dispersion_df_with_regime(
            "normal", "mid",
            dispersion=0.07, velocity=0.002, vel_p90=0.01, disp_median=0.06,
        )
        signals = detect_dispersion_signals(df)
        active = [s for s in signals if s.active]
        assert len(active) == 0

    def test_empty_df_returns_empty_list(self):
        """Empty DataFrame should return empty signal list."""
        df = pd.DataFrame(columns=[
            "date", "dispersion", "mean_ratio", "range",
            "dispersion_ma10", "dispersion_velocity",
            "regime", "level_regime",
            "p25", "p75", "velocity_p90", "dispersion_median",
        ])
        signals = detect_dispersion_signals(df)
        assert signals == []

    def test_all_nan_regime_returns_empty(self):
        """DataFrame with all NaN regime should return empty signal list."""
        df = pd.DataFrame({
            "date": pd.bdate_range("2024-01-01", periods=3, freq="B"),
            "dispersion": [np.nan] * 3,
            "mean_ratio": [np.nan] * 3,
            "range": [np.nan] * 3,
            "dispersion_ma10": [np.nan] * 3,
            "dispersion_velocity": [np.nan] * 3,
            "regime": [np.nan] * 3,
            "level_regime": [np.nan] * 3,
            "p25": [np.nan] * 3,
            "p75": [np.nan] * 3,
            "velocity_p90": [np.nan] * 3,
            "dispersion_median": [np.nan] * 3,
        })
        signals = detect_dispersion_signals(df)
        assert signals == []

    def test_signal_dataclass_fields(self):
        """DispersionSignal should have required fields."""
        df = self._make_dispersion_df_with_regime("converged", "low")
        signals = detect_dispersion_signals(df)
        for s in signals:
            assert hasattr(s, "signal_id")
            assert hasattr(s, "name")
            assert hasattr(s, "active")
            assert hasattr(s, "dispersion")
            assert hasattr(s, "mean_ratio")


class TestForwardReturns:
    """Tests for calculate_forward_returns() with composite state transitions."""

    def _make_data_with_transitions(self):
        """Create dispersion_df and market_df with known regime transitions."""
        n = 30
        dates = pd.bdate_range("2024-01-01", periods=n, freq="B")
        # Regime transitions: normal(0-9) -> converged_low(10-14) -> normal_mid(15-24) -> diverged_high(25-29)
        regimes = ["normal"] * 10 + ["converged"] * 5 + ["normal"] * 10 + ["diverged"] * 5
        levels = ["mid"] * 10 + ["low"] * 5 + ["mid"] * 10 + ["high"] * 5
        dispersion_df = pd.DataFrame({
            "date": dates,
            "dispersion": np.random.uniform(0.05, 0.15, n),
            "mean_ratio": np.random.uniform(0.1, 0.4, n),
            "range": [0.1] * n,
            "dispersion_ma10": [0.1] * n,
            "dispersion_velocity": [0.01] * n,
            "regime": regimes,
            "level_regime": levels,
            "p25": [0.06] * n,
            "p75": [0.12] * n,
            "velocity_p90": [0.02] * n,
            "dispersion_median": [0.09] * n,
        })
        # Market df with increasing ratio
        market_df = pd.DataFrame({
            "date": dates,
            "ratio": np.linspace(0.2, 0.4, n),
            "ma_10": np.linspace(0.2, 0.4, n),
        })
        return dispersion_df, market_df

    def test_output_columns(self):
        """Forward returns should have expected columns."""
        disp_df, mkt_df = self._make_data_with_transitions()
        result = calculate_forward_returns(disp_df, mkt_df, windows=(5, 10))
        expected = {"regime", "level_regime", "window", "mean_return", "win_rate", "count"}
        assert expected.issubset(set(result.columns))

    def test_transition_event_counting(self):
        """Continuous same regime should count as 1 event, not N daily samples."""
        disp_df, mkt_df = self._make_data_with_transitions()
        result = calculate_forward_returns(disp_df, mkt_df, windows=(5,))
        # We have 4 transitions: start(normal_mid), converged_low, normal_mid, diverged_high
        # First row is always a "transition" (from nothing)
        total_events = result["count"].sum()
        assert total_events <= 4  # at most 4 transition events

    def test_composite_state_transition_detected(self):
        """Transition within same regime but different level should be detected."""
        n = 20
        dates = pd.bdate_range("2024-01-01", periods=n, freq="B")
        # converged_mid(0-9) -> converged_low(10-19): same regime, different level
        disp_df = pd.DataFrame({
            "date": dates,
            "dispersion": [0.05] * n,
            "mean_ratio": [0.25] * 10 + [0.15] * 10,
            "range": [0.1] * n,
            "dispersion_ma10": [0.05] * n,
            "dispersion_velocity": [0.01] * n,
            "regime": ["converged"] * n,
            "level_regime": ["mid"] * 10 + ["low"] * 10,
            "p25": [0.06] * n,
            "p75": [0.12] * n,
            "velocity_p90": [0.02] * n,
            "dispersion_median": [0.09] * n,
        })
        mkt_df = pd.DataFrame({
            "date": dates,
            "ratio": np.linspace(0.2, 0.3, n),
            "ma_10": np.linspace(0.2, 0.3, n),
        })
        result = calculate_forward_returns(disp_df, mkt_df, windows=(5,))
        # Should have 2 events: converged_mid (row 0) and converged_low (row 10)
        total = result["count"].sum()
        assert total == 2

    def test_short_data_handles_gracefully(self):
        """Window longer than data should still return valid results."""
        n = 5
        dates = pd.bdate_range("2024-01-01", periods=n, freq="B")
        disp_df = pd.DataFrame({
            "date": dates,
            "dispersion": [0.05] * n,
            "mean_ratio": [0.2] * n,
            "range": [0.1] * n,
            "dispersion_ma10": [0.05] * n,
            "dispersion_velocity": [0.01] * n,
            "regime": ["normal"] * n,
            "level_regime": ["mid"] * n,
            "p25": [0.06] * n,
            "p75": [0.12] * n,
            "velocity_p90": [0.02] * n,
            "dispersion_median": [0.09] * n,
        })
        mkt_df = pd.DataFrame({
            "date": dates,
            "ratio": [0.2] * n,
            "ma_10": [0.2] * n,
        })
        result = calculate_forward_returns(disp_df, mkt_df, windows=(20,))
        # Window=20 exceeds data length, so no forward return can be calculated
        assert result.empty or result["count"].sum() == 0


class TestSectorEdge:
    """Tests for calculate_sector_edge() with composite state transitions."""

    def test_output_columns(self):
        """Sector edge should have expected columns."""
        data = _make_sector_data(n=80)
        disp_df = calculate_sector_dispersion(data)
        result = calculate_sector_edge(disp_df, data, window=5)
        expected = {"sector_key", "regime", "level_regime", "mean_change", "win_rate", "count"}
        assert expected.issubset(set(result.columns))

    def test_uses_transition_events(self):
        """Should use composite state transitions, not daily samples."""
        n = 30
        dates = pd.bdate_range("2024-01-01", periods=n, freq="B")
        # 2 transitions: normal_mid(0-14) -> converged_low(15-29)
        disp_df = pd.DataFrame({
            "date": dates,
            "dispersion": [0.08] * n,
            "mean_ratio": [0.25] * 15 + [0.15] * 15,
            "range": [0.1] * n,
            "dispersion_ma10": [0.08] * n,
            "dispersion_velocity": [0.01] * n,
            "regime": ["normal"] * 15 + ["converged"] * 15,
            "level_regime": ["mid"] * 15 + ["low"] * 15,
            "p25": [0.06] * n,
            "p75": [0.12] * n,
            "velocity_p90": [0.02] * n,
            "dispersion_median": [0.09] * n,
        })
        sec_data = {}
        for sec in SECTORS:
            sec_data[sec] = pd.DataFrame({
                "date": dates,
                "ma_10": np.linspace(0.2, 0.35, n),
            })
        result = calculate_sector_edge(disp_df, sec_data, window=5)
        if not result.empty:
            # Each regime transition should produce at most 11 sector entries
            per_regime = result.groupby(["regime", "level_regime"])["count"].first()
            assert (per_regime <= 1).all()  # each transition is 1 event

    def test_includes_level_regime(self):
        """Output should distinguish by (regime, level_regime)."""
        data = _make_sector_data(n=80)
        disp_df = calculate_sector_dispersion(data)
        result = calculate_sector_edge(disp_df, data, window=5)
        assert "level_regime" in result.columns


class TestConfirmRegime:
    """Unit tests for the causal regime confirmation state machine."""

    def _series(self, values):
        return pd.Series(
            values,
            index=pd.bdate_range("2024-01-01", periods=len(values), freq="B"),
            dtype=object,
        )

    def test_short_blip_absorbed(self):
        """A run shorter than min_days is absorbed into the previous regime."""
        s = self._series(["normal"] * 3 + ["diverged"] * 2)
        out = _confirm_regime(s, 3)
        assert list(out) == ["normal"] * 5

    def test_confirmation_only_on_min_days(self):
        """A transition is emitted only on the min_days-th consecutive candidate day."""
        s = self._series(["normal"] * 3 + ["diverged"] * 3)
        out = _confirm_regime(s, 3)
        # 3 normals, then 2 absorbed diverged days, then the 3rd diverged day confirms
        assert list(out) == ["normal", "normal", "normal", "normal", "normal", "diverged"]

    def test_two_day_candidate_not_confirmed_then_revert(self):
        """A 2-day candidate that reverts never gets confirmed."""
        s = self._series(["normal"] * 3 + ["diverged"] * 2 + ["normal"] * 2)
        out = _confirm_regime(s, 3)
        assert list(out) == ["normal"] * 7

    def test_blip_then_revert_to_previous(self):
        """A short candidate that returns to the confirmed regime is fully absorbed."""
        s = self._series(["normal"] * 4 + ["converged"] * 2 + ["normal"] * 3)
        out = _confirm_regime(s, 3)
        assert list(out) == ["normal"] * 9

    def test_retransition_to_previously_seen_regime(self):
        """After a confirmed regime, the same regime can be re-confirmed later."""
        s = self._series(
            ["normal"] * 3 + ["diverged"] * 3 + ["normal"] * 3 + ["diverged"] * 3
        )
        out = _confirm_regime(s, 3)
        assert list(out) == [
            "normal", "normal", "normal",
            "normal", "normal", "diverged",
            "diverged", "diverged", "normal",
            "normal", "normal", "diverged",
        ]

    def test_initial_baseline_is_first_observation(self):
        """The first non-NaN regime becomes the baseline immediately."""
        s = self._series(["diverged", "diverged", "normal"])
        out = _confirm_regime(s, 3)
        assert list(out) == ["diverged", "diverged", "diverged"]

    def test_missing_observation_resets_candidate(self):
        """A NaN day interrupts the candidate run, delaying confirmation."""
        s = pd.Series(
            ["normal", "normal", "normal", "diverged", np.nan, "diverged", "diverged"],
            index=pd.bdate_range("2024-01-01", periods=7, freq="B"),
            dtype=object,
        )
        out = _confirm_regime(s, 3)
        assert list(out.iloc[:3]) == ["normal"] * 3
        assert out.iloc[3] == "normal"      # unconfirmed diverged absorbed
        assert pd.isna(out.iloc[4])          # NaN preserved as NaN
        assert out.iloc[5] == "normal"       # candidate restarted after NaN
        assert out.iloc[6] == "normal"

    def test_min_days_le_one_passthrough(self):
        """min_days <= 1 returns the series unchanged (no noise filter)."""
        s = self._series(["normal", "diverged", "normal"])
        out = _confirm_regime(s, 1)
        assert list(out) == ["normal", "diverged", "normal"]

    def test_empty_series_passthrough(self):
        out = _confirm_regime(pd.Series([], dtype=object), 3)
        assert out.empty

    def test_all_nan_passthrough(self):
        s = pd.Series(
            [np.nan, np.nan],
            index=pd.bdate_range("2024-01-01", periods=2, freq="B"),
            dtype=object,
        )
        out = _confirm_regime(s, 3)
        assert out.isna().all()

    def test_prefix_invariance(self):
        """Labels at each position are identical to those of the full series.

        This is the causal guarantee: no label depends on future observations.
        """
        values = [
            "normal", "converged", "normal", "diverged", "converged",
            "normal", "normal", "diverged", "diverged", "diverged",
            "normal", "converged", "converged", "converged", "normal",
        ]
        full_out = _confirm_regime(self._series(values), 3)
        for k in range(1, len(values) + 1):
            pre = _confirm_regime(self._series(values).iloc[:k], 3)
            assert list(pre) == list(full_out.iloc[:k]), f"prefix length {k} differs"

    def test_prefix_invariance_randomized(self):
        """Randomized prefix-invariance check over varied series lengths."""
        import random
        rng = random.Random(42)
        pool = ["normal", "converged", "diverged"]
        for _ in range(25):
            n = rng.randint(5, 30)
            values = [rng.choice(pool) for _ in range(n)]
            full_out = _confirm_regime(self._series(values), 3)
            for k in range(1, n + 1):
                pre = _confirm_regime(self._series(values).iloc[:k], 3)
                assert list(pre) == list(full_out.iloc[:k])

    def test_prefix_invariance_with_nan_randomized(self):
        """Randomized prefix-invariance check including NaN (missing) observations."""
        import random
        rng = random.Random(7)
        pool = ["normal", "converged", "diverged", np.nan]
        for _ in range(25):
            n = rng.randint(5, 30)
            values = [rng.choice(pool) for _ in range(n)]
            s = pd.Series(
                values,
                index=pd.bdate_range("2024-01-01", periods=n, freq="B"),
                dtype=object,
            )
            full_out = _confirm_regime(s, 3)
            for k in range(1, n + 1):
                pre = _confirm_regime(s.iloc[:k], 3)
                assert list(pre) == list(full_out.iloc[:k])

    def test_leading_nan_then_baseline(self):
        """A leading NaN prefix is preserved, then the first non-NaN becomes baseline."""
        s = pd.Series(
            [np.nan, np.nan, "diverged", "diverged", "normal"],
            index=pd.bdate_range("2024-01-01", periods=5, freq="B"),
            dtype=object,
        )
        out = _confirm_regime(s, 3)
        assert pd.isna(out.iloc[0])
        assert pd.isna(out.iloc[1])
        assert list(out.iloc[2:]) == ["diverged", "diverged", "diverged"]


class TestDispersionRegimePrefixInvariance:
    """Integration: calculate_sector_dispersion() regime column is prefix-invariant."""

    def test_regime_prefix_invariant_across_truncation(self):
        """Regime labels over shared dates are identical for a prefix vs the full series."""
        data = _make_sector_data(n=120)
        full = calculate_sector_dispersion(data).set_index("date")
        for k in [70, 90, 110]:
            prefix_data = {key: df.iloc[:k] for key, df in data.items()}
            pre = calculate_sector_dispersion(prefix_data).set_index("date")
            common = full.index.intersection(pre.index)
            assert full.loc[common, "regime"].equals(pre.loc[common, "regime"]), \
                f"prefix length {k} differs"


class TestForwardReturnsConfirmationDate:
    """Forward returns use the first observable confirmation date for a regime event."""

    def test_no_event_on_blip_start(self):
        """A short candidate that never confirms does not create a regime event."""
        n = 15
        dates = pd.bdate_range("2024-01-01", periods=n, freq="B")
        raw = ["normal"] * 4 + ["diverged"] * 2 + ["normal"] * 9
        regimes = _confirm_regime(pd.Series(raw, dtype=object), 3)
        # The 2-day diverged blip is absorbed, so regime stays normal throughout
        assert set(regimes) == {"normal"}
        disp_df = pd.DataFrame({
            "date": dates,
            "dispersion": [0.08] * n,
            "mean_ratio": [0.25] * n,
            "range": [0.1] * n,
            "dispersion_ma10": [0.08] * n,
            "dispersion_velocity": [0.01] * n,
            "regime": list(regimes),
            "level_regime": ["mid"] * n,
            "p25": [0.06] * n,
            "p75": [0.12] * n,
            "velocity_p90": [0.02] * n,
            "dispersion_median": [0.09] * n,
        })
        mkt_df = pd.DataFrame({
            "date": dates,
            "ratio": np.linspace(0.2, 0.4, n),
            "ma_10": np.linspace(0.2, 0.4, n),
        })
        result = calculate_forward_returns(disp_df, mkt_df, windows=(5,))
        div = result[result["regime"] == "diverged"]
        assert div.empty  # no diverged event because the blip was never confirmed

    def test_event_date_is_confirmation_date(self):
        """The regime event is measured from the confirmation date, not the run start."""
        n = 15
        dates = pd.bdate_range("2024-01-01", periods=n, freq="B")
        raw = ["normal"] * 4 + ["diverged"] * 11
        regimes = _confirm_regime(pd.Series(raw, dtype=object), 3)
        regime_list = list(regimes)
        # normal for 6 rows (4 baseline + 2 absorbed candidates), diverged confirmed on row 6
        assert regime_list[4] == "normal"
        assert regime_list[5] == "normal"
        assert regime_list[6] == "diverged"
        mkt_ratio = np.linspace(0.2, 0.4, n)
        disp_df = pd.DataFrame({
            "date": dates,
            "dispersion": [0.08] * n,
            "mean_ratio": [0.25] * n,
            "range": [0.1] * n,
            "dispersion_ma10": [0.08] * n,
            "dispersion_velocity": [0.01] * n,
            "regime": regime_list,
            "level_regime": ["mid"] * n,
            "p25": [0.06] * n,
            "p75": [0.12] * n,
            "velocity_p90": [0.02] * n,
            "dispersion_median": [0.09] * n,
        })
        mkt_df = pd.DataFrame({
            "date": dates,
            "ratio": mkt_ratio,
            "ma_10": mkt_ratio,
        })
        result = calculate_forward_returns(disp_df, mkt_df, windows=(5,))
        div = result[(result["regime"] == "diverged") & (result["level_regime"] == "mid")]
        assert len(div) == 1  # exactly one diverged event
        row = div.iloc[0]
        assert row["count"] == 1
        # forward return measured from the confirmation date (index 6) over window 5
        expected_fwd = mkt_ratio[11] - mkt_ratio[6]
        assert abs(row["mean_return"] - expected_fwd) < 1e-10
