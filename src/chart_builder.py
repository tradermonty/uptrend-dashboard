"""Plotly chart builders for uptrend dashboard (v2)."""

import logging
from typing import Dict, List, Optional

import pandas as pd
import numpy as np
import plotly.graph_objects as go

from plotly.subplots import make_subplots

from src.constants import (
    UPPER_THRESHOLD,
    LOWER_THRESHOLD,
    CHART_HEIGHT_RATIO,
    CHART_HEIGHT_SUMMARY,
    CHART_HEIGHT_COMPARISON,
    CHART_HEIGHT_HEATMAP,
    CHART_HEIGHT_DISPERSION,
    CHART_HEIGHT_REGIME_TIMELINE,
    CHART_Y_MAX_MIN,
    CHART_Y_MAX_MULTIPLIER,
)
from src.data_processor import get_sector_display_name, get_industry_display_name

logger = logging.getLogger(__name__)


# Color constants for trend segments
COLOR_TREND_UP = "#00cc96"
COLOR_TREND_DOWN = "#ef553b"
COLOR_TREND_NA = "#636efa"

# 11-color palette for sector comparison (maximally distinguishable)
SECTOR_PALETTE = [
    "#1f77b4",  # blue
    "#ff7f0e",  # orange
    "#2ca02c",  # green
    "#d62728",  # red
    "#9467bd",  # purple
    "#8c564b",  # brown
    "#e377c2",  # pink
    "#7f7f7f",  # gray
    "#bcbd22",  # olive
    "#17becf",  # cyan
    "#ff6600",  # dark orange
]

# 20-color palette for industry comparison (maximally distinguishable)
INDUSTRY_PALETTE = [
    "#1f77b4",  # blue
    "#ff7f0e",  # orange
    "#2ca02c",  # green
    "#d62728",  # red
    "#9467bd",  # purple
    "#8c564b",  # brown
    "#e377c2",  # pink
    "#7f7f7f",  # gray
    "#bcbd22",  # olive
    "#17becf",  # cyan
    "#ff6600",  # dark orange
    "#1a9850",  # forest green
    "#fdae61",  # light orange
    "#abd9e9",  # light blue
    "#d73027",  # crimson
    "#4575b4",  # steel blue
    "#fee090",  # gold
    "#91bfdb",  # sky blue
    "#fc8d59",  # salmon
    "#313695",  # navy
]

COLOR_MA = "rgba(148, 103, 189, 0.8)"
COLOR_PEAK = "#FF0000"
COLOR_TROUGH = "#00BFFF"
COLOR_UPPER = "#d62728"
COLOR_LOWER = "#2ca02c"

STATUS_COLORS = {
    "Overbought": "#d62728",
    "Oversold": "#2ca02c",
    "Normal": "#1f77b4",
}


def _get_trend_state(slope_val):
    """Determine trend state from slope value."""
    if pd.isna(slope_val):
        return "na"
    return "up" if slope_val > 0 else "down"


def _trend_color(state: str) -> str:
    """Map trend state to color."""
    if state == "up":
        return COLOR_TREND_UP
    elif state == "down":
        return COLOR_TREND_DOWN
    return COLOR_TREND_NA


def _trend_legend_name(state: str) -> str:
    """Map trend state to legend name."""
    if state == "up":
        return "Ratio (Up)"
    elif state == "down":
        return "Ratio (Down)"
    return "Ratio (N/A)"


def _add_ratio_segments(fig: go.Figure, df: pd.DataFrame) -> None:
    """Add color-coded ratio trend segments to the figure."""
    segments = []
    if len(df) > 0:
        current_state = _get_trend_state(df["slope"].iloc[0])
        seg_start = 0

        for i in range(1, len(df)):
            state = _get_trend_state(df["slope"].iloc[i])
            if state != current_state:
                segments.append((seg_start, i, current_state))
                seg_start = i
                current_state = state
        segments.append((seg_start, len(df), current_state))

    shown_legends = set()
    for start, end, state in segments:
        actual_start = max(0, start - 1) if start > 0 else start
        seg_df = df.iloc[actual_start:end]

        name = _trend_legend_name(state)
        show_legend = name not in shown_legends
        shown_legends.add(name)

        fig.add_trace(
            go.Scatter(
                x=seg_df["date"],
                y=seg_df["ratio"],
                mode="lines",
                name=name,
                line=dict(color=_trend_color(state), width=2),
                showlegend=show_legend,
            )
        )


def _add_moving_average(fig: go.Figure, df: pd.DataFrame) -> None:
    """Add 10MA line to the figure."""
    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["ma_10"],
            mode="lines",
            name="10MA",
            line=dict(color=COLOR_MA, width=1.5),
            opacity=0.85,
        )
    )


def _add_peaks_and_troughs(fig: go.Figure, df: pd.DataFrame) -> None:
    """Add peak and trough markers to the figure."""
    if "is_peak" in df.columns:
        peak_df = df[df["is_peak"]]
        if len(peak_df) > 0:
            fig.add_trace(
                go.Scatter(
                    x=peak_df["date"],
                    y=peak_df["ma_10"],
                    mode="markers",
                    name="10MA Peak",
                    marker=dict(symbol="triangle-down", size=10, color=COLOR_PEAK),
                )
            )

    if "is_trough" in df.columns:
        trough_df = df[df["is_trough"]]
        if len(trough_df) > 0:
            fig.add_trace(
                go.Scatter(
                    x=trough_df["date"],
                    y=trough_df["ma_10"],
                    mode="markers",
                    name="10MA Trough",
                    marker=dict(symbol="triangle-up", size=10, color=COLOR_TROUGH),
                )
            )


def _add_threshold_lines(fig: go.Figure, df: pd.DataFrame) -> None:
    """Add upper and lower threshold lines to the figure."""
    upper_val = df["upper"].dropna().iloc[0] if not df["upper"].dropna().empty else UPPER_THRESHOLD
    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=[upper_val] * len(df),
            mode="lines",
            name="Upper",
            line=dict(color=COLOR_UPPER, width=1, dash="dot"),
        )
    )

    lower_val = df["lower"].dropna().iloc[0] if not df["lower"].dropna().empty else LOWER_THRESHOLD
    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=[lower_val] * len(df),
            mode="lines",
            name="Lower",
            line=dict(color=COLOR_LOWER, width=1, dash="dot"),
        )
    )


def _apply_chart_layout(fig: go.Figure, df: pd.DataFrame, title: str) -> None:
    """Apply standard layout settings to the ratio chart."""
    fig.update_layout(
        title=title,
        xaxis_title="Date",
        yaxis_title="Ratio",
        template="plotly_white",
        height=CHART_HEIGHT_RATIO,
        yaxis=dict(range=[0, max(CHART_Y_MAX_MIN, df["ratio"].max() * CHART_Y_MAX_MULTIPLIER)]),
        hovermode="x unified",
    )


def build_ratio_chart(df: pd.DataFrame, title: str = "Uptrend Ratio") -> go.Figure:
    """Build a time series chart of ratio data with color-coded trend segments."""
    fig = go.Figure()
    _add_ratio_segments(fig, df)
    _add_moving_average(fig, df)
    _add_peaks_and_troughs(fig, df)
    _add_threshold_lines(fig, df)
    _apply_chart_layout(fig, df, title)
    return fig


def build_sector_summary_chart(summary_df: pd.DataFrame) -> go.Figure:
    """Build a horizontal bar chart of sector ratios."""
    fig = go.Figure()

    colors = [STATUS_COLORS.get(s, "#1f77b4") for s in summary_df["Status"]]

    fig.add_trace(
        go.Bar(
            y=summary_df["Sector"],
            x=summary_df["Ratio"],
            orientation="h",
            marker_color=colors,
            text=summary_df["Ratio"].apply(lambda x: f"{x:.1%}"),
            textposition="auto",
            customdata=summary_df["_key"].values if "_key" in summary_df.columns else None,
        )
    )

    fig.add_vline(x=UPPER_THRESHOLD, line_dash="dash", line_color=COLOR_UPPER, annotation_text="Upper")
    fig.add_vline(x=LOWER_THRESHOLD, line_dash="dash", line_color=COLOR_LOWER, annotation_text="Lower")

    fig.update_layout(
        title="Sector Ratio Summary",
        template="plotly_white",
        height=CHART_HEIGHT_SUMMARY,
        xaxis_title="Ratio",
        yaxis=dict(autorange="reversed"),
    )

    return fig


def build_industry_summary_chart(
    summary_df: pd.DataFrame, sector_name: str = ""
) -> go.Figure:
    """Build a horizontal bar chart of industry ratios.

    Args:
        summary_df: DataFrame from build_industry_summary().
        sector_name: Optional sector name for the chart title.
    """
    fig = go.Figure()

    colors = [STATUS_COLORS.get(s, "#1f77b4") for s in summary_df["Status"]]

    fig.add_trace(
        go.Bar(
            y=summary_df["Industry"],
            x=summary_df["Ratio"],
            orientation="h",
            marker_color=colors,
            text=summary_df["Ratio"].apply(lambda x: f"{x:.1%}"),
            textposition="auto",
            customdata=summary_df["_key"].values if "_key" in summary_df.columns else None,
        )
    )

    fig.add_vline(x=UPPER_THRESHOLD, line_dash="dash", line_color=COLOR_UPPER, annotation_text="Upper")
    fig.add_vline(x=LOWER_THRESHOLD, line_dash="dash", line_color=COLOR_LOWER, annotation_text="Lower")

    title = f"Industry Ratio Summary — {sector_name}" if sector_name else "Industry Ratio Summary"
    height = max(300, len(summary_df) * 35 + 100)

    fig.update_layout(
        title=title,
        template="plotly_white",
        height=height,
        xaxis_title="Ratio",
        yaxis=dict(autorange="reversed"),
    )

    return fig


def _build_comparison_chart(
    all_data: Dict[str, pd.DataFrame],
    selected_keys: List[str],
    display_name_fn,
    palette: List[str],
    use_ma: bool,
    title_prefix: str,
) -> go.Figure:
    """Build an overlay chart comparing ratios over time (shared logic).

    Args:
        all_data: Dict of worksheet name -> calculated DataFrame.
        selected_keys: List of worksheet keys to display.
        display_name_fn: Callable(key) -> display name string.
        palette: Color palette list.
        use_ma: If True, plot ma_10. If False, plot raw ratio.
        title_prefix: Title prefix (e.g. "Sector Comparison").
    """
    fig = go.Figure()

    y_col = "ma_10" if use_ma else "ratio"

    # Collect latest values for sorting legend by descending value
    key_latest = []
    for key in selected_keys:
        if key not in all_data:
            continue
        df = all_data[key]
        if df.empty or y_col not in df.columns:
            continue
        valid = df[y_col].dropna()
        latest_val = valid.iloc[-1] if len(valid) > 0 else 0.0
        display_name = display_name_fn(key)
        key_latest.append((key, display_name, latest_val))

    # Sort by latest value descending
    key_latest.sort(key=lambda x: x[2], reverse=True)

    for idx, (key, display_name, latest_val) in enumerate(key_latest):
        df = all_data[key]
        color = palette[idx % len(palette)]
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df[y_col],
                mode="lines",
                name=display_name,
                line=dict(color=color, width=2),
            )
        )

        # Annotate latest value at the right end of each line
        valid = df[y_col].dropna()
        if len(valid) > 0:
            last_date = df.loc[valid.index[-1], "date"]
            fig.add_annotation(
                x=last_date,
                y=latest_val,
                text=f"{display_name} {latest_val:.0%}",
                showarrow=False,
                xanchor="left",
                xshift=5,
                font=dict(size=10, color=color),
            )

    # Threshold lines
    fig.add_trace(
        go.Scatter(
            x=[],
            y=[],
            mode="lines",
            name="Upper",
            line=dict(color=COLOR_UPPER, width=1, dash="dash"),
            showlegend=True,
        )
    )
    fig.add_hline(
        y=UPPER_THRESHOLD,
        line_dash="dash",
        line_color=COLOR_UPPER,
        line_width=1,
    )

    fig.add_trace(
        go.Scatter(
            x=[],
            y=[],
            mode="lines",
            name="Lower",
            line=dict(color=COLOR_LOWER, width=1, dash="dash"),
            showlegend=True,
        )
    )
    fig.add_hline(
        y=LOWER_THRESHOLD,
        line_dash="dash",
        line_color=COLOR_LOWER,
        line_width=1,
    )

    title_suffix = " (10MA)" if use_ma else " (Raw Ratio)"
    fig.update_layout(
        title=title_prefix + title_suffix,
        xaxis_title="Date",
        yaxis_title="Ratio",
        yaxis=dict(tickformat=".0%"),
        template="plotly_white",
        height=CHART_HEIGHT_COMPARISON,
        legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02),
        hovermode="x unified",
    )

    return fig


def build_sector_comparison_chart(
    all_data: Dict[str, pd.DataFrame],
    selected_sectors: Optional[List[str]] = None,
    use_ma: bool = True,
) -> go.Figure:
    """Build an overlay chart comparing sector ratios over time.

    Args:
        all_data: Dict of worksheet name -> calculated DataFrame.
        selected_sectors: List of sector keys to display.
        use_ma: If True, plot ma_10 (smoothed). If False, plot raw ratio.
    """
    sectors = selected_sectors or [k for k in all_data if k.startswith("sec_")]
    return _build_comparison_chart(
        all_data=all_data,
        selected_keys=sectors,
        display_name_fn=get_sector_display_name,
        palette=SECTOR_PALETTE,
        use_ma=use_ma,
        title_prefix="Sector Comparison",
    )


def build_industry_comparison_chart(
    all_data: Dict[str, pd.DataFrame],
    selected_industries: Optional[List[str]] = None,
    use_ma: bool = True,
) -> go.Figure:
    """Build an overlay chart comparing industry ratios over time.

    Args:
        all_data: Dict of worksheet name -> calculated DataFrame.
        selected_industries: List of industry keys to display.
        use_ma: If True, plot ma_10 (smoothed). If False, plot raw ratio.
    """
    industries = selected_industries or [k for k in all_data if k.startswith("ind_")]
    return _build_comparison_chart(
        all_data=all_data,
        selected_keys=industries,
        display_name_fn=get_industry_display_name,
        palette=INDUSTRY_PALETTE,
        use_ma=use_ma,
        title_prefix="Industry Comparison",
    )


def build_industry_heatmap(
    summary_df: pd.DataFrame,
    color_mode: str = "ratio",
    size_mode: str = "uniform",
) -> go.Figure:
    """Build a treemap chart of all industries grouped by sector.

    Args:
        summary_df: DataFrame from build_industry_summary_with_sector().
            Expected columns: Industry, Ratio, 10MA, Trend, Slope, Status, _key, Sector, Total.
        color_mode: "ratio" for continuous RdYlGn colorscale, "status" for categorical colors.
        size_mode: "uniform" for equal cell sizes, "count" for stock count-based sizes.

    Returns:
        Plotly Figure with a Treemap trace.
    """
    fig = go.Figure()

    if summary_df.empty:
        fig.add_trace(go.Treemap(labels=[], parents=[], values=[]))
        fig.update_layout(
            title="Industry Heatmap",
            height=CHART_HEIGHT_HEATMAP,
            template="plotly_white",
        )
        return fig

    # Build treemap data: root ("") -> sectors -> industries
    sectors = summary_df["Sector"].unique().tolist()

    labels = []
    parents = []
    values = []
    colors = []
    customdata = []
    text = []
    hovertext = []

    # Add sector nodes
    for sector in sectors:
        labels.append(sector)
        parents.append("")
        values.append(0)
        colors.append("#cccccc")
        customdata.append("")
        text.append("")
        hovertext.append(sector)

    # Add industry nodes
    for _, row in summary_df.iterrows():
        labels.append(row["Industry"])
        parents.append(row["Sector"])

        if size_mode == "count":
            values.append(int(row["Total"]))
        else:
            values.append(1)

        if color_mode == "status":
            colors.append(STATUS_COLORS.get(row["Status"], "#1f77b4"))
        else:
            colors.append(None)  # placeholder, will use colorscale

        customdata.append(row["_key"])

        ratio_pct = f"{row['Ratio']:.1%}" if pd.notna(row["Ratio"]) else "N/A"
        name = row["Industry"]
        short_name = name[:14] + "…" if len(name) > 15 else name
        text.append(f"{short_name}<br>{ratio_pct}")

        ma_str = f"{row['10MA']:.1%}" if pd.notna(row["10MA"]) else "N/A"
        slope_str = f"{row['Slope']:.4f}" if pd.notna(row["Slope"]) else "N/A"
        hovertext.append(
            f"<b>{row['Industry']}</b><br>"
            f"Ratio: {ratio_pct}<br>"
            f"10MA: {ma_str}<br>"
            f"Trend: {row['Trend']}<br>"
            f"Slope: {slope_str}<br>"
            f"Status: {row['Status']}"
        )

    if color_mode == "ratio":
        # Build marker colors array: ratio values for industries, NaN for sectors
        marker_values = []
        for i, label in enumerate(labels):
            if label in sectors:
                marker_values.append(np.nan)
            else:
                idx = len(sectors) + (i - len(sectors))
                row = summary_df.iloc[i - len(sectors)]
                marker_values.append(row["Ratio"] if pd.notna(row["Ratio"]) else 0)

        valid_ratios = summary_df["Ratio"].dropna()
        cmin = max(0, valid_ratios.min()) if len(valid_ratios) > 0 else 0
        cmax = valid_ratios.max() if len(valid_ratios) > 0 else 1

        fig.add_trace(
            go.Treemap(
                labels=labels,
                parents=parents,
                values=values,
                marker=dict(
                    colors=marker_values,
                    colorscale="RdYlGn",
                    cmin=cmin,
                    cmax=cmax,
                    showscale=True,
                    colorbar=dict(title="Ratio"),
                ),
                customdata=customdata,
                text=text,
                textinfo="text",
                hovertext=hovertext,
                hoverinfo="text",
            )
        )
    else:
        fig.add_trace(
            go.Treemap(
                labels=labels,
                parents=parents,
                values=values,
                marker=dict(colors=colors),
                customdata=customdata,
                text=text,
                textinfo="text",
                hovertext=hovertext,
                hoverinfo="text",
            )
        )

    fig.update_layout(
        title="Industry Heatmap",
        height=CHART_HEIGHT_HEATMAP,
        template="plotly_white",
        margin=dict(t=50, l=10, r=10, b=10),
    )

    return fig


# --- Dispersion Charts ---

REGIME_COLORS = {
    "converged": "#2ca02c",
    "normal": "#1f77b4",
    "diverged": "#d62728",
}

REGIME_BG_COLORS = {
    "converged": "rgba(0,255,0,0.05)",
    "diverged": "rgba(255,0,0,0.05)",
}


def _dispersion_regime_segments(dispersion_df: pd.DataFrame) -> list:
    """Return valid regime runs, ending each run before a missing observation."""
    segments = []
    previous = None
    start = end = None
    for _, row in dispersion_df.iterrows():
        regime = row["regime"]
        if pd.isna(regime):
            if previous is not None:
                segments.append((start, end, previous))
            previous = None
        elif regime != previous:
            if previous is not None:
                segments.append((start, end, previous))
            start = end = row["date"]
            previous = regime
        else:
            end = row["date"]
    if previous is not None:
        segments.append((start, end, previous))
    return segments


def build_dispersion_chart(dispersion_df: pd.DataFrame) -> go.Figure:
    """Build a dual-axis dispersion chart with regime background bands.

    Left Y: Dispersion (σ) + MA10 + p25/p75 time-series traces.
    Right Y: Mean Ratio.
    """
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    if dispersion_df.empty:
        fig.update_layout(
            height=CHART_HEIGHT_DISPERSION,
            template="plotly_white",
        )
        return fig

    dates = dispersion_df["date"]

    # Dispersion line (primary)
    fig.add_trace(
        go.Scatter(
            x=dates, y=dispersion_df["dispersion"],
            name="Dispersion (σ)",
            line=dict(color="#1f77b4", width=2),
        ),
        secondary_y=False,
    )

    # Dispersion MA10 (dashed)
    fig.add_trace(
        go.Scatter(
            x=dates, y=dispersion_df["dispersion_ma10"],
            name="Dispersion MA10",
            line=dict(color="#1f77b4", width=1, dash="dash"),
        ),
        secondary_y=False,
    )

    # p25 / p75 time-series thresholds
    fig.add_trace(
        go.Scatter(
            x=dates, y=dispersion_df["p25"],
            name="P25 Threshold",
            line=dict(color="#2ca02c", width=1, dash="dot"),
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=dates, y=dispersion_df["p75"],
            name="P75 Threshold",
            line=dict(color="#d62728", width=1, dash="dot"),
        ),
        secondary_y=False,
    )

    # Mean Ratio (secondary axis)
    fig.add_trace(
        go.Scatter(
            x=dates, y=dispersion_df["mean_ratio"],
            name="Mean Ratio",
            line=dict(color="#ff7f0e", width=1.5, dash="dot"),
        ),
        secondary_y=True,
    )

    # Regime background bands — only draw segments lasting >= 5 days
    # to avoid noisy flickering of thin colored bands
    _MIN_REGIME_BAND_DAYS = 5
    for seg_start, seg_end, seg_regime in _dispersion_regime_segments(dispersion_df):
        if seg_regime not in REGIME_BG_COLORS:
            continue
        duration = (pd.Timestamp(seg_end) - pd.Timestamp(seg_start)).days
        if duration >= _MIN_REGIME_BAND_DAYS:
            fig.add_vrect(
                x0=seg_start, x1=seg_end,
                fillcolor=REGIME_BG_COLORS[seg_regime],
                layer="below", line_width=0,
            )

    fig.update_layout(
        height=CHART_HEIGHT_DISPERSION,
        template="plotly_white",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(t=60),
    )
    fig.update_yaxes(title_text="Dispersion (σ)", secondary_y=False)
    fig.update_yaxes(title_text="Mean Ratio", tickformat=".0%", secondary_y=True)

    return fig


def build_regime_timeline_chart(dispersion_df: pd.DataFrame) -> go.Figure:
    """Build a horizontal bar chart showing regime transitions over time."""
    fig = go.Figure()

    if dispersion_df.empty:
        fig.update_layout(
            height=CHART_HEIGHT_REGIME_TIMELINE,
            template="plotly_white",
        )
        return fig

    segments = _dispersion_regime_segments(dispersion_df)

    # Add a Bar trace per regime type for legend.
    # On a Plotly date axis, bar widths must be in milliseconds.
    MS_PER_DAY = 86_400_000
    added_legend = set()
    for start, end, regime in segments:
        duration_days = (pd.Timestamp(end) - pd.Timestamp(start)).days + 1
        duration_ms = duration_days * MS_PER_DAY
        show_legend = regime not in added_legend
        added_legend.add(regime)
        fig.add_trace(
            go.Bar(
                x=[duration_ms],
                y=["Regime"],
                orientation="h",
                base=[pd.Timestamp(start)],
                marker_color=REGIME_COLORS.get(regime, "#7f7f7f"),
                name=regime.title(),
                showlegend=show_legend,
                hovertext=f"{regime}: {start} → {end} ({duration_days}d)",
                hoverinfo="text",
            )
        )

    fig.update_layout(
        height=CHART_HEIGHT_REGIME_TIMELINE,
        template="plotly_white",
        barmode="stack",
        showlegend=True,
        xaxis=dict(type="date"),
        yaxis=dict(visible=False),
        margin=dict(t=10, b=20, l=10, r=10),
    )

    return fig
