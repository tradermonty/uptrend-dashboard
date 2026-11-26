"""About Uptrend Ratio page: plain-language definition with a live example (v6.6)."""

import base64
import re
from pathlib import Path

import pandas as pd
import pytest

from src.about_page import RatioExample, about_page_html, latest_example
from src.constants import LOWER_THRESHOLD, UPPER_THRESHOLD
from src.finviz_universe import UPTREND_FILTERS
from src.kpi_cards import uptrend_screener_url
from src.navigation import PAGE_SPECS
from src.page_footer import UPTREND_ANALYZER_SKILL_URL

ROOT = Path(__file__).resolve().parents[1]
ABOUT_PAGE = "views/7_About_Uptrend_Ratio.py"
EXAMPLE = RatioExample(date=pd.Timestamp("2026-11-25"), count=380, total=2714)


def _pictures(html):
    """The SVG documents embedded as data: URI images."""
    return [base64.b64decode(b).decode() for b in re.findall(r'src="data:image/svg\+xml;base64,([^"]+)"', html)]


def _green_dots(html):
    return sum(len(re.findall(r'<circle class="dot up"', svg)) for svg in _pictures(html))


class TestAboutPageHtml:

    def test_lists_every_screening_condition(self):
        html = about_page_html(EXAMPLE)
        for text in (
            "Market cap over $50M", "Average volume over 100K shares", "Price over $10",
            "Price above its 20-day average", "Price above its 200-day average",
            "50-day average above the 200-day average", "30% or more above its 52-week low",
            "Up over the past month",
        ):
            assert text in html, text

    def test_links_the_finviz_screen_and_the_skill(self):
        html = about_page_html(EXAMPLE)
        assert uptrend_screener_url().replace("&", "&amp;") in html
        assert UPTREND_ANALYZER_SKILL_URL in html

    def test_example_uses_the_given_numbers(self):
        html = about_page_html(EXAMPLE)
        assert "380" in html and "2,714" in html and "14.0%" in html
        assert "Nov 25, 2026" in html
        assert "about 27 real stocks" in html

    def test_green_dots_match_the_ratio(self):
        assert _green_dots(about_page_html(EXAMPLE)) == 14
        assert _green_dots(about_page_html(RatioExample(pd.Timestamp("2026-01-02"), 1000, 2000))) == 50

    def test_without_data_it_still_explains_the_ratio(self):
        html = about_page_html(None)
        assert "What is the Uptrend Ratio?" in html
        assert "Up over the past month" in html
        assert "2,714" not in html and _green_dots(html) == 0

    def test_no_scripts_and_styles_are_scoped(self):
        html = about_page_html(EXAMPLE)
        assert "<script" not in html
        css = re.search(r"<style>(.*?)</style>", html, re.S).group(1)
        selectors = [s.strip() for s in re.findall(r"(?:^|})\s*([^{}@]+?)\s*{", css)]
        assert selectors and all(s.startswith((".about-ur", ":root")) for s in selectors), selectors

    def test_pictures_are_images_because_st_html_drops_inline_svg(self):
        html = about_page_html(EXAMPLE)
        assert "<svg" not in html
        pictures = _pictures(html)
        assert len(pictures) == 3
        for svg in pictures:
            assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg"') and "<title>" in svg
            assert "prefers-color-scheme" not in svg  # the app theme is fixed to light
        assert all('alt="' in img for img in re.findall(r"<img [^>]+>", html))

    def test_every_filter_has_its_plain_words(self):
        """A change to the Finviz filters must come with a change to the page text."""
        words = {
            "cap_microover": "Market cap over $50M",
            "sh_avgvol_o100": "Average volume over 100K shares",
            "sh_price_o10": "Price over $10",
            "ta_sma20_pa": "Price above its 20-day average",
            "ta_sma200_pa": "Price above its 200-day average",
            "ta_sma50_sa200": "50-day average above the 200-day average",
            "ta_highlow52w_a30h": "30% or more above its 52-week low",
            "ta_perf2_4wup": "Up over the past month",
        }
        assert set(words) == set(UPTREND_FILTERS)
        html = about_page_html(EXAMPLE)
        assert all(text in html for text in words.values())

    def test_price_is_not_required_above_the_50_day(self):
        html = about_page_html(EXAMPLE)
        assert "every average" not in html
        assert "above the 20-day and the 200-day average" in html

    def test_threshold_levels_come_from_constants(self):
        html = about_page_html(EXAMPLE)
        assert f"{UPPER_THRESHOLD * 100:g}%" in html and f"{LOWER_THRESHOLD * 100:g}%" in html

    @pytest.mark.parametrize("count,dots", [(145, 15), (144, 14), (5, 1), (4, 0), (1000, 100)])
    def test_dots_round_half_up(self, count, dots):
        assert _green_dots(about_page_html(RatioExample(pd.Timestamp("2026-01-02"), count, 1000))) == dots

    def test_pictures_have_their_own_white_background(self):
        for svg in _pictures(about_page_html(EXAMPLE)):
            assert '<rect width="360"' in svg and 'fill="#ffffff"' in svg

    def test_explains_the_deeper_oversold_shading(self):
        from src.chart_builder import COLOR_OVERSOLD_BAND
        html = about_page_html(EXAMPLE)
        assert f"Deeper pink: the ratio is below {LOWER_THRESHOLD * 100:g}% (Oversold)" in html
        assert COLOR_OVERSOLD_BAND in html
        chart = _pictures(html)[-1]
        assert 'class="deep"' in chart

    def test_example_chart_shading_matches_its_lines(self):
        """Pale pink from the top of the red line to where it drops below 9.7%; deep pink while below."""
        chart = _pictures(about_page_html(EXAMPLE))[-1]
        rect = lambda cls: tuple(map(float, re.search(  # noqa: E731
            rf'<rect class="{cls}" x="([\d.]+)" y="[\d.]+" width="([\d.]+)"', chart).groups()))
        (px, pw), (dx, dw) = rect("pink"), rect("deep")
        lower_y = 165  # the dotted 9.7% line
        line = []  # the ratio polyline: the three green/red paths, in order
        for d in re.findall(r'<path d="(M[\d. L]+)" fill="none" stroke="#(?:00cc96|ef553b)"', chart):
            line += [tuple(map(float, xy.split())) for xy in re.findall(r"[ML]\s*([\d.]+ [\d.]+)", d)]
        crossings = [x0 + (x1 - x0) * (lower_y - y0) / (y1 - y0)
                     for (x0, y0), (x1, y1) in zip(line, line[1:]) if (y0 - lower_y) * (y1 - lower_y) < 0]
        red_start = float(re.search(r'<path d="M([\d.]+) [\d.]+[^"]*" fill="none" stroke="#ef553b"', chart).group(1))
        assert px == red_start and px + pw == dx  # pale: red start to the drop below the level
        assert [dx, dx + dw] == pytest.approx(crossings)  # deep: exactly while below the level

    def test_legend_says_pale_pink_stops_at_the_level(self):
        assert "Pale pink: the red stretches while the ratio is above 9.7%" in about_page_html(EXAMPLE)

    def test_says_it_is_not_advice(self):
        assert "Not investment advice" in about_page_html(EXAMPLE)


class TestLatestExample:

    def test_takes_the_last_row(self):
        df = pd.DataFrame({"date": pd.to_datetime(["2026-11-24", "2026-11-25"]),
                           "count": [400, 380], "total": [2700, 2714]})
        ex = latest_example(df)
        assert (ex.date, ex.count, ex.total) == (pd.Timestamp("2026-11-25"), 380, 2714)
        assert ex.ratio == pytest.approx(380 / 2714)

    def test_takes_the_latest_date_even_if_unsorted(self):
        df = pd.DataFrame({"date": pd.to_datetime(["2026-11-25", "2026-11-24", None]),
                           "count": [380, 400, 1], "total": [2714, 2700, 2]})
        assert latest_example(df).count == 380

    @pytest.mark.parametrize("df", [None, pd.DataFrame(), pd.DataFrame(
        {"date": [pd.Timestamp("2026-11-25")], "count": [10], "total": [0]})])
    def test_no_usable_row_gives_none(self, df):
        assert latest_example(df) is None


class TestAboutPageRegistration:

    def test_registered_last_in_the_menu(self):
        assert PAGE_SPECS[-1].path == ABOUT_PAGE
        assert PAGE_SPECS[-1].title == "About Uptrend Ratio"

    def test_page_renders_with_the_latest_numbers(self, tmp_path, monkeypatch):
        import streamlit as st
        from streamlit.testing.v1 import AppTest
        from src.db_client import DBClient
        db = tmp_path / "u.db"
        client = DBClient(str(db))
        client.upsert_raw_data("2026-11-25", "all", 1234, 5678)
        client.upsert_raw_data("2026-11-24", "all", 1000, 5000)
        monkeypatch.setenv("DB_PATH", str(db))
        st.cache_data.clear()
        try:
            app = AppTest.from_file(str(ROOT / ABOUT_PAGE), default_timeout=30).run()
        finally:
            st.cache_data.clear()
        assert not app.exception
        body = " ".join(e.proto.body for e in app.get("html"))
        assert "1,234" in body and "5,678" in body and "Nov 25, 2026" in body
        assert "What is the Uptrend Ratio?" in body

    def test_uptrend_ratio_page_links_here(self):
        """Through the real router, the landing page shows a link to the About page."""
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
        assert not app.exception
        links = [e.proto for e in app.get("page_link")]
        assert any(link.page.endswith("About_Uptrend_Ratio") or ABOUT_PAGE in link.page for link in links), \
            [(link.label, link.page) for link in links]

    def test_page_run_on_its_own_skips_the_link(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(ROOT / "views/0_Uptrend_Ratio.py"), default_timeout=30).run()
        assert not app.exception
        assert not app.get("page_link")
