"""Sector Detail Page — individual sector analysis."""

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from src.constants import SECTORS, SECTOR_INDUSTRIES
from src.data_loader import cached_load_all_data, cached_load_manifest
from src.data_processor import (
    get_current_status,
    get_sector_display_name,
    default_start_date,
    filter_by_date_range,
    prepare_timeseries_csv,
    build_industry_summary,
    order_stale_last,
    split_stale_rows,
    stale_rows_caption,
    style_status_row,
)
from src.chart_builder import build_ratio_chart, build_industry_summary_chart
from src.collection_manifest import coverage_caption
from src.kpi_cards import KpiCard, render_kpi_cards, status_card, trend_card
from src.mobile_ui import display_years, inject_mobile_css, is_mobile_client, mobile_columns, show_chart

st.set_page_config(page_title="Sector Detail", page_icon="🔍", layout="wide")
inject_mobile_css()
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

render_kpi_cards([
    KpiCard("Ratio", f"{status['ratio']:.1%}"),
    KpiCard("10MA", f"{status['ratio_10ma']:.1%}" if status["ratio_10ma"] is not None else "N/A"),
    trend_card(status["trend"]),
    KpiCard("Slope", f"{status['slope']:.4f}" if status["slope"] is not None else "N/A"),
    status_card(status),
])

# Date filter
min_date = df["date"].min().date()
max_date = df["date"].max().date()
default_start = default_start_date(min_date, max_date, years=display_years(is_mobile_client()))
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
show_chart(fig, mobile_height=420)

# Industries in this Sector
st.markdown("---")
st.subheader(f"Industries in {selected_display}")

industry_keys = SECTOR_INDUSTRIES.get(selected_key, [])

# Latest collection outcome (Issue #6), counted over this sector's industries only
_coverage = coverage_caption(cached_load_manifest(), worksheets=industry_keys,
                             label=f"{selected_display} industries")
if _coverage:
    st.caption(_coverage)

has_industry_data = any(
    k in all_data and not all_data[k].empty for k in industry_keys
)

if has_industry_data:
    ind_summary = order_stale_last(build_industry_summary(all_data, sector_key=selected_key))
    if not ind_summary.empty:
        # Stale industries are left out of the ranking chart; the table still lists them
        fresh_ind, stale_ind = split_stale_rows(ind_summary)
        if not stale_ind.empty:
            st.caption(stale_rows_caption(stale_ind, "Industry") + ".")
        fig_ind = build_industry_summary_chart(fresh_ind, sector_name=selected_display)
        ind_chart_event = show_chart(
            fig_ind, on_select="rerun", key="industry_summary_chart",
        )

        if ind_chart_event and ind_chart_event.selection and ind_chart_event.selection.points:
            point = ind_chart_event.selection.points[0]
            customdata = point.get("customdata")
            if customdata:
                st.session_state["selected_industry"] = customdata
                st.switch_page("views/3_Industry_Detail.py")

        ind_table_event = st.dataframe(
            ind_summary.drop(columns=["_key"]).style
            .format({"Ratio": "{:.1%}", "10MA": "{:.1%}", "Slope": "{:.4f}"}, na_rep="N/A")
            .apply(style_status_row, axis=1),
            width="stretch",
            hide_index=True,
            column_order=mobile_columns(ind_summary.columns, is_mobile_client()),
            on_select="rerun",
            selection_mode="single-row",
            key="industry_table",
        )

        if ind_table_event and ind_table_event.selection and ind_table_event.selection.rows:
            selected_ind_row = ind_table_event.selection.rows[0]
            selected_ind_key = ind_summary.iloc[selected_ind_row]["_key"]
            st.session_state["selected_industry"] = selected_ind_key
            st.switch_page("views/3_Industry_Detail.py")
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
