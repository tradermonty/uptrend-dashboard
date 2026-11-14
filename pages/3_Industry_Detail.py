"""Industry Detail Page — individual industry analysis."""

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from src.constants import INDUSTRIES, SECTORS, SECTOR_INDUSTRIES
from src.data_loader import cached_load_all_data
from src.data_processor import (
    get_current_status,
    get_industry_display_name,
    get_sector_display_name,
    get_sector_for_industry,
    default_start_date,
    filter_by_date_range,
    prepare_timeseries_csv,
)
from src.chart_builder import build_ratio_chart

st.set_page_config(page_title="Industry Detail", page_icon="🏭", layout="wide")
st.title("Industry Detail")

with st.sidebar:
    st.markdown("---")
    st.markdown(
        "Deep dive into individual industry uptrend ratios "
        "with trend direction, 10-day moving average, "
        "and overbought/oversold indicators."
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

# Navigation intent is separate from persistent, page-specific widget state.
# Apply the parent context before creating either widget; changing only index
# cannot override an existing selectbox or a filter hiding the requested target.
pending = st.session_state.get("selected_industry")
valid_target = isinstance(pending, str) and pending in INDUSTRIES
if "selected_industry" in st.session_state:
    if valid_target:
        target_parent = get_sector_for_industry(pending)
        st.session_state["industry_detail_sector_filter"] = target_parent if target_parent in SECTORS else None
        st.session_state["industry_detail_industry"] = pending
    else:
        st.session_state.pop("selected_industry")
        st.warning("Invalid industry navigation target. Choose an industry below.")

filter_state = st.session_state.get("industry_detail_sector_filter")
if filter_state is not None and (not isinstance(filter_state, str) or filter_state not in SECTORS):
    st.session_state["industry_detail_sector_filter"] = None
selected_sector = st.selectbox(
    "Filter by Sector", [None, *SECTORS],
    format_func=lambda key: "All Sectors" if key is None else get_sector_display_name(key),
    key="industry_detail_sector_filter",
)

available_industries = INDUSTRIES if selected_sector is None else SECTOR_INDUSTRIES.get(selected_sector, [])
industry_options = sorted(available_industries, key=get_industry_display_name)
if not industry_options:
    st.warning("No industries available.")
    st.stop()

industry_state = st.session_state.get("industry_detail_industry")
if not isinstance(industry_state, str) or industry_state not in industry_options:
    st.session_state["industry_detail_industry"] = industry_options[0]
selected_key = st.selectbox(
    "Select Industry", industry_options, format_func=get_industry_display_name,
    key="industry_detail_industry",
)
selected_display = get_industry_display_name(selected_key)
if (valid_target and selected_key == pending
        and selected_sector == (target_parent if target_parent in SECTORS else None)):
    st.session_state.pop("selected_industry", None)

# Show parent sector
parent_sector = get_sector_for_industry(selected_key)
if parent_sector:
    parent_display = get_sector_display_name(parent_sector)
    st.caption(f"Parent Sector: {parent_display}")

df = all_data.get(selected_key)

if df is None or df.empty:
    st.warning(f"No data available for {selected_display}.")
    st.stop()

# Status indicators
status = get_current_status(df)

col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric("Ratio", f"{status['ratio']:.1%}")
with col2:
    st.metric("10MA", f"{status['ratio_10ma']:.1%}" if status["ratio_10ma"] is not None else "N/A")
with col3:
    trend_icons = {"up": "🔼", "down": "🔽", "neutral": "➖"}
    st.metric("Trend", f"{trend_icons.get(status['trend'], '➖')} {status['trend'].title()}")
with col4:
    st.metric("Slope", f"{status['slope']:.4f}" if status["slope"] is not None else "N/A")
with col5:
    if status["is_overbought"]:
        st.metric("Status", "⚠️ Overbought")
    elif status["is_oversold"]:
        st.metric("Status", "⚠️ Oversold")
    else:
        st.metric("Status", "Normal")

# Date filter
min_date = df["date"].min().date()
max_date = df["date"].max().date()
default_start = default_start_date(min_date, max_date)
date_range = st.date_input(
    "Date Range",
    value=(default_start, max_date),
    min_value=min_date,
    max_value=max_date,
)

if date_range and len(date_range) == 2:
    start, end = date_range
    df_filtered = filter_by_date_range(df, start, end)
else:
    df_filtered = df

# Chart
fig = build_ratio_chart(df_filtered, title=f"{selected_display} Uptrend Ratio")
st.plotly_chart(fig, use_container_width=True)

# Data Download
st.markdown("---")
st.subheader("Data Download")
ts_csv = prepare_timeseries_csv(df_filtered)
st.download_button(
    f"Download {selected_display} Time Series",
    ts_csv.to_csv(index=False),
    f"{selected_key}_timeseries.csv",
    "text/csv",
)
