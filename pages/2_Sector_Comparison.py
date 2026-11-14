"""Sector Comparison Page — overlay multiple sector ratios."""

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from src.constants import SECTORS
from src.data_loader import cached_load_sector_data
from src.data_processor import get_sector_display_name
from src.comparison_filters import comparison_date_filter
from src.chart_builder import build_sector_comparison_chart
from src.indicator_calculator import calculate_sector_dispersion

st.set_page_config(page_title="Sector Comparison", page_icon="📊", layout="wide")
st.title("Sector Comparison")

with st.sidebar:
    st.markdown("---")
    st.markdown(
        "Compare uptrend ratios across multiple sectors side by side. "
        "Identify which sectors are leading or lagging the market."
    )

    st.markdown("---")
    st.page_link("pages/6_Dispersion_Monitor.py", label="📡 Dispersion Monitor")
    st.markdown("---")
    st.markdown(
        'Made with <img src="https://streamlit.io/images/brand/streamlit-mark-color.png" alt="Streamlit" height="16"> by <a href="https://github.com/tradermonty">@tradermonty</a>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-support-yellow?style=for-the-badge&logo=buy-me-a-coffee)](https://buymeacoffee.com/tradermonty)'
    )


def load_data():
    return cached_load_sector_data()


all_data = load_data()

# Dispersion gauge in sidebar
with st.sidebar:
    dispersion_df = calculate_sector_dispersion(all_data)
    valid_disp = (
        dispersion_df.dropna(subset=["regime", "level_regime"])
        if not dispersion_df.empty
        else dispersion_df
    )
    if not dispersion_df.empty:
        observed = dispersion_df.iloc[-1]
        last_complete = str(valid_disp.iloc[-1]["date"].date()) if not valid_disp.empty else "none"
        st.caption(
            f"Latest observed: {observed['date'].date()} | "
            f"Coverage: {observed['sector_count']}/{observed['expected_sector_count']} | "
            f"Last complete as-of: {last_complete}"
        )
    if not dispersion_df.empty and dispersion_df.iloc[-1]["coverage_complete"]:
        latest = dispersion_df.iloc[-1]
        regime_icons = {"converged": "🟢", "normal": "🔵", "diverged": "🔴"}
        st.markdown(
            f"**Dispersion**: σ={latest['dispersion']:.3f} "
            f"{regime_icons.get(latest['regime'], '')}"
        )
    else:
        st.markdown("**Dispersion**: N/A (insufficient sector coverage)")

# Multi-select sectors
sector_names = {get_sector_display_name(s): s for s in SECTORS}
selected_display = st.multiselect(
    "Select Sectors",
    options=list(sector_names.keys()),
    default=list(sector_names.keys()),
)

selected_keys = [sector_names[name] for name in selected_display]

if not selected_keys:
    st.warning("Please select at least one sector.")
    st.stop()

filtered_data = comparison_date_filter(
    all_data, selected_keys, get_sector_display_name, "sector_comparison_dates"
)

# Display mode toggle
display_mode = st.radio(
    "Display Mode",
    options=["Smoothed (10MA)", "Raw Ratio"],
    horizontal=True,
)
use_ma = display_mode == "Smoothed (10MA)"

# Chart
fig = build_sector_comparison_chart(filtered_data, selected_sectors=selected_keys, use_ma=use_ma)
st.plotly_chart(fig, use_container_width=True)
