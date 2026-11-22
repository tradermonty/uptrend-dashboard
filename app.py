"""US Market Uptrend Dashboard — entrypoint and sidebar navigation.

Pages are registered explicitly so the menu shows readable titles
(the main page used to appear as "app"). See src/navigation.py.
"""

import streamlit as st

from src.navigation import PAGE_SPECS

pages = [
    st.Page(spec.path, title=spec.title, icon=spec.icon, default=spec.default)
    for spec in PAGE_SPECS
]
st.navigation(pages).run()
