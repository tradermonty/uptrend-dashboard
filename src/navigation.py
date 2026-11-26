"""Sidebar navigation definitions.

Streamlit's automatic pages/ discovery labels the entrypoint after its file
name ("app"). Defining pages explicitly with st.navigation lets every menu
entry have a readable title. The page scripts live in views/, not pages/:
with a pages/ directory Streamlit could still show its auto-discovered menu
(including "app") before st.navigation ran.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PageSpec:
    path: str
    title: str
    icon: str
    default: bool = False


ABOUT_PAGE = "views/7_About_Uptrend_Ratio.py"

# Menu order = how often the pages are used (most used first). File names keep
# their original numbers so URLs and st.switch_page() paths do not change.
PAGE_SPECS = (
    PageSpec("views/0_Uptrend_Ratio.py", "Uptrend Ratio", "📈", default=True),
    PageSpec("views/1_Sector_Detail.py", "Sector Detail", "🔍"),
    PageSpec("views/5_Industry_Heatmap.py", "Industry Heatmap", "🗺️"),
    PageSpec("views/2_Sector_Comparison.py", "Sector Comparison", "📊"),
    PageSpec("views/3_Industry_Detail.py", "Industry Detail", "🏭"),
    PageSpec("views/4_Industry_Comparison.py", "Industry Comparison", "📊"),
    PageSpec("views/6_Dispersion_Monitor.py", "Dispersion Monitor", "📡"),
    PageSpec(ABOUT_PAGE, "About Uptrend Ratio", "📖"),
)


def about_page_link() -> None:
    """Link to the About Uptrend Ratio page.

    st.page_link only knows pages registered with st.navigation, so a page script
    run on its own (AppTest, `streamlit run views/...`) has no About page to link to;
    the link is then left out instead of breaking the page.
    """
    import streamlit as st
    from streamlit.errors import StreamlitPageNotFoundError

    try:
        st.page_link(ABOUT_PAGE, label="What is the Uptrend Ratio? How it is counted", icon="📖")
    except StreamlitPageNotFoundError:
        pass
