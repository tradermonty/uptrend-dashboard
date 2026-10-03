"""Derived indicator calculations for uptrend dashboard."""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.signal import find_peaks

from src.constants import (
    DISPERSION_CONVERGED_FALLBACK,
    DISPERSION_DIVERGED_FALLBACK,
    DISPERSION_MIN_HISTORY,
    DISPERSION_MIN_REGIME_DAYS,
    DISPERSION_VELOCITY_WINDOW,
    LOWER_THRESHOLD,
    MA_PERIOD,
    MEAN_RATIO_HIGH,
    MEAN_RATIO_LOW,
    PEAK_DISTANCE,
    PEAK_PROMINENCE,
    UPPER_THRESHOLD,
)

logger = logging.getLogger(__name__)


@dataclass
class IndicatorConfig:
    """Configuration for indicator calculations."""

    ma_period: int = MA_PERIOD
    upper_threshold: float = UPPER_THRESHOLD
    lower_threshold: float = LOWER_THRESHOLD
    peak_distance: int = PEAK_DISTANCE
    peak_prominence: float = PEAK_PROMINENCE


@dataclass
class DispersionSignal:
    """A dispersion-based market signal."""

    signal_id: str
    name: str
    active: bool
    dispersion: float
    mean_ratio: float


def _calc_ratio(df: pd.DataFrame) -> pd.Series:
    """Calculate ratio = count / total, handling zero total and NaN values."""
    count = df["count"].fillna(0)
    total = df["total"].fillna(0)
    return pd.Series(
        np.where(total == 0, 0.0, count / total),
        index=df.index,
    )


def _calc_ma(ratio: pd.Series, period: int = 10) -> pd.Series:
    """Calculate simple moving average of ratio."""
    return ratio.rolling(window=period).mean()


def _calc_slope(ma: pd.Series) -> pd.Series:
    """Calculate slope as 1-day difference of MA."""
    return ma.diff()


def _calc_trend(ratio: pd.Series, slope: pd.Series) -> Tuple[pd.Series, pd.Series]:
    """Split ratio into trend_up and trend_down based on slope.

    Returns:
        (trend_up, trend_down) where:
        - trend_up has ratio values where slope > 0, NaN otherwise
        - trend_down has ratio values where slope <= 0, NaN otherwise
        - Both are NaN where slope is NaN
    """
    trend_up = pd.Series(np.nan, index=ratio.index)
    trend_down = pd.Series(np.nan, index=ratio.index)

    up_mask = slope > 0
    down_mask = slope.notna() & (slope <= 0)

    trend_up[up_mask] = ratio[up_mask]
    trend_down[down_mask] = ratio[down_mask]

    return trend_up, trend_down


def _detect_peaks_troughs(
    ma: pd.Series, distance: int, prominence: float
) -> Tuple[np.ndarray, np.ndarray]:
    """Detect peaks (tops) and troughs (bottoms) in a moving average series.

    Args:
        ma: Moving average series (may contain leading NaNs).
        distance: Minimum distance between peaks in data points.
        prominence: Minimum prominence for peak detection.

    Returns:
        (peak_indices, trough_indices) mapped back to the original series index.
    """
    valid = ma.dropna()
    if len(valid) == 0:
        return np.array([], dtype=int), np.array([], dtype=int)

    offset = ma.index.get_loc(valid.index[0])
    if isinstance(offset, slice):
        offset = offset.start

    peaks, _ = find_peaks(valid.values, distance=distance, prominence=prominence)
    troughs, _ = find_peaks(-valid.values, distance=distance, prominence=prominence)

    return peaks + offset, troughs + offset


def calculate_indicators(
    df: pd.DataFrame, config: Optional[IndicatorConfig] = None
) -> pd.DataFrame:
    """Calculate all derived indicators from raw data.

    Args:
        df: DataFrame with columns (date, count, total).
        config: Optional configuration for MA period and thresholds.

    Returns:
        DataFrame with added columns: ratio, ma_10, slope, trend_up, trend_down,
        upper, lower, is_peak, is_trough.
    """
    if config is None:
        config = IndicatorConfig()

    result = df.reset_index(drop=True).copy()
    ratio = pd.Series(_calc_ratio(result), index=result.index)
    result["ratio"] = ratio
    result["ma_10"] = _calc_ma(ratio, period=config.ma_period)
    result["slope"] = _calc_slope(result["ma_10"])
    result["trend_up"], result["trend_down"] = _calc_trend(ratio, result["slope"])
    result["upper"] = config.upper_threshold
    result["lower"] = config.lower_threshold

    peak_idx, trough_idx = _detect_peaks_troughs(
        result["ma_10"], config.peak_distance, config.peak_prominence
    )
    result["is_peak"] = False
    result["is_trough"] = False
    if len(peak_idx) > 0:
        result.iloc[peak_idx, result.columns.get_loc("is_peak")] = True
    if len(trough_idx) > 0:
        result.iloc[trough_idx, result.columns.get_loc("is_trough")] = True

    return result


def _confirm_regime(regime: pd.Series, min_days: int) -> pd.Series:
    """Causally confirm regime transitions using a sequential state machine.

    Each row is classified based only on observations up to and including that
    row (no lookahead). A regime change is emitted only once the new regime has
    been observed for min_days consecutive valid days; before that the row keeps
    the previous confirmed regime, absorbing short blips (noise). Because the
    output at any row depends only on data up to that row, the labels are
    prefix-invariant: appending future history never relabels an earlier row.

    Missing (NaN) observations reset the in-progress candidate run (a missing
    day provides no evidence), are emitted as NaN, and do not extend a run;
    the current confirmed regime is retained.

    Args:
        regime: Regime label series, indexed ascending by date.
        min_days: Minimum consecutive valid days to confirm a regime change.

    Returns:
        New regime series with the same index.
    """
    if regime.dropna().empty or min_days <= 1:
        return regime

    result = pd.Series(np.nan, index=regime.index, dtype=object)
    confirmed = None
    candidate = None
    candidate_count = 0

    for i, r in enumerate(regime.values):
        if pd.isna(r):
            result.iloc[i] = np.nan
            candidate = None
            candidate_count = 0
            continue

        if confirmed is None:
            confirmed = r
            result.iloc[i] = r
            continue

        if r == confirmed:
            candidate = None
            candidate_count = 0
            result.iloc[i] = confirmed
            continue

        if r == candidate:
            candidate_count += 1
        else:
            candidate = r
            candidate_count = 1

        if candidate_count >= min_days:
            confirmed = candidate
            candidate = None
            candidate_count = 0
            result.iloc[i] = confirmed
        else:
            result.iloc[i] = confirmed

    return result


def calculate_sector_dispersion(
    sector_data: Dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Calculate cross-sectional dispersion of sector uptrend ratios.

    Args:
        sector_data: Dict mapping worksheet keys to DataFrames with 'ma_10'.
            Only sec_* keys are used; 'all' and ind_* keys are ignored.

    Returns:
        DataFrame with columns: date, dispersion, mean_ratio, range,
        dispersion_ma10, dispersion_velocity, regime, level_regime,
        p25, p75, velocity_p90, dispersion_median.
        Empty DataFrame if fewer than 2 sectors.
    """
    output_cols = [
        "date", "dispersion", "mean_ratio", "range",
        "dispersion_ma10", "dispersion_velocity",
        "regime", "level_regime",
        "p25", "p75", "velocity_p90", "dispersion_median",
    ]

    # Filter to sec_* keys only
    sec_keys = [k for k in sector_data if k.startswith("sec_")]
    if len(sec_keys) < 2:
        return pd.DataFrame(columns=output_cols)

    # Build cross-sectional matrix: date x sector ma_10
    aligned = {}
    for key in sec_keys:
        df = sector_data[key]
        if df.empty or "ma_10" not in df.columns:
            continue
        s = df.set_index("date")["ma_10"]
        aligned[key] = s

    if len(aligned) < 2:
        return pd.DataFrame(columns=output_cols)

    matrix = pd.DataFrame(aligned)
    # Drop rows where ALL sectors are NaN
    matrix = matrix.dropna(how="all")

    # Drop the last row if not all sectors reported (partial day data)
    n_sectors = len(aligned)
    if not matrix.empty and matrix.iloc[-1].count() < n_sectors:
        matrix = matrix.iloc[:-1]

    if matrix.empty:
        return pd.DataFrame(columns=output_cols)

    # Cross-sectional statistics per day
    valid_count = matrix.count(axis=1)  # non-NaN sectors per day
    dispersion = matrix.std(axis=1, ddof=0)
    mean_ratio = matrix.mean(axis=1)
    range_val = matrix.max(axis=1) - matrix.min(axis=1)

    # Valid mask: need at least 2 non-NaN sectors for meaningful std dev,
    # otherwise ddof=0 returns 0 for a single value (false convergence)
    valid = dispersion.notna() & mean_ratio.notna() & (valid_count >= 2)

    # Smoothed dispersion
    dispersion_ma10 = _calc_ma(dispersion, period=10)

    # Velocity: absolute 3-day change
    dispersion_velocity = dispersion.diff(DISPERSION_VELOCITY_WINDOW).abs()

    # Expanding window percentiles (only on valid rows)
    valid_disp = dispersion.where(valid)
    p25 = valid_disp.expanding(min_periods=DISPERSION_MIN_HISTORY).quantile(0.25)
    p75 = valid_disp.expanding(min_periods=DISPERSION_MIN_HISTORY).quantile(0.75)
    dispersion_median = valid_disp.expanding(min_periods=DISPERSION_MIN_HISTORY).quantile(0.5)
    velocity_p90 = dispersion_velocity.where(valid).expanding(
        min_periods=DISPERSION_MIN_HISTORY
    ).quantile(0.90)

    # Regime classification
    regime = pd.Series(np.nan, index=matrix.index, dtype=object)
    thresh_low = p25.where(p25.notna(), DISPERSION_CONVERGED_FALLBACK)
    thresh_high = p75.where(p75.notna(), DISPERSION_DIVERGED_FALLBACK)

    converged_mask = valid & (dispersion < thresh_low)
    diverged_mask = valid & (dispersion > thresh_high)
    normal_mask = valid & ~converged_mask & ~diverged_mask

    regime[converged_mask] = "converged"
    regime[diverged_mask] = "diverged"
    regime[normal_mask] = "normal"

    # Hysteresis: confirm regime transitions only after MIN_REGIME_DAYS
    # consecutive valid days, absorbing shorter blips into the previous
    # confirmed regime. Causal (no lookahead): labels are prefix-invariant.
    regime = _confirm_regime(regime, DISPERSION_MIN_REGIME_DAYS)

    # Level regime classification
    level_regime = pd.Series(np.nan, index=matrix.index, dtype=object)
    level_regime[valid & (mean_ratio < MEAN_RATIO_LOW)] = "low"
    level_regime[valid & (mean_ratio >= MEAN_RATIO_LOW) & (mean_ratio < MEAN_RATIO_HIGH)] = "mid"
    level_regime[valid & (mean_ratio >= MEAN_RATIO_HIGH)] = "high"

    result = pd.DataFrame({
        "date": matrix.index,
        "dispersion": dispersion.values,
        "mean_ratio": mean_ratio.values,
        "range": range_val.values,
        "dispersion_ma10": dispersion_ma10.values,
        "dispersion_velocity": dispersion_velocity.values,
        "regime": regime.values,
        "level_regime": level_regime.values,
        "p25": p25.values,
        "p75": p75.values,
        "velocity_p90": velocity_p90.values,
        "dispersion_median": dispersion_median.values,
    })

    return result


def detect_dispersion_signals(
    dispersion_df: pd.DataFrame,
) -> List[DispersionSignal]:
    """Detect active dispersion signals from the latest valid row.

    Args:
        dispersion_df: Output of calculate_sector_dispersion().

    Returns:
        List of DispersionSignal. Empty if no valid data.
    """
    if dispersion_df.empty:
        return []

    valid = dispersion_df.dropna(subset=["regime", "level_regime"])
    if valid.empty:
        return []

    latest = valid.iloc[-1]
    regime = latest["regime"]
    level = latest["level_regime"]
    disp = float(latest["dispersion"])
    mean_r = float(latest["mean_ratio"])
    vel = latest.get("dispersion_velocity")
    vel_p90 = latest.get("velocity_p90")
    disp_med = latest.get("dispersion_median")

    signals = []

    # CAPITULATION: converged + low
    signals.append(DispersionSignal(
        signal_id="CAPITULATION",
        name="Capitulation",
        active=(regime == "converged" and level == "low"),
        dispersion=disp,
        mean_ratio=mean_r,
    ))

    # DIVERGENCE_WARNING: diverged
    signals.append(DispersionSignal(
        signal_id="DIVERGENCE_WARNING",
        name="Divergence Warning",
        active=(regime == "diverged"),
        dispersion=disp,
        mean_ratio=mean_r,
    ))

    # BREAKOUT_VELOCITY: velocity > p90 and dispersion < median
    breakout_active = False
    if pd.notna(vel) and pd.notna(vel_p90) and pd.notna(disp_med):
        breakout_active = (vel > vel_p90) and (disp < disp_med)
    signals.append(DispersionSignal(
        signal_id="BREAKOUT_VELOCITY",
        name="Breakout Velocity",
        active=breakout_active,
        dispersion=disp,
        mean_ratio=mean_r,
    ))

    return signals


def calculate_forward_returns(
    dispersion_df: pd.DataFrame,
    market_df: pd.DataFrame,
    windows: Tuple[int, ...] = (5, 10, 20),
) -> pd.DataFrame:
    """Calculate forward returns by regime using composite state transition events.

    Only counts the first day of each (regime, level_regime) transition as an event.

    Args:
        dispersion_df: Output of calculate_sector_dispersion().
        market_df: DataFrame with 'date' and 'ratio' columns (e.g., all_data["all"]).
        windows: Forward windows in trading days.

    Returns:
        DataFrame with columns: regime, level_regime, window, mean_return, win_rate, count.
    """
    output_cols = ["regime", "level_regime", "window", "mean_return", "win_rate", "count"]

    if dispersion_df.empty or market_df.empty:
        return pd.DataFrame(columns=output_cols)

    valid = dispersion_df.dropna(subset=["regime", "level_regime"]).copy()
    if valid.empty:
        return pd.DataFrame(columns=output_cols)

    # Composite state for transition detection
    valid = valid.copy()
    valid["_composite"] = valid["regime"].astype(str) + "_" + valid["level_regime"].astype(str)
    transitions = valid[valid["_composite"] != valid["_composite"].shift(1)]

    if transitions.empty:
        return pd.DataFrame(columns=output_cols)

    # Align market ratio by date
    mkt = market_df.set_index("date")["ratio"] if "date" in market_df.columns else market_df["ratio"]

    rows = []
    for w in windows:
        for _, event in transitions.iterrows():
            event_date = event["date"]
            if event_date not in mkt.index:
                continue
            event_idx = mkt.index.get_loc(event_date)
            fwd_idx = event_idx + w
            if fwd_idx >= len(mkt):
                continue
            fwd_return = mkt.iloc[fwd_idx] - mkt.iloc[event_idx]
            rows.append({
                "regime": event["regime"],
                "level_regime": event["level_regime"],
                "window": w,
                "forward_return": fwd_return,
            })

    if not rows:
        return pd.DataFrame(columns=output_cols)

    detail = pd.DataFrame(rows)
    result = detail.groupby(["regime", "level_regime", "window"]).agg(
        mean_return=("forward_return", "mean"),
        win_rate=("forward_return", lambda x: (x > 0).mean()),
        count=("forward_return", "count"),
    ).reset_index()

    return result


def calculate_sector_edge(
    dispersion_df: pd.DataFrame,
    sector_data: Dict[str, pd.DataFrame],
    window: int = 10,
) -> pd.DataFrame:
    """Calculate sector-level performance after regime transitions.

    Args:
        dispersion_df: Output of calculate_sector_dispersion().
        sector_data: Dict mapping sector keys to DataFrames with 'date' and 'ma_10'.
        window: Forward window in trading days.

    Returns:
        DataFrame with columns: sector_key, regime, level_regime, mean_change, win_rate, count.
    """
    output_cols = ["sector_key", "regime", "level_regime", "mean_change", "win_rate", "count"]

    if dispersion_df.empty:
        return pd.DataFrame(columns=output_cols)

    valid = dispersion_df.dropna(subset=["regime", "level_regime"]).copy()
    if valid.empty:
        return pd.DataFrame(columns=output_cols)

    valid["_composite"] = valid["regime"].astype(str) + "_" + valid["level_regime"].astype(str)
    transitions = valid[valid["_composite"] != valid["_composite"].shift(1)]

    if transitions.empty:
        return pd.DataFrame(columns=output_cols)

    sec_keys = [k for k in sector_data if k.startswith("sec_")]

    rows = []
    for sec_key in sec_keys:
        sec_df = sector_data[sec_key]
        if sec_df.empty or "ma_10" not in sec_df.columns:
            continue
        sec_ma = sec_df.set_index("date")["ma_10"] if "date" in sec_df.columns else sec_df["ma_10"]

        for _, event in transitions.iterrows():
            event_date = event["date"]
            if event_date not in sec_ma.index:
                continue
            event_idx = sec_ma.index.get_loc(event_date)
            fwd_idx = event_idx + window
            if fwd_idx >= len(sec_ma):
                continue
            if pd.isna(sec_ma.iloc[event_idx]) or pd.isna(sec_ma.iloc[fwd_idx]):
                continue
            change = sec_ma.iloc[fwd_idx] - sec_ma.iloc[event_idx]
            rows.append({
                "sector_key": sec_key,
                "regime": event["regime"],
                "level_regime": event["level_regime"],
                "change": change,
            })

    if not rows:
        return pd.DataFrame(columns=output_cols)

    detail = pd.DataFrame(rows)
    result = detail.groupby(["sector_key", "regime", "level_regime"]).agg(
        mean_change=("change", "mean"),
        win_rate=("change", lambda x: (x > 0).mean()),
        count=("change", "count"),
    ).reset_index()

    return result
