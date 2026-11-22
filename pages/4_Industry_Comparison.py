"""Industry Comparison Page — overlay multiple industry ratios."""

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from src.constants import SECTORS, SECTOR_INDUSTRIES, MAX_INDUSTRY_COMPARISON
from src.data_loader import cached_load_all_data
from src.data_processor import (
    get_sector_display_name,
    get_industry_display_name,
    default_start_date,
    filter_by_date_range,
)
from src.chart_builder import build_industry_comparison_chart
from src.mobile_ui import display_years, inject_mobile_css, is_mobile_client, mobile_columns, show_chart

st.set_page_config(page_title="Industry Comparison", page_icon="📊", layout="wide")
inject_mobile_css()
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

# Date filter
first_df = next((all_data[k] for k in selected_keys if k in all_data and not all_data[k].empty), None)
if first_df is not None:
    min_date = first_df["date"].min().date()
    max_date = first_df["date"].max().date()
    default_start = default_start_date(min_date, max_date, years=display_years(is_mobile_client()))
    date_range = st.date_input(
        "Date Range",
        value=(default_start, max_date),
        min_value=min_date,
        max_value=max_date,
    )

    if date_range and len(date_range) == 2:
        start, end = date_range
        filtered_data = {}
        for key in selected_keys:
            df = all_data.get(key)
            if df is not None:
                filtered_data[key] = filter_by_date_range(df, start, end)
    else:
        filtered_data = {k: all_data[k] for k in selected_keys if k in all_data}
else:
    filtered_data = {k: all_data[k] for k in selected_keys if k in all_data}

if not filtered_data:
    st.warning("No data available for the selected industries.")
    st.stop()

# Display mode toggle
display_mode = st.radio(
    "Display Mode",
    options=["Smoothed (10MA)", "Raw Ratio"],
    horizontal=True,
)
use_ma = display_mode == "Smoothed (10MA)"

# Chart
fig = build_industry_comparison_chart(filtered_data, selected_industries=selected_keys, use_ma=use_ma)
show_chart(fig, mobile_height=520, mobile_hide_annotations=True)
