"""Industry Heatmap Page — treemap overview of all industries."""

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from src.data_loader import cached_load_all_constituents, cached_load_all_data
from src.data_processor import (
    build_industry_summary_with_sector,
    style_status_row,
)
from src.chart_builder import build_industry_heatmap
from src.kpi_cards import KpiCard, render_kpi_cards
from src.mobile_ui import inject_mobile_css, is_mobile_client, mobile_columns, show_chart

st.set_page_config(page_title="Industry Heatmap", page_icon="🗺️", layout="wide")
inject_mobile_css()
st.title("Industry Heatmap")

with st.sidebar:
    st.markdown("---")
    st.markdown(
        "Treemap overview of all 149 industries grouped by sector. "
        "Color indicates uptrend ratio strength."
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

# Controls
col_color, col_size = st.columns(2)
with col_color:
    color_mode = st.radio(
        "Color Mode",
        ["Ratio", "Trend Status"],
        horizontal=True,
    )
with col_size:
    size_mode = st.radio(
        "Size Mode",
        ["Uniform", "Stock Count"],
        horizontal=True,
    )

color_mode_key = "ratio" if color_mode == "Ratio" else "status"
size_mode_key = "uniform" if size_mode == "Uniform" else "count"

# Build summary data
summary = build_industry_summary_with_sector(all_data)

if summary.empty:
    st.warning("No industry data available.")
    st.stop()

# KPI metrics
total_count = len(summary)
status_counts = summary["Status"].value_counts()
trend_counts = summary["Trend"].value_counts()

render_kpi_cards([
    KpiCard("Oversold", f"{status_counts.get('Oversold', 0) / total_count:.1%}", "oversold"),
    KpiCard("Normal", f"{status_counts.get('Normal', 0) / total_count:.1%}", "normal"),
    KpiCard("Overbought", f"{status_counts.get('Overbought', 0) / total_count:.1%}", "overbought"),
    KpiCard("Trend Up", f"{trend_counts.get('Up', 0) / total_count:.1%}", "up"),
    KpiCard("Trend Down", f"{trend_counts.get('Down', 0) / total_count:.1%}", "down"),
])

# Treemap (display only)
# 149 tiles are unreadable on a phone: phones first see 11 sector tiles and
# tap one to zoom into its industries (Plotly treemap drilldown).
is_mobile = is_mobile_client()
constituents = cached_load_all_constituents()
has_stocks = not constituents.empty
if is_mobile:
    st.caption(
        "Tap a sector to see its industries"
        + (", then an industry to see its stocks (size = market cap, color = today's change; "
           "bold outline = uptrend). Tap a ticker to open its Finviz chart" if has_stocks else "")
        + ". Tap the bar at the top to go back."
    )
elif has_stocks:
    st.caption(
        "Click an industry to see its stocks (size = market cap, color = today's change; "
        "bold outline = uptrend). Click a ticker to open its Finviz chart."
    )
fig = build_industry_heatmap(
    summary, color_mode=color_mode_key, size_mode=size_mode_key, drilldown=is_mobile,
    constituents=constituents if has_stocks else None,
)
show_chart(fig, mobile_height=560)

# Industry Summary Table
st.markdown("---")
st.subheader("Industry Summary")
st.caption("Click a row to open the industry with its stock list.")

display_df = summary.sort_values(["Sector", "Industry"]).reset_index(drop=True)

table_event = st.dataframe(
    display_df.drop(columns=["_key", "Total"]).style
    .format({"Ratio": "{:.1%}", "10MA": "{:.1%}", "Slope": "{:.4f}"}, na_rep="N/A")
    .apply(style_status_row, axis=1),
    width="stretch",
    hide_index=True,
    column_order=mobile_columns(display_df.columns, is_mobile_client()),
    on_select="rerun",
    selection_mode="single-row",
    key="heatmap_industry_table",
)

if table_event and table_event.selection and table_event.selection.rows:
    selected_row = table_event.selection.rows[0]
    selected_key = display_df.iloc[selected_row]["_key"]
    st.session_state["selected_industry"] = selected_key
    st.switch_page("pages/3_Industry_Detail.py")
