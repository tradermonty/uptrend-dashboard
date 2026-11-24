"""Site layout on the gh-pages branch: dated archive, latest copy, manifest, index."""

import json

import pytest

from explainer.facts import Facts
from explainer.site import DASHBOARD_URL, LANGS, SKILL_URL, SKILL_URLS, publish, refresh_nav

PAGE = '<!doctype html><html lang="{lang}"><head><title>t</title></head><body class="x"><h1>{date}</h1></body></html>'


def _facts(date, ratio=6.9, score=22.4, zone="Cautious"):
    return Facts(date=date, ratio_pct=ratio, count=183, total=2661, score=score,
                 zone=zone, exposure="Defensive (30-60%)")


def _pages(date):
    return {lang: PAGE.format(lang=lang, date=date) for lang in LANGS}


@pytest.fixture
def site(tmp_path):
    return tmp_path / "site"


class TestPublish:

    def test_writes_archive_and_latest(self, site):
        publish(site, _facts("2026-11-20"), _pages("2026-11-20"))
        for lang in LANGS:
            assert "2026-11-20" in (site / "2026" / "11" / f"2026-11-20-{lang}.html").read_text()
            assert "2026-11-20" in (site / "latest" / f"{lang}.html").read_text()
        assert (site / ".nojekyll").exists()

    def test_latest_moves_but_archive_is_kept(self, site):
        publish(site, _facts("2026-11-19"), _pages("2026-11-19"))
        publish(site, _facts("2026-11-20"), _pages("2026-11-20"))
        assert "2026-11-19" in (site / "2026" / "11" / "2026-11-19-ja.html").read_text()
        assert "2026-11-20" in (site / "latest" / "ja.html").read_text()

    def test_backfill_does_not_replace_latest(self, site):
        publish(site, _facts("2026-11-20"), _pages("2026-11-20"))
        publish(site, _facts("2026-11-18"), _pages("2026-11-18"))
        assert "2026-11-20" in (site / "latest" / "ja.html").read_text()

    def test_manifest_upserts_and_sorts_newest_first(self, site):
        publish(site, _facts("2026-11-19", score=30.0), _pages("2026-11-19"))
        publish(site, _facts("2026-11-20"), _pages("2026-11-20"))
        publish(site, _facts("2026-11-19", score=31.0), _pages("2026-11-19"))
        manifest = json.loads((site / "manifest.json").read_text())
        assert [e["date"] for e in manifest] == ["2026-11-20", "2026-11-19"]
        assert manifest[1]["score"] == 31.0
        assert manifest[0]["pages"]["en"] == "2026/11/2026-11-20-en.html"

    def test_index_links_every_day_and_language(self, site):
        publish(site, _facts("2026-10-30"), _pages("2026-10-30"))
        publish(site, _facts("2026-11-20"), _pages("2026-11-20"))
        index = (site / "index.html").read_text()
        for href in ("2026/11/2026-11-20-ja.html", "2026/11/2026-11-20-en.html",
                     "2026/10/2026-10-30-ja.html", "latest/ja.html", "latest/en.html"):
            assert f'href="{href}"' in index
        assert index.index('class="d">2026-11-20') < index.index('class="d">2026-10-30')

    def test_index_is_english_first_with_japanese_offered(self, site):
        publish(site, _facts("2026-11-20"), _pages("2026-11-20"))
        index = (site / "index.html").read_text()
        assert '<html lang="en">' in index
        assert "Daily Uptrend Explainer" in index
        assert index.index('href="latest/en.html"') < index.index('href="latest/ja.html"')
        row_en = index.index('href="2026/11/2026-11-20-en.html"')
        assert row_en < index.index('href="2026/11/2026-11-20-ja.html"')
        assert 'lang="ja"' in index  # Japanese labels are marked as Japanese

    def test_nav_injected_with_relative_links(self, site):
        publish(site, _facts("2026-11-19"), _pages("2026-11-19"))
        publish(site, _facts("2026-11-20"), _pages("2026-11-20"))
        archived = (site / "2026" / "11" / "2026-11-20-ja.html").read_text()
        assert 'id="explainer-nav"' in archived
        assert 'href="../../index.html"' in archived
        assert 'href="2026-11-19-ja.html"' in archived       # previous day, same month
        assert 'href="2026-11-20-en.html"' in archived       # other language
        latest = (site / "latest" / "ja.html").read_text()
        assert 'href="../index.html"' in latest
        assert 'href="../2026/11/2026-11-19-ja.html"' in latest
        assert archived.index('id="explainer-nav"') > archived.index('<body class="x">')

    def test_nav_inserted_once_on_republish(self, site):
        publish(site, _facts("2026-11-20"), _pages("2026-11-20"))
        publish(site, _facts("2026-11-20"), _pages("2026-11-20"))
        assert (site / "latest" / "ja.html").read_text().count('id="explainer-nav"') == 1

    def test_rejects_missing_language(self, site):
        with pytest.raises(ValueError, match="en"):
            publish(site, _facts("2026-11-20"), {"ja": PAGE})


class TestDashboardLink:
    """Every explainer page and the index link back to the Streamlit dashboard."""

    def test_page_nav_links_to_dashboard(self, site):
        publish(site, _facts("2026-11-20"), _pages("2026-11-20"))
        for path in ("2026/11/2026-11-20-en.html", "2026/11/2026-11-20-ja.html",
                     "latest/en.html", "latest/ja.html"):
            assert f'href="{DASHBOARD_URL}"' in (site / path).read_text()

    def test_dashboard_back_link_is_first_in_nav(self, site):
        publish(site, _facts("2026-11-20"), _pages("2026-11-20"))
        page = (site / "latest/en.html").read_text()
        nav = page[page.index('<nav id="explainer-nav"'):page.index("</nav>")]
        assert nav.index("<a ") == nav.index(f'href="{DASHBOARD_URL}"') - 3
        assert "← Dashboard" in nav

    def test_dashboard_label_per_language(self, site):
        publish(site, _facts("2026-11-20"), _pages("2026-11-20"))
        assert "Dashboard" in (site / "latest/en.html").read_text()
        assert "ダッシュボード" in (site / "latest/ja.html").read_text()

    def test_index_links_to_dashboard(self, site):
        publish(site, _facts("2026-11-20"), _pages("2026-11-20"))
        assert f'href="{DASHBOARD_URL}"' in (site / "index.html").read_text()

    def test_refresh_nav_updates_already_published_pages(self, site):
        publish(site, _facts("2026-11-19"), _pages("2026-11-19"))
        publish(site, _facts("2026-11-20"), _pages("2026-11-20"))
        old = site / "2026/11/2026-11-19-en.html"
        # Simulate a page published before the dashboard link existed
        old.write_text(old.read_text().replace(DASHBOARD_URL, "https://example.invalid/"))
        changed = refresh_nav(site)
        text = old.read_text()
        assert f'href="{DASHBOARD_URL}"' in text
        assert text.count('<nav id="explainer-nav"') == 1
        assert "<h1>2026-11-19</h1>" in text  # page body untouched
        assert 'href="2026-11-19-ja.html"' in text  # other-language link kept
        assert changed == 1  # only the simulated old page differed
        assert refresh_nav(site) == 0  # idempotent

    def test_refresh_nav_rejects_a_site_without_manifest(self, tmp_path):
        tmp_path.mkdir(exist_ok=True)
        with pytest.raises(FileNotFoundError):
            refresh_nav(tmp_path)
        assert not (tmp_path / "index.html").exists()


class TestSkillLink:
    """Every page points readers to the Uptrend Analyzer skill page in its own language."""

    PAGES = ("2026/11/2026-11-20-en.html", "2026/11/2026-11-20-ja.html",
             "latest/en.html", "latest/ja.html")

    def test_skill_urls_per_language(self):
        assert SKILL_URLS == {"en": "https://tradermonty.github.io/claude-trading-skills/en/skills/uptrend-analyzer/",
                              "ja": "https://tradermonty.github.io/claude-trading-skills/ja/skills/uptrend-analyzer/"}
        assert SKILL_URL == SKILL_URLS["en"]

    def test_every_page_links_to_the_skill_once(self, site):
        publish(site, _facts("2026-11-20"), _pages("2026-11-20"))
        for path in self.PAGES:
            text = (site / path).read_text()
            lang = "ja" if "ja" in path else "en"
            assert text.count(f'href="{SKILL_URLS[lang]}"') == 1, path
            assert text.count('id="explainer-skill"') == 1, path

    def test_skill_note_sits_at_the_end_of_the_body(self, site):
        publish(site, _facts("2026-11-20"), _pages("2026-11-20"))
        text = (site / "latest/en.html").read_text()
        assert text.index("<h1>2026-11-20</h1>") < text.index('id="explainer-skill"') < text.index("</body>")

    def test_skill_link_opens_in_a_new_tab(self, site):
        publish(site, _facts("2026-11-20"), _pages("2026-11-20"))
        text = (site / "latest/en.html").read_text()
        assert 'target="_blank" rel="noopener"' in text

    def test_skill_label_per_language(self, site):
        publish(site, _facts("2026-11-20"), _pages("2026-11-20"))
        assert "Uptrend Analyzer skill" in (site / "latest/en.html").read_text()
        ja = (site / "latest/ja.html").read_text()
        assert "スキル" in ja and "英語" not in ja
        assert "https://tradermonty.github.io/claude-trading-skills/en/skills/uptrend-analyzer/" not in ja

    def test_index_links_to_the_skill(self, site):
        publish(site, _facts("2026-11-20"), _pages("2026-11-20"))
        assert f'href="{SKILL_URL}"' in (site / "index.html").read_text()

    def test_refresh_nav_adds_the_skill_link_to_old_pages(self, site):
        publish(site, _facts("2026-11-19"), _pages("2026-11-19"))
        publish(site, _facts("2026-11-20"), _pages("2026-11-20"))
        old = site / "2026/11/2026-11-19-en.html"
        # Simulate a page published before the skill link existed
        text = old.read_text()
        start = text.index('<p id="explainer-skill"')
        end = text.index("</p>", start) + len("</p>")
        old.write_text(text[:start] + text[end:])
        assert refresh_nav(site) == 1
        text = old.read_text()
        assert text.count(f'href="{SKILL_URL}"') == 1
        assert "<h1>2026-11-19</h1>" in text  # page body untouched
        assert refresh_nav(site) == 0  # idempotent

    def test_skill_note_goes_before_html_end_when_body_end_is_missing(self, site):
        pages = {lang: f'<html lang="{lang}"><body><h1>2026-11-20</h1></html>' for lang in LANGS}
        publish(site, _facts("2026-11-20"), pages)
        text = (site / "latest/en.html").read_text()
        assert text.index('id="explainer-skill"') < text.index("</html>")
        assert text.endswith("</html>")
