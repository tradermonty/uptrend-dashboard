"""Mobile-friendly UI helpers shared by all pages.

Streamlit cannot switch Plotly layouts with CSS, so the approach is split:
- Page chrome (title size, padding, metric grid) adapts via a CSS media query.
- Plotly figures get a compact layout only when the request comes from a phone,
  detected from the User-Agent header.
"""

import re
from typing import Optional

import plotly.graph_objects as go

from src.constants import DEFAULT_DISPLAY_YEARS, MOBILE_DISPLAY_YEARS

MOBILE_BREAKPOINT_PX = 640
MOBILE_CHART_HEIGHT = 380

_MOBILE_UA_PATTERN = re.compile(r"iPhone|iPod|Android.*Mobile|Mobile Safari|Windows Phone", re.I)

# Shared Plotly config: drop buttons that are rarely used and crowd the toolbar.
PLOTLY_CONFIG = {
    "displaylogo": False,
    "modeBarButtonsToRemove": [
        "lasso2d",
        "select2d",
        "zoomIn2d",
        "zoomOut2d",
        "autoScale2d",
        "toImage",
    ],
}


def is_mobile_user_agent(user_agent: Optional[str]) -> bool:
    """Return True when the User-Agent belongs to a phone-sized device."""
    if not user_agent:
        return False
    return bool(_MOBILE_UA_PATTERN.search(user_agent))


def build_mobile_css() -> str:
    """Return a <style> block that compacts the page on small screens."""
    bp = MOBILE_BREAKPOINT_PX
    return f"""<style>
@media (max-width: {bp}px) {{
  [data-testid="stMainBlockContainer"], .block-container {{
    padding: 2.5rem 0.75rem 3rem 0.75rem !important;
  }}
  h1 {{ font-size: 1.6rem !important; line-height: 1.25 !important; padding-bottom: 0.25rem !important; }}
  h2 {{ font-size: 1.3rem !important; }}
  h3 {{ font-size: 1.15rem !important; }}
  /* Keep metric rows as a 2-column grid instead of one tall stack */
  [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) {{
    flex-direction: row !important;
    flex-wrap: wrap !important;
    gap: 0.5rem 1rem !important;
  }}
  [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > [data-testid="stColumn"] {{
    flex: 1 1 calc(50% - 0.5rem) !important;
    width: calc(50% - 0.5rem) !important;
    min-width: calc(50% - 0.5rem) !important;
  }}
  [data-testid="stMetric"] {{
    background: rgba(128, 128, 128, 0.08);  /* readable in light and dark themes */
    border-radius: 0.5rem;
    padding: 0.5rem 0.75rem;
  }}
  [data-testid="stMetricValue"] {{ font-size: 1.35rem !important; }}
  [data-testid="stMetricLabel"] p {{ font-size: 0.8rem !important; }}
}}
</style>"""


def apply_mobile_layout(
    fig: go.Figure,
    height: Optional[int] = None,
    hide_annotations: bool = False,
) -> go.Figure:
    """Compact a Plotly figure for phone screens (mutates and returns fig).

    dragmode=False lets a finger drag scroll the page instead of box-zooming;
    tap-to-hover still works. Tight margins plus axis automargin give the plot
    area most of the screen width without clipping tick labels.
    """
    fig.update_layout(
        dragmode=False,
        margin=dict(l=8, r=8, t=56, b=8),
        font=dict(size=11),
        legend=dict(orientation="h", font=dict(size=10)),
    )
    # Touch title only when one exists: a font-only title renders as "undefined"
    if fig.layout.title.text:
        fig.update_layout(title_font_size=14)
    # Axis titles ("Ratio", "Date") cost ~10% of a phone's width; ticks are self-explanatory
    fig.update_xaxes(automargin=True, tickangle=0, nticks=5, title_text=None)
    fig.update_yaxes(automargin=True, title_text=None)
    # Treemap colorbar on the right steals width; lay it flat under the plot
    fig.update_traces(
        marker_colorbar=dict(orientation="h", thickness=10, y=-0.08, len=0.9),
        textfont=dict(size=12),
        selector=dict(type="treemap"),
    )
    if hide_annotations:
        fig.layout.annotations = ()
    if height is not None:
        fig.update_layout(height=height)
    return fig


# Columns worth the width on a phone; the rest are available on desktop
MOBILE_TABLE_COLUMNS = ("Sector", "Industry", "Ratio", "Current Ratio", "Trend", "Status", "Regime")
# Industry constituent (stock list) table
MOBILE_CONSTITUENT_COLUMNS = ("Ticker", "Uptrend", "Change", "Perf YTD")


def mobile_columns(columns, is_mobile: bool, keep=MOBILE_TABLE_COLUMNS):
    """Return the subset of columns to show on a phone, or None on desktop.

    The result is meant for st.dataframe(column_order=...): None keeps all columns.
    """
    if not is_mobile:
        return None
    return [c for c in columns if c in keep]


def display_years(is_mobile: bool) -> int:
    """Default chart range in years: shorter on phones so the chart is not squeezed."""
    return MOBILE_DISPLAY_YEARS if is_mobile else DEFAULT_DISPLAY_YEARS


def is_mobile_client() -> bool:
    """Detect a phone from the current Streamlit request headers."""
    import streamlit as st

    try:
        user_agent = st.context.headers.get("User-Agent")
    except Exception:
        return False
    return is_mobile_user_agent(user_agent)


def inject_mobile_css() -> None:
    """Inject the responsive CSS into the current page."""
    import streamlit as st

    st.markdown(build_mobile_css(), unsafe_allow_html=True)


def show_chart(
    fig: go.Figure,
    mobile_height: Optional[int] = None,
    mobile_hide_annotations: bool = False,
    **kwargs,
):
    """Render a Plotly chart, applying the compact layout on phones.

    Extra kwargs (key, on_select, ...) pass through to st.plotly_chart.
    """
    import streamlit as st

    if is_mobile_client():
        apply_mobile_layout(fig, height=mobile_height, hide_annotations=mobile_hide_annotations)
        # Trimmed toolbar on phones only; desktop keeps download/select buttons
        kwargs.setdefault("config", PLOTLY_CONFIG)
    kwargs.setdefault("width", "stretch")
    return st.plotly_chart(fig, **kwargs)
