"""Plotly chart builders for uptrend dashboard (v2)."""

import html
import logging
from typing import Dict, List, Optional

import pandas as pd
import numpy as np
import plotly.graph_objects as go

from plotly.colors import sample_colorscale
from plotly.subplots import make_subplots

from src.constants import (
    UPPER_THRESHOLD,
    LOWER_THRESHOLD,
    CHART_HEIGHT_RATIO,
    CHART_HEIGHT_MARKET,
    MARKET_PRICE_PANEL_SHARE,
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

# Legend below the plot: a right-side legend takes ~1/3 of the width on phones
HORIZONTAL_LEGEND = dict(orientation="h", yanchor="top", y=-0.12, xanchor="left", x=0)

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


def _add_ratio_segments(fig: go.Figure, df: pd.DataFrame, row: Optional[int] = None) -> None:
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
            ),
            row=row, col=row and 1,
        )


def _add_moving_average(fig: go.Figure, df: pd.DataFrame, row: Optional[int] = None) -> None:
    """Add 10MA line to the figure."""
    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["ma_10"],
            mode="lines",
            name="10MA",
            line=dict(color=COLOR_MA, width=1.5),
            opacity=0.85,
        ),
        row=row, col=row and 1,
    )


def _add_peaks_and_troughs(fig: go.Figure, df: pd.DataFrame, row: Optional[int] = None) -> None:
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
                ),
                row=row, col=row and 1,
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
                ),
                row=row, col=row and 1,
            )


def _add_threshold_lines(fig: go.Figure, df: pd.DataFrame, row: Optional[int] = None) -> None:
    """Add upper and lower threshold lines to the figure."""
    upper_val = df["upper"].dropna().iloc[0] if not df["upper"].dropna().empty else UPPER_THRESHOLD
    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=[upper_val] * len(df),
            mode="lines",
            name="Upper",
            line=dict(color=COLOR_UPPER, width=1, dash="dot"),
        ),
        row=row, col=row and 1,
    )

    lower_val = df["lower"].dropna().iloc[0] if not df["lower"].dropna().empty else LOWER_THRESHOLD
    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=[lower_val] * len(df),
            mode="lines",
            name="Lower",
            line=dict(color=COLOR_LOWER, width=1, dash="dot"),
        ),
        row=row, col=row and 1,
    )


def _apply_chart_layout(fig: go.Figure, df: pd.DataFrame, title: str) -> None:
    """Apply standard layout settings to the ratio chart."""
    fig.update_layout(
        title=title,
        yaxis_title="Ratio",
        template="plotly_white",
        height=CHART_HEIGHT_RATIO,
        yaxis=dict(
            range=[0, max(CHART_Y_MAX_MIN, df["ratio"].max() * CHART_Y_MAX_MULTIPLIER)],
            tickformat=".0%",
        ),
        hovermode="x unified",
        legend=HORIZONTAL_LEGEND,
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


COLOR_PRICE = "#17becf"
PRICE_TRACE_NAME = "S&P 500"
PRICE_PANEL_LABEL = "S&P 500 (SPY)"
DOWNTREND_BAND_NAME = "ratio-downtrend"
COLOR_DOWNTREND_BAND = "rgba(233, 30, 99, 0.08)"  # pale pink, like the Market Breadth page
OVERSOLD_BAND_NAME = "ratio-oversold"
COLOR_OVERSOLD_BAND = "rgba(233, 30, 99, 0.28)"  # deeper pink: ratio below the Oversold level
PANEL_DIVIDER_NAME = "panel-divider"
COLOR_PANEL_DIVIDER = "#c8ced8"


def has_price_panel(fig: go.Figure) -> bool:
    """True when build_market_chart drew the S&P 500 panel (not the plain fallback)."""
    return any(t.name == PRICE_TRACE_NAME for t in fig.data)


def _add_bands(fig: go.Figure, dates: list, mask: list, name: str, color: str) -> None:
    """Shade each run of True sessions in `mask`, in both panels.

    A band runs from the first session of the run to the next session (or the last
    one), so consecutive bands meet the line segments they describe. A run of only
    the last session would have no width, so it gets one session's width instead
    (the day the Status card turns Oversold must show on the chart). Each panel
    gets its own band, leaving the gap between the panels white.
    """
    step = dates[-1] - dates[-2] if len(dates) > 1 else pd.Timedelta(days=1)
    i = 0
    while i < len(mask):
        if not mask[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(mask) and mask[j + 1]:
            j += 1
        end = dates[min(j + 1, len(dates) - 1)]
        if end == dates[i]:
            end = dates[i] + step
        for xref, yref in (("x", "y domain"), ("x2", "y2 domain")):
            fig.add_shape(type="rect", name=name, xref=xref, yref=yref,
                          x0=dates[i], x1=end, y0=0, y1=1, fillcolor=color,
                          line=dict(width=0), layer="below")
        i = j + 1


def _add_downtrend_bands(fig: go.Figure, df: pd.DataFrame) -> None:
    """Pale pink where the ratio's 10MA slope is down (or flat)."""
    down = [_get_trend_state(s) == "down" for s in df["slope"]]
    _add_bands(fig, list(df["date"]), down, DOWNTREND_BAND_NAME, COLOR_DOWNTREND_BAND)


def _add_oversold_bands(fig: go.Figure, df: pd.DataFrame) -> None:
    """Deeper pink where the ratio is below the Oversold level, whatever the 10MA does.

    Same rule as the Status card (ratio < lower). Drawn after the downtrend bands,
    so it sits on top of them.
    """
    lower = df["lower"].fillna(LOWER_THRESHOLD)
    oversold = list((pd.to_numeric(df["ratio"], errors="coerce") < lower).fillna(False))
    _add_bands(fig, list(df["date"]), oversold, OVERSOLD_BAND_NAME, COLOR_OVERSOLD_BAND)


def _add_panel_divider(fig: go.Figure) -> None:
    """A thin full-width line in the gap, so the two panels read as separate charts."""
    y = (fig.layout.yaxis.domain[0] + fig.layout.yaxis2.domain[1]) / 2
    fig.add_shape(type="line", name=PANEL_DIVIDER_NAME, xref="paper", yref="paper",
                  x0=0, x1=1, y0=y, y1=y, line=dict(color=COLOR_PANEL_DIVIDER, width=1))


def build_market_chart(df: pd.DataFrame, prices: pd.DataFrame, title: str = "Uptrend Ratio") -> go.Figure:
    """S&P 500 (log scale) above the market Uptrend Ratio, on one shared time axis.

    ``prices`` has (date, close). Without prices inside the ratio's date range the
    result is the plain ratio chart, so a missing price source never hides the ratio.
    """
    if prices is not None and len(prices) and len(df):
        start, end = df["date"].min(), df["date"].max()
        prices = prices[(prices["date"] >= start) & (prices["date"] <= end)]
    if prices is None or prices.empty or df.empty:
        return build_ratio_chart(df, title=title)

    last = prices.iloc[-1]
    label = (f"<b>{PRICE_PANEL_LABEL}</b> {last['close']:,.2f} "
             f"<span style='color:#888'>({last['date'].month}/{last['date'].day}, log)</span>")
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.07,
        row_heights=[MARKET_PRICE_PANEL_SHARE, 1 - MARKET_PRICE_PANEL_SHARE],
        subplot_titles=(label, ""),
    )
    fig.add_trace(
        go.Scatter(x=prices["date"], y=prices["close"], mode="lines", name=PRICE_TRACE_NAME,
                   line=dict(color=COLOR_PRICE, width=2), showlegend=False,
                   hovertemplate="S&P 500: %{y:,.2f}<extra></extra>"),
        row=1, col=1,
    )
    _add_downtrend_bands(fig, df)
    _add_oversold_bands(fig, df)
    _add_panel_divider(fig)
    _add_ratio_segments(fig, df, row=2)
    _add_moving_average(fig, df, row=2)
    _add_peaks_and_troughs(fig, df, row=2)
    _add_threshold_lines(fig, df, row=2)

    fig.update_layout(
        title=title,
        template="plotly_white",
        height=CHART_HEIGHT_MARKET,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="top", y=-0.08, xanchor="left", x=0),
    )
    # Subplot titles sit left-aligned above each panel, like the Market Breadth page
    for ann in fig.layout.annotations:
        ann.update(x=0, xanchor="left", font=dict(size=13))
    fig.update_yaxes(type="log", row=1, col=1)
    fig.update_yaxes(
        title_text="Ratio", tickformat=".0%", row=2, col=1,
        range=[0, max(CHART_Y_MAX_MIN, df["ratio"].max() * CHART_Y_MAX_MULTIPLIER)],
    )
    # One hover box covering both panels at the touched date (plotly >= 5.21)
    try:
        fig.update_layout(hoversubplots="axis")
    except ValueError:
        pass
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
        yaxis_title="Ratio",
        yaxis=dict(tickformat=".0%"),
        template="plotly_white",
        height=CHART_HEIGHT_COMPARISON,
        legend=HORIZONTAL_LEGEND,
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


HEATMAP_ROOT_LABEL = "All Sectors"
HEATMAP_DRILLDOWN_CMAX = 0.6


def _weighted_sector_ratio(sector_df: pd.DataFrame) -> float:
    """Stock-count-weighted ratio of a sector's industries (≈ the sector's own ratio)."""
    valid = sector_df.dropna(subset=["Ratio"])
    if valid.empty:
        return np.nan
    weights = valid["Total"] if "Total" in valid.columns else None
    if weights is None or weights.fillna(0).sum() <= 0:
        return float(valid["Ratio"].mean())
    weights = weights.fillna(0)
    return float((valid["Ratio"] * weights).sum() / weights.sum())


def _ratio_status(ratio: float) -> str:
    """Map a ratio to Overbought/Oversold/Normal using the standard thresholds."""
    if pd.isna(ratio):
        return "Normal"
    if ratio >= UPPER_THRESHOLD:
        return "Overbought"
    if ratio <= LOWER_THRESHOLD:
        return "Oversold"
    return "Normal"


# Stock tiles: daily change colors (Finviz-map style), saturating at ±3%
STOCK_CHANGE_CLIP = 0.03
_STOCK_CHANGE_SCALE = [[0.0, "#d62728"], [0.5, "#555a64"], [1.0, "#2ca02c"]]
_STOCK_SHARE_OF_INDUSTRY = 0.999  # float headroom so children never exceed the parent


def _stock_change_color(change) -> str:
    if pd.isna(change):
        return "#7f7f7f"
    pos = (max(-STOCK_CHANGE_CLIP, min(STOCK_CHANGE_CLIP, change)) / STOCK_CHANGE_CLIP + 1) / 2
    return sample_colorscale(_STOCK_CHANGE_SCALE, [pos])[0]


def _format_market_cap(cap_m) -> str:
    if pd.isna(cap_m):
        return "N/A"
    return f"${cap_m / 1000:.1f}B" if cap_m >= 1000 else f"${cap_m:.0f}M"


def _pct(value) -> str:
    return f"{value:+.1%}" if pd.notna(value) else "N/A"


def _heatmap_with_stocks(
    fig, summary_df, constituents, labels, parents, values, colors, customdata,
    text, hovertext, node_ratios, color_mode, color_range, drilldown,
) -> go.Figure:
    """Add a stock level under each industry and render with explicit colors.

    - Sizes: branchvalues="total". Industry tiles keep their size (uniform/count);
      stocks split their industry's value in proportion to market cap.
    - Colors: sectors/industries keep their ratio/status colors (converted to
      explicit colors because stocks use a different scale: daily change).
    - Text: plain ticker (customdata holds the Finviz URL opened by the tap handler); uptrend stocks are
      bold with a thick outline.
    - maxdepth=2: the first view stops at industries; tap an industry for stocks.
    """
    from src.data_processor import finviz_chart_url

    n_base = len(labels)
    ids = list(labels)
    line_widths = [1.0] * n_base

    # Explicit colors for existing nodes
    if color_mode == "ratio":
        valid = summary_df["Ratio"].dropna()
        cmin = max(0, valid.min()) if len(valid) else 0
        cmax = valid.max() if len(valid) else 1
        if color_range is not None:
            cmin, cmax = color_range
        elif drilldown:
            cmin, cmax = 0, HEATMAP_DRILLDOWN_CMAX
        span = (cmax - cmin) or 1
        node_colors = [
            "#cccccc" if pd.isna(r) else
            sample_colorscale("RdYlGn", [min(1, max(0, (r - cmin) / span))])[0]
            for r in node_ratios
        ]
    else:
        node_colors = list(colors)

    # Industry label -> worksheet key and node index
    industry_index = {customdata[i]: i for i in range(n_base) if customdata[i]}
    for ws, group in constituents.groupby("worksheet"):
        if ws not in industry_index:
            continue
        parent_i = industry_index[ws]
        caps = pd.to_numeric(group["market_cap"], errors="coerce")
        caps = caps.fillna(caps.min() if caps.notna().any() else 1.0).clip(lower=0.01)
        budget = values[parent_i] * _STOCK_SHARE_OF_INDUSTRY
        for (_, stock), cap in zip(group.iterrows(), caps):
            ticker = str(stock["ticker"])
            ids.append(f"{ticker}|{ws}")
            labels.append(ticker)
            parents.append(ids[parent_i])
            values.append(budget * cap / caps.sum())
            customdata.append(finviz_chart_url(ticker))  # opened by the tap handler
            node_colors.append(_stock_change_color(stock["change"]))
            link = ticker
            if stock["is_uptrend"]:
                link = f"<b>{link}</b>"
            text.append(f"{link}<br>{_pct(stock['change'])}")
            hovertext.append(
                f"<b>{ticker}</b> {html.escape(str(stock['company'])) if pd.notna(stock['company']) else ''}<br>"
                f"Market Cap: {_format_market_cap(stock['market_cap'])}<br>"
                f"Change: {_pct(stock['change'])}<br>"
                f"Perf Week: {_pct(stock['perf_week'])}<br>"
                f"Perf YTD: {_pct(stock['perf_ytd'])}<br>"
                f"Uptrend: {'Yes' if stock['is_uptrend'] else 'No'}"
            )
            line_widths.append(3.0 if stock["is_uptrend"] else 0.5)

    # branchvalues="total": every parent must hold at least its children's sum.
    # Base nodes are ordered root -> sectors -> industries, so walk them backwards.
    child_sums: Dict[str, float] = {}
    for j in range(n_base, len(ids)):
        child_sums[parents[j]] = child_sums.get(parents[j], 0.0) + values[j]
    for i in reversed(range(n_base)):
        values[i] = max(values[i], child_sums.get(ids[i], 0.0))
        if parents[i]:
            child_sums[parents[i]] = child_sums.get(parents[i], 0.0) + values[i]

    fig.add_trace(
        go.Treemap(
            ids=ids,
            labels=labels,
            parents=parents,
            values=values,
            branchvalues="total",
            marker=dict(colors=node_colors, line=dict(width=line_widths, color="#222")),
            customdata=customdata,
            text=text,
            textinfo="text",
            hovertext=hovertext,
            hoverinfo="text",
            maxdepth=2,
            pathbar=dict(visible=True, side="top", thickness=22),
        )
    )
    fig.update_layout(
        title="Industry Heatmap",
        height=CHART_HEIGHT_HEATMAP,
        template="plotly_white",
        margin=dict(t=50, l=10, r=10, b=10),
    )
    return fig


def build_industry_heatmap(
    summary_df: pd.DataFrame,
    color_mode: str = "ratio",
    size_mode: str = "uniform",
    color_range: Optional[tuple] = None,
    drilldown: bool = False,
    constituents: Optional[pd.DataFrame] = None,
) -> go.Figure:
    """Build a treemap chart of all industries grouped by sector.

    Args:
        summary_df: DataFrame from build_industry_summary_with_sector().
            Expected columns: Industry, Ratio, 10MA, Trend, Slope, Status, _key, Sector, Total.
        color_mode: "ratio" for continuous RdYlGn colorscale, "status" for categorical colors.
        size_mode: "uniform" for equal cell sizes, "count" for stock count-based sizes.
        color_range: Optional (cmin, cmax) for the ratio colorscale. Defaults to the
            data's own range; pass the full-market range when showing a subset.
        drilldown: Phone view. Adds an "All Sectors" root, colors each sector tile by
            its stock-weighted ratio, and limits rendering to 2 levels so the first
            screen shows 11 readable sector tiles; tapping one zooms to its industries.
        constituents: Optional stock lists (`worksheet` + CONSTITUENT_COLUMNS). When
            given, each industry gets stock tiles sized by market cap, colored by the
            day's change and linked to the Finviz chart; see _heatmap_with_stocks().

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

    # Build treemap data: [root] -> sectors -> industries
    sectors = summary_df["Sector"].unique().tolist()

    labels = []
    parents = []
    values = []
    colors = []
    customdata = []
    text = []
    hovertext = []
    # Ratio colorscale value per node; NaN = no color (grey header)
    node_ratios = []

    sector_parent = ""
    if drilldown:
        labels.append(HEATMAP_ROOT_LABEL)
        parents.append("")
        values.append(0)
        colors.append("#cccccc")
        customdata.append("")
        text.append("")
        hovertext.append(HEATMAP_ROOT_LABEL)
        node_ratios.append(np.nan)
        sector_parent = HEATMAP_ROOT_LABEL

    # Add sector nodes
    for sector in sectors:
        labels.append(sector)
        parents.append(sector_parent)
        values.append(0)
        customdata.append("")
        if drilldown:
            # Sector tiles are what a phone sees first, so they carry color and value
            sector_ratio = _weighted_sector_ratio(summary_df[summary_df["Sector"] == sector])
            pct = f"{sector_ratio:.1%}" if pd.notna(sector_ratio) else "N/A"
            colors.append(STATUS_COLORS[_ratio_status(sector_ratio)])
            text.append(f"{sector}<br>{pct}")
            hovertext.append(f"<b>{sector}</b><br>Ratio (stock-weighted): {pct}<br>Tap to see industries")
            node_ratios.append(sector_ratio)
        else:
            colors.append("#cccccc")
            text.append("")
            hovertext.append(sector)
            node_ratios.append(np.nan)

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
        node_ratios.append(row["Ratio"] if pd.notna(row["Ratio"]) else 0)

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

    # Phone view: render root + sectors only; tapping a sector zooms to its industries
    maxdepth = 2 if drilldown else None

    if constituents is not None and not constituents.empty:
        return _heatmap_with_stocks(
            fig, summary_df, constituents, labels, parents, values, colors, customdata,
            text, hovertext, node_ratios, color_mode, color_range, drilldown,
        )

    if color_mode == "ratio":
        marker_values = node_ratios

        valid_ratios = summary_df["Ratio"].dropna()
        cmin = max(0, valid_ratios.min()) if len(valid_ratios) > 0 else 0
        cmax = valid_ratios.max() if len(valid_ratios) > 0 else 1
        if color_range is not None:
            # Keep colors comparable when the heatmap shows a filtered subset
            cmin, cmax = color_range
        elif drilldown:
            # Sector ratios cluster around 20-45%; a fixed 0-60% scale keeps the
            # first (sector) screen differentiated. Industries above 60% saturate green.
            cmin, cmax = 0, HEATMAP_DRILLDOWN_CMAX

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
                maxdepth=maxdepth,
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
                maxdepth=maxdepth,
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
