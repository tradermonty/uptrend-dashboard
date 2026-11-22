"""Tests for color-coded KPI cards (replacing emoji metrics)."""

from src.kpi_cards import (
    TONE_COLORS,
    KpiCard,
    kpi_cards_html,
    regime_card,
    status_card,
    trend_card,
)


class TestTrendCard:
    def test_up_is_green_tone_without_emoji(self):
        card = trend_card("up")
        assert card == KpiCard("Trend", "Up", "up")

    def test_down(self):
        assert trend_card("down").tone == "down"

    def test_unknown_is_neutral(self):
        card = trend_card("neutral")
        assert card.value == "Neutral"
        assert card.tone == "neutral"


class TestStatusCard:
    def test_oversold(self):
        status = {"is_overbought": False, "is_oversold": True}
        assert status_card(status) == KpiCard("Status", "Oversold", "oversold")

    def test_overbought(self):
        status = {"is_overbought": True, "is_oversold": False}
        assert status_card(status).tone == "overbought"

    def test_normal(self):
        status = {"is_overbought": False, "is_oversold": False}
        assert status_card(status) == KpiCard("Status", "Normal", "normal")


class TestRegimeCard:
    def test_regime_tones(self):
        assert regime_card("diverged").tone == "overbought"
        assert regime_card("converged").tone == "up"
        assert regime_card("normal") == KpiCard("Regime", "Normal", "normal")


class TestKpiCardsHtml:
    def test_contains_labels_values_and_no_emoji(self):
        html = kpi_cards_html([KpiCard("Current Ratio", "6.9%"), trend_card("down")])
        assert "Current Ratio" in html and "6.9%" in html and "Down" in html
        for emoji in ("🔼", "🔽", "⚠️", "➖", "🟢", "🔴", "🔵"):
            assert emoji not in html

    def test_tone_color_is_applied(self):
        html = kpi_cards_html([trend_card("down")])
        assert TONE_COLORS["down"] in html

    def test_neutral_card_has_no_tone_color(self):
        html = kpi_cards_html([KpiCard("10MA", "18.2%")])
        for color in TONE_COLORS.values():
            assert color not in html

    def test_values_are_html_escaped(self):
        html = kpi_cards_html([KpiCard("<b>x</b>", "<script>")])
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_grid_wraps_to_two_columns_on_phones(self):
        html = kpi_cards_html([KpiCard("a", "1")])
        assert "grid-template-columns" in html
        assert "minmax(" in html
