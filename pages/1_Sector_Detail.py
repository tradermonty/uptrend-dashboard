"""Sector Detail Page — individual sector analysis."""

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from src.constants import SECTORS, SECTOR_INDUSTRIES
from src.data_loader import cached_load_all_data
from src.data_processor import (
    get_current_status,
    get_sector_display_name,
    default_start_date,
    filter_by_date_range,
    prepare_timeseries_csv,
    build_industry_summary,
    style_status_row,
)
from src.chart_builder import build_ratio_chart, build_industry_summary_chart

st.set_page_config(page_title="Sector Detail", page_icon="🔍", layout="wide")
st.title("Sector Detail")

with st.sidebar:
    st.markdown("---")
    st.markdown(
        "Deep dive into individual sector uptrend ratios "
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

# Apply navigation before the stable selector widget is instantiated.
pending = st.session_state.get("selected_sector")
valid_target = isinstance(pending, str) and pending in SECTORS
if "selected_sector" in st.session_state:
    if valid_target:
        st.session_state["sector_detail_sector"] = pending
    else:
        st.session_state.pop("selected_sector")
        st.warning("Invalid sector navigation target. Choose a sector below.")

sector_state = st.session_state.get("sector_detail_sector")
if not isinstance(sector_state, str) or sector_state not in SECTORS:
    st.session_state["sector_detail_sector"] = SECTORS[0]
selected_key = st.selectbox(
    "Select Sector", SECTORS, format_func=get_sector_display_name, key="sector_detail_sector",
)
selected_display = get_sector_display_name(selected_key)
if valid_target and selected_key == pending:
    st.session_state.pop("selected_sector", None)

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

# Industries in this Sector
st.markdown("---")
st.subheader(f"Industries in {selected_display}")

industry_keys = SECTOR_INDUSTRIES.get(selected_key, [])
has_industry_data = any(
    k in all_data and not all_data[k].empty for k in industry_keys
)

if has_industry_data:
    ind_summary = build_industry_summary(all_data, sector_key=selected_key)
    if not ind_summary.empty:
        fig_ind = build_industry_summary_chart(ind_summary, sector_name=selected_display)
        ind_chart_event = st.plotly_chart(
            fig_ind, use_container_width=True, on_select="rerun", key="industry_summary_chart",
        )

        if ind_chart_event and ind_chart_event.selection and ind_chart_event.selection.points:
            point = ind_chart_event.selection.points[0]
            customdata = point.get("customdata")
            if customdata:
                st.session_state["selected_industry"] = customdata
                st.switch_page("pages/3_Industry_Detail.py")

        ind_table_event = st.dataframe(
            ind_summary.drop(columns=["_key"]).style
            .format({"Ratio": "{:.1%}", "10MA": "{:.1%}", "Slope": "{:.4f}"}, na_rep="N/A")
            .apply(style_status_row, axis=1),
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="industry_table",
        )

        if ind_table_event and ind_table_event.selection and ind_table_event.selection.rows:
            selected_ind_row = ind_table_event.selection.rows[0]
            selected_ind_key = ind_summary.iloc[selected_ind_row]["_key"]
            st.session_state["selected_industry"] = selected_ind_key
            st.switch_page("pages/3_Industry_Detail.py")
else:
    st.info("No industry data available for this sector yet.")

# Data Download
st.markdown("---")
st.subheader("Data Download")
col_dl1, col_dl2 = st.columns(2)
with col_dl1:
    ts_csv = prepare_timeseries_csv(df_filtered)
    st.download_button(
        f"Download {selected_display} Time Series",
        ts_csv.to_csv(index=False),
        f"{selected_key}_timeseries.csv",
        "text/csv",
    )
with col_dl2:
    if has_industry_data and not ind_summary.empty:
        st.download_button(
            f"Download {selected_display} Industry Summary",
            ind_summary.drop(columns=["_key"]).to_csv(index=False),
            f"{selected_key}_industry_summary.csv",
            "text/csv",
        )
