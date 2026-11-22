"""Data processing utilities for uptrend dashboard (v2)."""

import datetime
import logging
from dataclasses import dataclass, asdict
from typing import Dict, Optional
from urllib.parse import quote

import pandas as pd
import numpy as np
from dateutil.relativedelta import relativedelta

from src.constants import (
    DEFAULT_DISPLAY_YEARS,
    INDUSTRY_DISPLAY_NAMES,
    INDUSTRY_TO_SECTOR,
    LOWER_THRESHOLD,
    SECTOR_DISPLAY_NAMES,
    SECTOR_INDUSTRIES,
    UPPER_THRESHOLD,
)

logger = logging.getLogger(__name__)


STATUS_STYLES = {
    "Overbought": "color: #d62728",
    "Oversold": "color: #2ca02c",
    "Normal": "color: #1f77b4",
}


@dataclass
class MarketStatus:
    """Current market status extracted from the latest indicator data."""

    date: str
    ratio: float
    ratio_10ma: Optional[float]
    trend: str
    slope: float
    is_overbought: bool
    is_oversold: bool

    def __getitem__(self, key):
        return getattr(self, key)

    def __contains__(self, key):
        return key in self.__dataclass_fields__

    def keys(self):
        return self.__dataclass_fields__.keys()


def get_current_status(df: pd.DataFrame) -> MarketStatus:
    """Extract current status from the latest row of a calculated DataFrame."""
    if df.empty:
        logger.warning("get_current_status called with empty DataFrame")
        return MarketStatus(
            date="",
            ratio=0.0,
            ratio_10ma=None,
            trend="neutral",
            slope=None,
            is_overbought=False,
            is_oversold=False,
        )

    latest = df.iloc[-1]

    slope_val = latest.get("slope")
    if pd.isna(slope_val):
        trend = "neutral"
    elif pd.notna(latest.get("trend_up")):
        trend = "up"
    else:
        trend = "down"

    ratio = float(latest["ratio"])
    upper = float(latest["upper"]) if pd.notna(latest.get("upper")) else UPPER_THRESHOLD
    lower = float(latest["lower"]) if pd.notna(latest.get("lower")) else LOWER_THRESHOLD

    return MarketStatus(
        date=str(latest["date"].date()) if hasattr(latest["date"], "date") else str(latest["date"]),
        ratio=ratio,
        ratio_10ma=float(latest["ma_10"]) if pd.notna(latest.get("ma_10")) else None,
        trend=trend,
        slope=float(latest["slope"]) if pd.notna(latest.get("slope")) else None,
        is_overbought=ratio > upper,
        is_oversold=ratio < lower,
    )


def get_sector_display_name(worksheet_name: str) -> str:
    """Convert worksheet name like 'sec_basicmaterials' to 'Basic Materials'."""
    suffix = worksheet_name.replace("sec_", "", 1)
    return SECTOR_DISPLAY_NAMES.get(suffix, suffix.title())


def get_industry_display_name(worksheet_name: str) -> str:
    """Convert worksheet name like 'ind_semiconductors' to 'Semiconductors'."""
    suffix = worksheet_name.replace("ind_", "", 1)
    return INDUSTRY_DISPLAY_NAMES.get(suffix, suffix.title())


def get_sector_for_industry(industry_key: str) -> Optional[str]:
    """Return the parent sector key for an industry, or None if unknown."""
    return INDUSTRY_TO_SECTOR.get(industry_key)


_TREND_DISPLAY = {"up": "Up", "down": "Down", "neutral": "—"}


def _trend_label(trend: str) -> str:
    """Convert internal trend value to display label."""
    return _TREND_DISPLAY.get(trend, "—")


def _determine_market_status(status: MarketStatus) -> str:
    """Determine market status label from a MarketStatus object."""
    if status["is_overbought"]:
        return "Overbought"
    elif status["is_oversold"]:
        return "Oversold"
    return "Normal"


def build_sector_summary(all_data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Build a summary DataFrame of all sectors' latest status."""
    rows = []
    for name, df in all_data.items():
        if not name.startswith("sec_") or df.empty:
            continue
        status = get_current_status(df)
        rows.append(
            {
                "Sector": get_sector_display_name(name),
                "Ratio": status["ratio"],
                "10MA": status["ratio_10ma"],
                "Trend": _trend_label(status["trend"]),
                "Slope": status["slope"],
                "Status": _determine_market_status(status),
                "_key": name,
            }
        )

    if not rows:
        return pd.DataFrame(columns=["Sector", "Ratio", "10MA", "Trend", "Slope", "Status", "_key"])

    summary = pd.DataFrame(rows)
    summary = summary.sort_values("Ratio", ascending=False).reset_index(drop=True)
    return summary


def build_industry_summary(
    all_data: Dict[str, pd.DataFrame],
    sector_key: Optional[str] = None,
) -> pd.DataFrame:
    """Build a summary DataFrame of industries' latest status.

    Args:
        all_data: Dict mapping worksheet name to calculated DataFrame.
        sector_key: If given, only include industries in this sector.
    """
    if sector_key is not None:
        target_keys = set(SECTOR_INDUSTRIES.get(sector_key, []))
    else:
        target_keys = None

    rows = []
    for name, df in all_data.items():
        if not name.startswith("ind_") or df.empty:
            continue
        if target_keys is not None and name not in target_keys:
            continue
        status = get_current_status(df)
        rows.append(
            {
                "Industry": get_industry_display_name(name),
                "Ratio": status["ratio"],
                "10MA": status["ratio_10ma"],
                "Trend": _trend_label(status["trend"]),
                "Slope": status["slope"],
                "Status": _determine_market_status(status),
                "_key": name,
            }
        )

    if not rows:
        return pd.DataFrame(columns=["Industry", "Ratio", "10MA", "Trend", "Slope", "Status", "_key"])

    summary = pd.DataFrame(rows)
    summary = summary.sort_values("Ratio", ascending=False).reset_index(drop=True)
    return summary


def build_industry_summary_with_sector(
    all_data: Dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Build industry summary with Sector and Total columns for heatmap display.

    Args:
        all_data: Dict mapping worksheet name to calculated DataFrame.

    Returns:
        DataFrame with columns: Industry, Ratio, 10MA, Trend, Slope, Status, _key, Sector, Total.
    """
    expected_columns = ["Industry", "Ratio", "10MA", "Trend", "Slope", "Status", "_key", "Sector", "Total"]

    summary = build_industry_summary(all_data)
    if summary.empty:
        return pd.DataFrame(columns=expected_columns)

    # Add Sector column
    summary["Sector"] = summary["_key"].apply(
        lambda k: get_sector_display_name(get_sector_for_industry(k))
        if get_sector_for_industry(k) else "Unknown"
    )

    # Add Total column (latest total value per industry, min 1)
    totals = []
    for key in summary["_key"]:
        df = all_data.get(key)
        if df is not None and not df.empty:
            latest_total = int(df.iloc[-1]["total"])
            totals.append(max(1, latest_total))
        else:
            totals.append(1)
    summary["Total"] = totals

    return summary


def style_status_row(row):
    """Apply color styling to Trend and Status columns in a summary row."""
    styles = []
    for col in row.index:
        if col == "Trend":
            trend_colors = {"Up": "color: #00cc96", "Down": "color: #ef553b"}
            styles.append(trend_colors.get(row["Trend"], "color: #888888"))
        elif col == "Status":
            styles.append(STATUS_STYLES.get(row["Status"], ""))
        else:
            styles.append("")
    return styles


# Stored constituent column -> display column (v5.2), in display order
CONSTITUENT_DISPLAY_COLUMNS = {
    "ticker": "Ticker",
    "company": "Company",
    "is_uptrend": "Uptrend",
    "market_cap": "Market Cap ($M)",
    "change": "Change",
    "perf_week": "Perf Week",
    "perf_ytd": "Perf YTD",
}


_FINVIZ_QUOTE_URL = "https://finviz.com/quote.ashx?t={ticker}&p=w"
# For st.column_config.LinkColumn(display_text=...): shows the ticker, not the URL
TICKER_LINK_PATTERN = r"t=([^&]+)"


def finviz_chart_url(ticker: str) -> str:
    """Finviz quote page opened on the weekly chart (p=w)."""
    return _FINVIZ_QUOTE_URL.format(ticker=quote(str(ticker), safe="-."))


def prepare_constituents_table(constituents: pd.DataFrame) -> pd.DataFrame:
    """Format an industry's stock list for display.

    Uptrend stocks come first; within each group, larger market cap first.
    The Ticker column holds the Finviz weekly chart URL; the page renders it as a
    link labelled with the ticker (TICKER_LINK_PATTERN).
    """
    columns = list(CONSTITUENT_DISPLAY_COLUMNS.values())
    if constituents.empty:
        return pd.DataFrame(columns=columns)
    ordered = constituents.sort_values(
        ["is_uptrend", "market_cap"], ascending=[False, False], na_position="last",
    )
    table = ordered[list(CONSTITUENT_DISPLAY_COLUMNS)].rename(columns=CONSTITUENT_DISPLAY_COLUMNS)
    table["Ticker"] = table["Ticker"].map(finviz_chart_url)
    return table.reset_index(drop=True)


_UP_COLOR = "color: #00cc96"
_DOWN_COLOR = "color: #ef553b"
_SIGNED_DISPLAY_COLUMNS = ("Change", "Perf Week", "Perf YTD")


def style_constituent_row(row):
    """Color a constituent table row: uptrend ticker in green, returns by sign."""
    styles = []
    for col in row.index:
        value = row[col]
        if col == "Ticker":
            styles.append(f"{_UP_COLOR}; font-weight: bold" if row.get("Uptrend") else "")
        elif col in _SIGNED_DISPLAY_COLUMNS and pd.notna(value) and value != 0:
            styles.append(_UP_COLOR if value > 0 else _DOWN_COLOR)
        else:
            styles.append("")
    return styles


def summarize_constituents(constituents: pd.DataFrame) -> dict:
    """Return total / uptrend stock counts and the snapshot date."""
    if constituents.empty:
        return {"total": 0, "uptrend": 0, "as_of": None}
    return {
        "total": len(constituents),
        "uptrend": int(constituents["is_uptrend"].sum()),
        "as_of": str(constituents["date"].max()),
    }


def prepare_timeseries_csv(df: pd.DataFrame) -> pd.DataFrame:
    """Select and format columns for time series CSV export."""
    result = df[["date", "count", "total", "ratio", "ma_10", "slope"]].copy()
    result["trend"] = np.where(
        df["slope"].isna(), "neutral",
        np.where(df["slope"] > 0, "up", "down"),
    )
    return result


def prepare_all_timeseries_csv(all_data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Combine all worksheets into a single timeseries DataFrame for CSV export.

    Args:
        all_data: Dict mapping worksheet name to calculated DataFrame.

    Returns:
        DataFrame with columns: worksheet, date, count, total, ratio, ma_10, slope, trend.
        Empty dict returns 0-row DataFrame with correct columns.
    """
    expected_columns = ["worksheet", "date", "count", "total", "ratio", "ma_10", "slope", "trend"]

    frames = []
    for name in sorted(all_data.keys()):
        df = all_data[name]
        if df.empty:
            continue
        csv_df = prepare_timeseries_csv(df)
        csv_df.insert(0, "worksheet", name)
        csv_df["date"] = csv_df["date"].dt.strftime("%Y-%m-%d")
        frames.append(csv_df)

    if not frames:
        return pd.DataFrame(columns=expected_columns)

    return pd.concat(frames, ignore_index=True)


def build_sector_ranking_table(
    sector_data: Dict[str, pd.DataFrame],
    regime: str,
    level_regime: str,
    sector_edge_df: pd.DataFrame,
) -> pd.DataFrame:
    """Build a regime-aware sector ranking table.

    Sort order depends on (regime, level_regime):
    - converged or diverged with edge data: by Historical Edge descending
    - normal or no edge data: by Current Ratio descending
    """
    expected_cols = ["Sector", "Current Ratio", "10MA", "Trend", "Historical Edge"]

    rows = []
    for name, df in sector_data.items():
        if not name.startswith("sec_") or df.empty:
            continue
        status = get_current_status(df)
        rows.append({
            "Sector": get_sector_display_name(name),
            "Current Ratio": status["ratio"],
            "10MA": status["ratio_10ma"],
            "Trend": _trend_label(status["trend"]),
            "Historical Edge": None,
            "_key": name,
        })

    if not rows:
        return pd.DataFrame(columns=expected_cols)

    result = pd.DataFrame(rows)

    edge_matched = False
    if not sector_edge_df.empty:
        bucket = sector_edge_df[
            (sector_edge_df["regime"] == regime) &
            (sector_edge_df["level_regime"] == level_regime)
        ]
        if not bucket.empty:
            edge_map = dict(zip(bucket["sector_key"], bucket["mean_change"]))
            result["Historical Edge"] = result["_key"].map(edge_map)
            edge_matched = result["Historical Edge"].notna().any()

    if edge_matched and regime in ("converged", "diverged"):
        result = result.sort_values("Historical Edge", ascending=False, na_position="last")
    else:
        result = result.sort_values("Current Ratio", ascending=False)

    result = result.drop(columns=["_key"]).reset_index(drop=True)
    return result


def prepare_dispersion_csv(dispersion_df: pd.DataFrame) -> pd.DataFrame:
    """Select and format columns for dispersion CSV export."""
    output_cols = ["date", "dispersion", "mean_ratio", "range", "regime", "level_regime",
                   "sector_count", "expected_sector_count", "coverage_complete"]

    if dispersion_df.empty:
        return pd.DataFrame(columns=output_cols)

    result = dispersion_df[output_cols].copy()
    if len(result) > 0 and hasattr(result["date"].iloc[0], "strftime"):
        result["date"] = result["date"].apply(
            lambda d: d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
        )
    return result


def filter_by_date_range(df: pd.DataFrame, start, end) -> pd.DataFrame:
    """Filter a DataFrame by date range (inclusive).

    Args:
        df: DataFrame with a 'date' column (datetime).
        start: Start date (date object).
        end: End date (date object).

    Returns:
        Filtered DataFrame.
    """
    mask = (df["date"].dt.date >= start) & (df["date"].dt.date <= end)
    return df[mask]


def default_start_date(
    min_date: datetime.date, max_date: datetime.date, years: Optional[int] = None
) -> datetime.date:
    """Return the default start date, at most `years` (default DEFAULT_DISPLAY_YEARS) before max_date."""
    cutoff = max_date - relativedelta(years=years if years is not None else DEFAULT_DISPLAY_YEARS)
    return max(min_date, cutoff)


# Industry Heatmap KPI filters: query-param key -> (column, value)
HEATMAP_FILTERS = {
    "oversold": ("Status", "Oversold"),
    "normal": ("Status", "Normal"),
    "overbought": ("Status", "Overbought"),
    "trend_up": ("Trend", "Up"),
    "trend_down": ("Trend", "Down"),
}


def parse_heatmap_filter(value) -> Optional[str]:
    """Validate a ?filter= query value; anything unknown means no filter."""
    return value if isinstance(value, str) and value in HEATMAP_FILTERS else None


def filter_industry_summary(summary: pd.DataFrame, key: Optional[str]) -> pd.DataFrame:
    """Rows of the industry summary that match a KPI filter (all rows when key is None)."""
    if key is None:
        return summary
    column, value = HEATMAP_FILTERS[key]
    return summary[summary[column] == value].reset_index(drop=True)
