"""Industry Comparison Page — overlay multiple industry ratios."""

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from src.constants import SECTORS, SECTOR_INDUSTRIES, MAX_INDUSTRY_COMPARISON
from src.data_loader import cached_load_all_data
from src.data_processor import (
    get_sector_display_name,
    get_industry_display_name,
)
from src.comparison_filters import comparison_date_filter
from src.chart_builder import build_industry_comparison_chart

st.set_page_config(page_title="Industry Comparison", page_icon="📊", layout="wide")
st.title("Industry Comparison")

with st.sidebar:
    st.markdown("---")
    st.markdown(
        "Compare uptrend ratios across multiple industries side by side. "
        "Use Within Sector mode for focused analysis or Cross-Sector for broader comparison."
    )

    st.markdown("---")
    st.markdown(
        'Made with <img src="https://streamlit.io/images/brand/streamlit-mark-color.png" alt="Streamlit" height="16"> by <a href="https://github.com/tradermonty">@tradermonty</a>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-support-yellow?style=for-the-badge&logo=buy-me-a-coffee)](https://buymeacoffee.com/tradermonty)'
    )


def load_data():
    return cached_load_all_data()


all_data = load_data()

# Compare mode
compare_mode = st.radio(
    "Compare Mode",
    ["Within Sector", "Cross-Sector"],
    horizontal=True,
)

if compare_mode == "Within Sector":
    # Select sector, then show all its industries
    sector_names = {get_sector_display_name(s): s for s in SECTORS}
    selected_sector_display = st.selectbox("Select Sector", list(sector_names.keys()))
    sector_key = sector_names[selected_sector_display]

    industry_keys = SECTOR_INDUSTRIES.get(sector_key, [])
    industry_names = {get_industry_display_name(k): k for k in industry_keys}

    selected_display = st.multiselect(
        "Select Industries",
        options=sorted(industry_names.keys()),
        default=sorted(industry_names.keys()),
    )
    selected_keys = [industry_names[name] for name in selected_display]

else:
    # Cross-sector: flat list with sector prefix
    industry_options = {}
    for sec in SECTORS:
        sec_display = get_sector_display_name(sec)
        for ind in SECTOR_INDUSTRIES.get(sec, []):
            ind_display = get_industry_display_name(ind)
            label = f"{sec_display} / {ind_display}"
            industry_options[label] = ind

    selected_labels = st.multiselect(
        f"Select Industries (max {MAX_INDUSTRY_COMPARISON})",
        options=sorted(industry_options.keys()),
        max_selections=MAX_INDUSTRY_COMPARISON,
    )
    selected_keys = [industry_options[label] for label in selected_labels]

if not selected_keys:
    st.warning("Please select at least one industry.")
    st.stop()

filtered_data = comparison_date_filter(
    all_data, selected_keys, get_industry_display_name, "industry_comparison_dates"
)

# Display mode toggle
display_mode = st.radio(
    "Display Mode",
    options=["Smoothed (10MA)", "Raw Ratio"],
    horizontal=True,
)
use_ma = display_mode == "Smoothed (10MA)"

# Chart
fig = build_industry_comparison_chart(filtered_data, selected_industries=selected_keys, use_ma=use_ma)
st.plotly_chart(fig, use_container_width=True)
