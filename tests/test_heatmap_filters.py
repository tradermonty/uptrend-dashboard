"""Tests for KPI-driven industry filters on the Industry Heatmap page."""

import pandas as pd
import pytest

from src.data_processor import HEATMAP_FILTERS, filter_industry_summary, parse_heatmap_filter
from src.kpi_cards import KpiCard, kpi_cards_html


def _summary():
    return pd.DataFrame({
        "Industry": ["A", "B", "C", "D"],
        "Status": ["Oversold", "Normal", "Overbought", "Oversold"],
        "Trend": ["Up", "Down", "Up", "Down"],
        "Sector": ["S1", "S1", "S2", "S2"],
    })


class TestFilterIndustrySummary:
    @pytest.mark.parametrize("key,expected", [
        ("oversold", ["A", "D"]),
        ("normal", ["B"]),
        ("overbought", ["C"]),
        ("trend_up", ["A", "C"]),
        ("trend_down", ["B", "D"]),
    ])
    def test_each_kpi_filter(self, key, expected):
        assert filter_industry_summary(_summary(), key)["Industry"].tolist() == expected

    def test_no_filter_returns_everything(self):
        assert len(filter_industry_summary(_summary(), None)) == 4

    def test_filters_match_kpi_cards(self):
        assert set(HEATMAP_FILTERS) == {"oversold", "normal", "overbought", "trend_up", "trend_down"}


class TestParseHeatmapFilter:
    def test_valid_value(self):
        assert parse_heatmap_filter("trend_up") == "trend_up"

    @pytest.mark.parametrize("value", [None, "", "bogus", ["trend_up"], "<script>"])
    def test_invalid_values_mean_no_filter(self, value):
        assert parse_heatmap_filter(value) is None


class TestLinkedKpiCards:
    def test_card_with_href_is_a_same_tab_link(self):
        html = kpi_cards_html([KpiCard("Trend Up", "8.2%", "up", href="?filter=trend_up")])
        assert '<a href="?filter=trend_up" target="_self"' in html

    def test_active_card_is_marked(self):
        active = kpi_cards_html([KpiCard("Trend Up", "8.2%", "up", href="?", active=True)])
        idle = kpi_cards_html([KpiCard("Trend Up", "8.2%", "up", href="?filter=trend_up")])
        assert "box-shadow" in active and "box-shadow" not in idle

    def test_href_is_escaped(self):
        html = kpi_cards_html([KpiCard("x", "1", href='?a="b"')])
        assert 'href="?a=&quot;b&quot;"' in html
