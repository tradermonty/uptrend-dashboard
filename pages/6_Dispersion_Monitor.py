"""Sector Dispersion Monitor — regime detection, signals, and sector ranking."""

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from src.data_loader import cached_load_sector_data
from src.indicator_calculator import (
    calculate_forward_returns,
    calculate_sector_dispersion,
    calculate_sector_edge,
    detect_dispersion_signals,
)
from src.chart_builder import build_dispersion_chart, build_regime_timeline_chart
from src.data_processor import (
    build_sector_ranking_table,
    default_start_date,
    filter_by_date_range,
    style_status_row,
)

st.set_page_config(page_title="Dispersion Monitor", page_icon="📡", layout="wide")
st.title("Sector Dispersion Monitor")

with st.sidebar:
    st.markdown("---")
    st.markdown(
        "Monitor cross-sectional dispersion of sector uptrend ratios. "
        "Detect convergence (capitulation) and divergence signals."
    )
    st.markdown("---")
    st.markdown(
        'Made with <img src="https://streamlit.io/images/brand/streamlit-mark-color.png" '
        'alt="Streamlit" height="16"> by '
        '<a href="https://github.com/tradermonty">@tradermonty</a>',
        unsafe_allow_html=True,
    )
    st.markdown(
        "[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-support-yellow"
        "?style=for-the-badge&logo=buy-me-a-coffee)](https://buymeacoffee.com/tradermonty)"
    )

# === Full-history calculation (before any date filter) ===
sector_data = cached_load_sector_data()
dispersion_df = calculate_sector_dispersion(sector_data)

# === Coverage and historical as-of ===
valid_df = dispersion_df.dropna(subset=["regime", "level_regime"])
current_available = not dispersion_df.empty and bool(dispersion_df.iloc[-1]["coverage_complete"])
if not dispersion_df.empty:
    observed = dispersion_df.iloc[-1]
    last_complete = str(valid_df.iloc[-1]["date"].date()) if not valid_df.empty else "none"
    st.caption(
        f"Latest observed: {observed['date'].date()} | "
        f"Coverage: {observed['sector_count']}/{observed['expected_sector_count']} | "
        f"Last complete as-of: {last_complete}"
    )
    if not current_available:
        st.warning("Current dispersion signals unavailable: incomplete sector coverage. "
                   "Charts and statistics below describe historical complete observations.")

# === Data sufficiency guard ===
if valid_df.empty:
    st.warning(
        "Insufficient dispersion data. "
        "Monitoring features will become available once enough history accumulates."
    )
    st.stop()

# === Valid data — normal processing ===
signals = detect_dispersion_signals(dispersion_df)
market_df = sector_data.get("all")
forward_stats = (
    calculate_forward_returns(dispersion_df, market_df)
    if market_df is not None and not market_df.empty
    else None
)
sector_edge = calculate_sector_edge(dispersion_df, sector_data)
latest_valid = valid_df.iloc[-1]
current_regime = latest_valid["regime"] if current_available else None
current_level = latest_valid["level_regime"] if current_available else None

if current_available:
    # --- 1. Signal Banner ---
    active_signals = [s for s in signals if s.active]
    if not active_signals:
        st.success(f"NORMAL — Sector dispersion within normal range "
                   f"(σ={latest_valid['dispersion']:.3f}, mean={latest_valid['mean_ratio']:.1%})")
    else:
        for sig in active_signals:
            if sig.signal_id == "CAPITULATION":
                st.error(
                    f"CAPITULATION ACTIVE — All sectors converged at low levels "
                    f"(σ={sig.dispersion:.3f}, mean={sig.mean_ratio:.1%})"
                )
            elif sig.signal_id == "DIVERGENCE_WARNING":
                st.warning(
                    f"DIVERGENCE WARNING — Sector dispersion expanding "
                    f"(σ={sig.dispersion:.3f})"
                )
            elif sig.signal_id == "BREAKOUT_VELOCITY":
                st.info(
                    f"BREAKOUT VELOCITY — Convergence breakout signal "
                    f"(σ={sig.dispersion:.3f})"
                )

    # --- Status metrics ---
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Dispersion (σ)", f"{latest_valid['dispersion']:.4f}")
    with col2:
        st.metric("Mean Ratio", f"{latest_valid['mean_ratio']:.1%}")
    with col3:
        regime_emoji = {"converged": "🟢", "normal": "🔵", "diverged": "🔴"}
        st.metric("Regime", f"{regime_emoji.get(current_regime, '')} {current_regime.title()}")
    with col4:
        st.metric("Level", current_level.title())

# === Date filter (chart/table display only) ===
with st.sidebar:
    if not dispersion_df.empty and "date" in dispersion_df.columns:
        min_date = dispersion_df["date"].min()
        max_date = dispersion_df["date"].max()
        if hasattr(min_date, "date"):
            min_date = min_date.date()
            max_date = max_date.date()
        default_start = default_start_date(min_date, max_date)
        date_range = st.date_input(
            "Date Range",
            value=(default_start, max_date),
            min_value=min_date,
            max_value=max_date,
        )
    else:
        date_range = None

if date_range and len(date_range) == 2:
    start, end = date_range
    filtered_df = filter_by_date_range(
        dispersion_df.assign(date=lambda d: d["date"] if hasattr(d["date"].iloc[0], "date") else d["date"]),
        start, end,
    ) if hasattr(dispersion_df["date"].iloc[0], "date") else dispersion_df
else:
    filtered_df = dispersion_df

# --- 2. Dispersion Chart ---
st.subheader("Dispersion Chart")
fig = build_dispersion_chart(filtered_df)
st.plotly_chart(fig, use_container_width=True)

# --- 3. Regime Timeline ---
st.subheader("Regime Timeline")
fig_timeline = build_regime_timeline_chart(filtered_df)
st.plotly_chart(fig_timeline, use_container_width=True)

# --- 4. Sector Ranking Table ---
st.subheader("Sector Ranking")
if not current_available:
    st.info("Current regime-based sector ranking is unavailable until all sectors report.")
else:
    if current_regime == "converged" and current_level == "low":
        st.caption("CAPITULATION regime: Ranked by historical recovery leaders")
    elif current_regime == "diverged":
        st.caption("DIVERGENCE regime: Ranked by historical defensive leaders")
    else:
        st.caption("NORMAL regime: Ranked by current ratio")

    ranking = build_sector_ranking_table(sector_data, current_regime, current_level, sector_edge)
    if not ranking.empty:
        st.dataframe(
            ranking.style
            .format({
                "Current Ratio": "{:.1%}",
                "10MA": "{:.1%}",
                "Historical Edge": lambda x: f"{x:+.4f}" if x is not None and x == x else "N/A",
            }),
            use_container_width=True,
            hide_index=True,
        )

# --- 5. Historical Stats (Expander) ---
with st.expander("Historical Stats (Regime Transition Events)"):
    if forward_stats is not None and not forward_stats.empty:
        st.caption("Samples are regime transition days only (consecutive same-regime days count as 1 event)")
        st.dataframe(
            forward_stats.style.format({
                "mean_return": "{:+.4f}",
                "win_rate": "{:.1%}",
                "count": "{:.0f}",
            }),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Forward return stats will appear once enough data accumulates.")

# --- 6. Regime Action Guide ---
st.subheader("Regime Action Guide")
st.caption("For decision support only — not investment advice. Always apply your own judgment.")

_REGIME_GUIDE = {
    ("converged", "low"): {
        "label": "Converged + Low (Capitulation)",
        "type": "success",
        "actions": [
            "Watch for reversal candidates — historically strong bounce zone",
            "Avoid initiating new short positions",
            "Prioritize sector_edge top-ranked sectors for early entry",
            "Position sizing: start small, scale in on confirmation",
        ],
    },
    ("converged", "mid"): {
        "label": "Converged + Mid",
        "type": "success",
        "actions": [
            "Risk-on bias — sectors tightly grouped and rising",
            "Favor trend-following in leading sectors",
            "Standard position sizing",
        ],
    },
    ("converged", "high"): {
        "label": "Converged + High",
        "type": "success",
        "actions": [
            "Risk-on bias — broad participation at elevated levels",
            "Favor momentum in strongest sectors",
            "Watch for divergence onset as a potential distribution signal",
        ],
    },
    ("normal", None): {
        "label": "Normal",
        "type": "info",
        "actions": [
            "Standard operations — follow individual stock/sector signals",
            "Standard position sizing, no regime-driven adjustment needed",
            "Monitor for regime transitions at P25/P75 boundaries",
        ],
    },
    ("diverged", None): {
        "label": "Diverged",
        "type": "error",
        "actions": [
            "Tighten new long entry criteria — selectivity over aggression",
            "Reduce position sizes or add hedges",
            "Favor defensive sectors and relative strength leaders",
            "Energy & Utilities have historically tended to outperform in this regime",
        ],
    },
}

# Current regime highlight
current_key = (current_regime, current_level)
# Fall back to (regime, None) for normal/diverged which don't vary by level
guide = _REGIME_GUIDE.get(current_key) or _REGIME_GUIDE.get((current_regime, None))

if guide:
    action_text = "\n".join(f"- {a}" for a in guide["actions"])
    display_fn = {"error": st.error, "warning": st.warning, "info": st.info, "success": st.success}
    display_fn.get(guide["type"], st.info)(
        f"**Current: {guide['label']}**\n\n{action_text}"
    )

# Full regime reference table
with st.expander("All Regime Actions (Reference)"):
    for key, g in _REGIME_GUIDE.items():
        is_current = (key == current_key) or (
            key == (current_regime, None) and current_key not in _REGIME_GUIDE
        )
        badge = " `CURRENT`" if is_current else ""
        st.markdown(f"**{g['label']}**{badge}")
        for a in g["actions"]:
            st.markdown(f"- {a}")
