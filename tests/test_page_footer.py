"""Tests for the AI skill promotion note below Data Download."""

from src.page_footer import UPTREND_ANALYZER_SKILL_URL, ai_skill_note_html


def test_links_to_uptrend_analyzer_skill_page():
    assert UPTREND_ANALYZER_SKILL_URL == (
        "https://tradermonty.github.io/claude-trading-skills/en/skills/uptrend-analyzer/"
    )
    assert f'href="{UPTREND_ANALYZER_SKILL_URL}"' in ai_skill_note_html()


def test_opens_in_new_tab_safely():
    html = ai_skill_note_html()
    assert 'target="_blank"' in html
    assert 'rel="noopener"' in html


def test_wording_matches_market_breadth_page():
    html = ai_skill_note_html()
    assert "Want to analyze this uptrend data with AI?" in html
    assert "Try the Uptrend Analyzer skill for Claude &rarr;" in html


# --- Daily explainer link (GitHub Pages, v6.3) ---------------------------------
from src.page_footer import EXPLAINER_URL, explainer_link_html  # noqa: E402


def test_explainer_link_points_to_latest_english_page():
    assert EXPLAINER_URL == "https://tradermonty.github.io/uptrend-dashboard/"
    html = explainer_link_html()
    assert f'href="{EXPLAINER_URL}latest/en.html"' in html


def test_explainer_link_has_no_japanese_link():
    html = explainer_link_html()
    assert "latest/ja.html" not in html
    assert "日本語で読む" not in html


def test_explainer_link_opens_new_tab():
    html = explainer_link_html()
    assert html.count('target="_blank"') == 1
    assert html.count('rel="noopener"') == 1
