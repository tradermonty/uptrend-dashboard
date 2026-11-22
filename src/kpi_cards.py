"""Color-coded KPI cards (replace st.metric + emoji).

Color carries the meaning (trend up/down, overbought/oversold, regime) instead of
emoji. Cards lay out in a responsive grid: 2 per row on phones, 4-5 on desktop.
"""

import html
from dataclasses import dataclass
from typing import Iterable, Optional

# Text/accent colors chosen for contrast on light and dark backgrounds.
# Status colors follow the app's convention (STATUS_COLORS in chart_builder).
TONE_COLORS = {
    "up": "#0a8f5a",
    "down": "#d63a2f",
    "overbought": "#d62728",
    "oversold": "#2ca02c",
    "normal": "#1f77b4",
}


@dataclass(frozen=True)
class KpiCard:
    label: str
    value: str
    tone: Optional[str] = None  # key of TONE_COLORS; None/"neutral" = no color


def trend_card(trend: str) -> KpiCard:
    trend = (trend or "neutral").lower()
    tone = trend if trend in ("up", "down") else "neutral"
    return KpiCard("Trend", trend.title(), tone)


def status_card(status) -> KpiCard:
    if status["is_overbought"]:
        return KpiCard("Status", "Overbought", "overbought")
    if status["is_oversold"]:
        return KpiCard("Status", "Oversold", "oversold")
    return KpiCard("Status", "Normal", "normal")


_REGIME_TONES = {"converged": "up", "normal": "normal", "diverged": "overbought"}


def regime_card(regime: str) -> KpiCard:
    regime = (regime or "").lower()
    return KpiCard("Regime", regime.title(), _REGIME_TONES.get(regime))


def _card_html(card: KpiCard) -> str:
    color = TONE_COLORS.get(card.tone or "")
    border = color if color else "transparent"
    background = f"{color}14" if color else "rgba(128,128,128,0.08)"
    value_style = f"color:{color};" if color else ""
    return (
        f'<div style="border-radius:10px;padding:10px 14px;background:{background};'
        f'border-left:5px solid {border};">'
        f'<div style="font-size:0.85rem;opacity:0.75;">{html.escape(card.label)}</div>'
        f'<div style="font-size:1.6rem;font-weight:600;line-height:1.3;{value_style}">'
        f"{html.escape(card.value)}</div></div>"
    )


def kpi_cards_html(cards: Iterable[KpiCard]) -> str:
    body = "".join(_card_html(c) for c in cards)
    return (
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));'
        f'gap:10px;margin:4px 0 12px 0;">{body}</div>'
    )


def render_kpi_cards(cards: Iterable[KpiCard]) -> None:
    import streamlit as st

    st.markdown(kpi_cards_html(cards), unsafe_allow_html=True)
