"""run_explainer.py: the daily entry point used by the GitHub Actions workflow."""

import json
from pathlib import Path

import pytest

import run_explainer
from explainer.facts import Facts

ROOT = Path(__file__).resolve().parents[1]
FACTS = Facts(date="2026-11-20", ratio_pct=6.9, count=183, total=2661,
              score=22.4, zone="Cautious", exposure="Defensive (30-60%)")


def test_run_analyzer_on_repo_data(tmp_path):
    report = run_explainer.run_analyzer(
        ROOT / "data" / "uptrend_ratio_timeseries.csv", ROOT / "data" / "sector_summary.csv", tmp_path)
    assert 0 <= report["composite"]["composite_score"] <= 100


def test_already_published(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps([{"date": "2026-11-20"}]))
    assert run_explainer.already_published(tmp_path, "2026-11-20")
    assert not run_explainer.already_published(tmp_path, "2026-11-21")
    assert not run_explainer.already_published(tmp_path / "missing", "2026-11-20")


def test_main_skips_without_calling_claude(tmp_path, monkeypatch):
    site = tmp_path / "site"
    site.mkdir()
    (site / "manifest.json").write_text(json.dumps([{"date": "2026-11-20"}]))
    monkeypatch.setattr(run_explainer, "run_analyzer", lambda *a: {})
    monkeypatch.setattr(run_explainer, "build_facts", lambda *a: FACTS)
    monkeypatch.setattr(run_explainer, "make_client",
                        lambda: pytest.fail("Claude must not be called"))
    assert run_explainer.main(["--site", str(site)]) == 0


def test_main_publishes_generated_pages(tmp_path, monkeypatch):
    site = tmp_path / "site"
    pages = {"ja": '<html lang="ja"><body>ja</body></html>', "en": '<html lang="en"><body>en</body></html>'}
    monkeypatch.setattr(run_explainer, "run_analyzer", lambda *a: {})
    monkeypatch.setattr(run_explainer, "build_facts", lambda *a: FACTS)
    monkeypatch.setattr(run_explainer, "make_client", lambda: object())
    monkeypatch.setattr(run_explainer, "build_brief", lambda *a: {})
    monkeypatch.setattr(run_explainer, "generate_pages", lambda *a, **k: pages)
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert run_explainer.main(["--site", str(site)]) == 0
    assert (site / "2026" / "11" / "2026-11-20-en.html").exists()
    assert "published_date=2026-11-20" in out.read_text()


def test_main_returns_1_on_api_error(tmp_path, monkeypatch):
    anthropic = pytest.importorskip("anthropic")  # CI installs requirements.txt only
    import httpx2

    def boom(*a, **k):
        raise anthropic.APIConnectionError(request=httpx2.Request("POST", "https://x"))

    site = tmp_path / "site"
    monkeypatch.setattr(run_explainer, "run_analyzer", lambda *a: {})
    monkeypatch.setattr(run_explainer, "build_facts", lambda *a: FACTS)
    monkeypatch.setattr(run_explainer, "build_brief", lambda *a: {})
    monkeypatch.setattr(run_explainer, "make_client", lambda: object())
    monkeypatch.setattr(run_explainer, "generate_pages", boom)
    assert run_explainer.main(["--site", str(site)]) == 1
    assert not (site / "manifest.json").exists()


def test_main_returns_1_and_leaves_site_alone_on_failure(tmp_path, monkeypatch):
    site = tmp_path / "site"

    def boom(*a, **k):
        raise run_explainer.GenerationError("pages failed the checks")

    monkeypatch.setattr(run_explainer, "run_analyzer", lambda *a: {})
    monkeypatch.setattr(run_explainer, "build_facts", lambda *a: FACTS)
    monkeypatch.setattr(run_explainer, "make_client", lambda: object())
    monkeypatch.setattr(run_explainer, "build_brief", lambda *a: {})
    monkeypatch.setattr(run_explainer, "generate_pages", boom)
    assert run_explainer.main(["--site", str(site)]) == 1
    assert not (site / "manifest.json").exists()
