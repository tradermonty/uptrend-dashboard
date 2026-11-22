"""Sidebar navigation definitions.

Streamlit's automatic pages/ discovery labels the entrypoint after its file
name ("app"). Defining pages explicitly with st.navigation lets every menu
entry have a readable title.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PageSpec:
    path: str
    title: str
    icon: str
    default: bool = False


PAGE_SPECS = (
    PageSpec("pages/0_Uptrend_Ratio.py", "Uptrend Ratio", "📈", default=True),
    PageSpec("pages/1_Sector_Detail.py", "Sector Detail", "🔍"),
    PageSpec("pages/2_Sector_Comparison.py", "Sector Comparison", "📊"),
    PageSpec("pages/3_Industry_Detail.py", "Industry Detail", "🏭"),
    PageSpec("pages/4_Industry_Comparison.py", "Industry Comparison", "📊"),
    PageSpec("pages/5_Industry_Heatmap.py", "Industry Heatmap", "🗺️"),
    PageSpec("pages/6_Dispersion_Monitor.py", "Dispersion Monitor", "📡"),
)
