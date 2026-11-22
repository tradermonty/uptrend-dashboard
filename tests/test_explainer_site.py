"""Site layout on the gh-pages branch: dated archive, latest copy, manifest, index."""

import json

import pytest

from explainer.facts import Facts
from explainer.site import LANGS, publish

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
