"""Uptrend Ratio page — full market overview (default page)."""

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from src.data_loader import cached_load_sector_data
from src.data_processor import (
    get_current_status,
    build_sector_summary,
    default_start_date,
    filter_by_date_range,
    prepare_timeseries_csv,
    style_status_row,
)
from src.chart_builder import build_ratio_chart, build_sector_summary_chart
from src.page_footer import render_ai_skill_note, render_explainer_link
from src.kpi_cards import KpiCard, regime_card, render_kpi_cards, status_card, trend_card
from src.mobile_ui import display_years, inject_mobile_css, is_mobile_client, mobile_columns, show_chart

st.set_page_config(
    page_title="US Market Uptrend Ratio",
    page_icon="📈",
    layout="wide",
)
inject_mobile_css()

st.title("US Market Uptrend Stock Ratio")


def load_data():
    """Load sector data from SQLite (cached cross-page)."""
    return cached_load_sector_data()


# Sidebar
with st.sidebar:
    st.header("Settings")
    if st.button("Refresh Data"):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")
    st.markdown(
        "Tracks the percentage of US stocks in an uptrend "
        "across the full market and 11 sectors. "
        'Data is collected daily from <a href="https://finviz.com/?affilId=279192576" target="_blank" rel="noopener noreferrer">Finviz</a>.',
        unsafe_allow_html=True,
    )

    st.markdown("---")
    st.markdown(
        'Made with <img src="https://streamlit.io/images/brand/streamlit-mark-color.png" alt="Streamlit" height="16"> by <a href="https://github.com/tradermonty">@tradermonty</a>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-support-yellow?style=for-the-badge&logo=buy-me-a-coffee)](https://buymeacoffee.com/tradermonty)'
    )

# Main content
all_data = load_data()
df_all = all_data.get("all")

if df_all is None or df_all.empty:
    st.warning("No data available. Import data using import_excel.py first.")
    st.stop()

# Current status indicators
status = get_current_status(df_all)

render_kpi_cards([
    KpiCard("Current Ratio", f"{status['ratio']:.1%}"),
    KpiCard("10MA", f"{status['ratio_10ma']:.1%}" if status["ratio_10ma"] is not None else "N/A"),
    trend_card(status["trend"]),
    status_card(status),
])

st.caption(f"Last updated: {status['date']}")
render_explainer_link()

# Date filter lives in the main area (not the sidebar) so it is reachable on phones
min_date = df_all["date"].min().date()
max_date = df_all["date"].max().date()
date_range = st.date_input(
    "Date Range",
    value=(default_start_date(min_date, max_date, years=display_years(is_mobile_client())), max_date),
    min_value=min_date,
    max_value=max_date,
)
if date_range and len(date_range) == 2:
    start, end = date_range
    df_filtered = filter_by_date_range(df_all, start, end)
else:
    df_filtered = df_all

# Full market ratio chart
st.subheader("Full Market Ratio")
fig = build_ratio_chart(df_filtered, title="US Market Uptrend Ratio")
show_chart(fig, mobile_height=420)

# Sector summary
st.subheader("Sector Summary")
summary = build_sector_summary(all_data)

fig_summary = build_sector_summary_chart(summary)
event = show_chart(fig_summary, on_select="rerun", key="sector_summary")

if event and event.selection and event.selection.points:
    point = event.selection.points[0]
    customdata = point.get("customdata")
    if customdata:
        st.session_state["selected_sector"] = customdata
        st.switch_page("views/1_Sector_Detail.py")

table_event = st.dataframe(
    summary.drop(columns=["_key"]).style
    .format({"Ratio": "{:.1%}", "10MA": "{:.1%}", "Slope": "{:.4f}"})
    .apply(style_status_row, axis=1),
    width="stretch",
    hide_index=True,
    column_order=mobile_columns(summary.columns, is_mobile_client()),
    on_select="rerun",
    selection_mode="single-row",
    key="sector_table",
)

if table_event and table_event.selection and table_event.selection.rows:
    selected_row = table_event.selection.rows[0]
    selected_key = summary.iloc[selected_row]["_key"]
    st.session_state["selected_sector"] = selected_key
    st.switch_page("views/1_Sector_Detail.py")

# Data Download
st.markdown("---")
st.subheader("Data Download")

col_dl1, col_dl2 = st.columns(2)
with col_dl1:
    ts_csv = prepare_timeseries_csv(df_filtered)
    st.download_button(
        "Download Ratio Time Series",
        ts_csv.to_csv(index=False),
        "uptrend_ratio_timeseries.csv",
        "text/csv",
    )
with col_dl2:
    st.download_button(
        "Download Sector Summary",
        summary.drop(columns=["_key"]).to_csv(index=False),
        "sector_summary.csv",
        "text/csv",
    )

# AI analysis: link to the Uptrend Analyzer skill (same note as the Market Breadth page)
render_ai_skill_note()
