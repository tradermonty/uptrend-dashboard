"""Read color-coded KPI cards (src.kpi_cards) back from a Streamlit AppTest."""

import html
import re

_CARD = re.compile(
    r'<div style="font-size:0\.85rem;opacity:0\.75;">(.*?)</div>'
    r'<div style="[^"]*">(.*?)</div>'
)


def kpi_cards(app) -> dict:
    """Return {label: value} for every KPI card rendered on the page."""
    cards = {}
    for block in app.markdown:
        if "grid-template-columns" not in block.value:
            continue
        for label, value in _CARD.findall(block.value):
            cards[html.unescape(label)] = html.unescape(value)
    return cards
