"""About Uptrend Ratio page — what the ratio counts, for first-time visitors."""

import logging

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from src.about_page import about_page_html, latest_example
from src.data_loader import cached_load_sector_data
from src.mobile_ui import inject_mobile_css

logger = logging.getLogger(__name__)

st.set_page_config(page_title="About Uptrend Ratio", page_icon="📖", layout="wide")
inject_mobile_css()

# The worked example uses the latest whole-market numbers; without data the page
# still explains the ratio, just without numbers.
try:
    example = latest_example(cached_load_sector_data().get("all"))
except Exception:  # noqa: BLE001 - an explainer page must render even if the DB is unavailable
    logger.exception("About page: live numbers unavailable")
    example = None

st.html(about_page_html(example))
