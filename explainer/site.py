"""Write a day's explainer pages into the GitHub Pages tree.

Layout (relative to the site root, the gh-pages branch checkout):

    index.html                      archive of every day, newest first
    manifest.json                   one entry per day, newest first
    latest/{lang}.html              copy of the newest day
    YYYY/MM/YYYY-MM-DD-{lang}.html  one page per day, kept forever

Archived pages are written once per date and not touched when later days
arrive, so each one stays as it was published. A short navigation bar is
added to each page with relative links, so the site works under a project
path such as /uptrend-dashboard/.
"""

import html
import json
import re
from pathlib import Path

from explainer.facts import Facts

LANGS = ("en", "ja")  # English is the primary language; Japanese is offered alongside
LANG_LABEL = {"ja": "日本語", "en": "English"}
LANG_ATTR = {"ja": ' lang="ja"', "en": ""}  # index page is English
NAV_ID = "explainer-nav"
# The Streamlit dashboard these pages explain; linked at the right end of every page's nav
DASHBOARD_URL = "https://uptrend-dashboard.streamlit.app/"

ZONE_COLOR = {  # matches the uptrend-analyzer zones
    "Strong Bull": "#12a36b", "Bull": "#6fbf73", "Neutral": "#c9a227",
    "Cautious": "#e0912b", "Bear": "#d9493a",
}


def archive_path(date: str, lang: str) -> str:
    return f"{date[:4]}/{date[5:7]}/{date}-{lang}.html"


def _rel(from_path: str, to_path: str) -> str:
    """Relative URL from one site path to another (both relative to the root)."""
    from_parts = from_path.split("/")[:-1]
    to_parts = to_path.split("/")
    common = 0
    while (common < len(from_parts) and common < len(to_parts) - 1
           and from_parts[common] == to_parts[common]):
        common += 1
    return "/".join([".."] * (len(from_parts) - common) + to_parts[common:])


def _nav(here: str, date: str, lang: str, prev_date: str | None) -> str:
    other = "en" if lang == "ja" else "ja"
    labels = {
        "ja": {"dashboard": "ダッシュボード", "index": "一覧", "latest": "最新", "prev": "前の日"},
        "en": {"dashboard": "Dashboard", "index": "All days", "latest": "Latest", "prev": "Previous day"},
    }[lang]
    links = [(labels["index"], _rel(here, "index.html")),
             (labels["latest"], _rel(here, f"latest/{lang}.html"))]
    if prev_date:
        links.append((f"← {labels['prev']}", _rel(here, archive_path(prev_date, lang))))
    links.append((LANG_LABEL[other], _rel(here, archive_path(date, other))))
    links.append((f"{labels['dashboard']} →", DASHBOARD_URL))  # right end of the bar
    items = " · ".join(
        f'<a href="{html.escape(href)}" style="color:inherit">{html.escape(text)}</a>'
        for text, href in links
    )
    return (
        f'<nav id="{NAV_ID}" style="font:13px/1.6 system-ui,sans-serif;padding:8px 16px;'
        f'text-align:center;opacity:.85">{items}</nav>'
    )


_NAV_RE = re.compile(rf'<nav id="{NAV_ID}".*?</nav>', re.S)
_BODY_RE = re.compile(r"<body\b[^>]*>", re.I)


def _with_nav(page: str, nav: str) -> str:
    page = _NAV_RE.sub("", page)
    m = _BODY_RE.search(page)
    if not m:
        return nav + page
    return page[: m.end()] + nav + page[m.end():]


def _load_manifest(site: Path) -> list[dict]:
    path = site / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def publish(site: Path, facts: Facts, pages: dict[str, str]) -> None:
    missing = [lang for lang in LANGS if lang not in pages]
    if missing:
        raise ValueError(f"missing pages for: {', '.join(missing)}")
    site.mkdir(parents=True, exist_ok=True)
    (site / ".nojekyll").touch()

    manifest = [e for e in _load_manifest(site) if e["date"] != facts.date]
    manifest.append({**facts.to_dict(),
                     "pages": {lang: archive_path(facts.date, lang) for lang in LANGS}})
    manifest.sort(key=lambda e: e["date"], reverse=True)
    dates = [e["date"] for e in manifest]
    older = [d for d in dates if d < facts.date]
    prev_date = older[0] if older else None
    is_latest = dates[0] == facts.date

    for lang in LANGS:
        here = archive_path(facts.date, lang)
        target = site / here
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_with_nav(pages[lang], _nav(here, facts.date, lang, prev_date)),
                          encoding="utf-8")
        if is_latest:
            latest = f"latest/{lang}.html"
            (site / "latest").mkdir(exist_ok=True)
            (site / latest).write_text(
                _with_nav(pages[lang], _nav(latest, facts.date, lang, prev_date)),
                encoding="utf-8")

    (site / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (site / "index.html").write_text(render_index(manifest), encoding="utf-8")


def refresh_nav(site: Path) -> int:
    """Re-render the nav bar (only) on every published page and the index.

    For nav changes such as the dashboard link: archived page bodies stay exactly
    as published; only the <nav id="explainer-nav"> block is replaced.
    Returns the number of files that changed.
    """
    manifest = _load_manifest(site)
    if not manifest:
        # A wrong --site path must not look like success (and must not write an empty index)
        raise FileNotFoundError(f"no published pages in {site} (manifest.json missing or empty)")
    dates = [e["date"] for e in manifest]
    targets = []
    for i, e in enumerate(manifest):
        prev_date = dates[i + 1] if i + 1 < len(dates) else None
        for lang in LANGS:
            targets.append((archive_path(e["date"], lang), e["date"], lang, prev_date))
            if i == 0:
                targets.append((f"latest/{lang}.html", e["date"], lang, prev_date))
    changed = 0
    for here, date, lang, prev_date in targets:
        path = site / here
        if not path.exists():
            continue
        old = path.read_text(encoding="utf-8")
        new = _with_nav(old, _nav(here, date, lang, prev_date))
        if new != old:
            path.write_text(new, encoding="utf-8")
            changed += 1
    index = render_index(manifest)
    index_path = site / "index.html"
    if not index_path.exists() or index_path.read_text(encoding="utf-8") != index:
        index_path.write_text(index, encoding="utf-8")
        changed += 1
    return changed


def _sparkline(manifest: list[dict]) -> str:
    points = list(reversed(manifest))[-120:]
    if len(points) < 2:
        return ""
    w, h, top = 640, 120, 50.0  # y scale 0-50 %
    step = w / (len(points) - 1)
    coords = " ".join(f"{i * step:.1f},{h - min(p['ratio_pct'], top) / top * h:.1f}"
                      for i, p in enumerate(points))
    y37 = h - 37 / top * h
    y97 = h - 9.7 / top * h
    return (
        f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Uptrend ratio history" class="spark">'
        f'<line x1="0" x2="{w}" y1="{y37:.1f}" y2="{y37:.1f}" class="hot"/>'
        f'<line x1="0" x2="{w}" y1="{y97:.1f}" y2="{y97:.1f}" class="cold"/>'
        f'<polyline points="{coords}" class="line"/></svg>'
        f'<p class="note">{html.escape(points[0]["date"])} – {html.escape(points[-1]["date"])}'
        f" · 37% / 9.7%</p>"
    )


def render_index(manifest: list[dict]) -> str:
    rows, month = [], None
    for e in manifest:
        if e["date"][:7] != month:
            month = e["date"][:7]
            rows.append(f'<h2>{html.escape(month)}</h2>')
        color = ZONE_COLOR.get(e.get("zone", ""), "#888")
        links = " ".join(
            f'<a href="{html.escape(e["pages"][lang])}"{LANG_ATTR[lang]}>{LANG_LABEL[lang]}</a>'
            for lang in LANGS
        )
        rows.append(
            f'<div class="row"><span class="d">{html.escape(e["date"])}</span>'
            f'<span class="r">{e["ratio_pct"]:.1f}%</span>'
            f'<span class="chip" style="background:{color}">{e["score"]:.0f}</span>'
            f'<span class="l">{links}</span></div>'
        )
    latest_en = '<a class="btn primary" href="latest/en.html">Read today\'s explainer</a>'
    latest_ja = '<a class="btn" href="latest/ja.html" lang="ja">日本語で読む</a>'
    dashboard = f'<a class="btn" href="{html.escape(DASHBOARD_URL)}">Open the dashboard</a>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Uptrend Explainer Archive</title>
<style>
:root{{--bg:#f3f5f8;--fg:#18202b;--muted:#5b6676;--line:#d9dee6;--accent:#3b7dd8;--hot:#e0912b;--cold:#3b7dd8}}
@media (prefers-color-scheme:dark){{:root{{--bg:#10151c;--fg:#e8edf3;--muted:#9aa6b5;--line:#2c3746;--accent:#6aa3f0;--hot:#f0aa4d;--cold:#6aa3f0;color-scheme:dark}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 system-ui,-apple-system,"Hiragino Sans","Noto Sans JP",sans-serif}}
main{{max-width:720px;margin:0 auto;padding:32px max(16px,env(safe-area-inset-left)) 48px}}
h1{{font-size:26px;margin:0 0 4px}} h2{{font-size:15px;color:var(--muted);margin:24px 0 6px;border-bottom:1px solid var(--line)}}
.btn{{display:inline-block;padding:6px 14px;border:1px solid var(--accent);border-radius:999px;color:var(--accent);text-decoration:none;margin-right:6px}}
.btn.primary{{background:var(--accent);color:var(--bg);font-weight:600}}
.row{{display:grid;grid-template-columns:7.5em 4em 2.6em 1fr;gap:8px;align-items:center;padding:4px 0;font-variant-numeric:tabular-nums}}
.chip{{color:#fff;border-radius:6px;text-align:center;font-size:13px;font-weight:700}}
.l a{{color:var(--accent);margin-right:10px}} .d{{font-family:ui-monospace,Menlo,monospace}}
.spark{{width:100%;height:auto;display:block;margin-top:16px}} .spark .line{{fill:none;stroke:var(--fg);stroke-width:2}}
.spark .hot{{stroke:var(--hot);stroke-dasharray:4 4}} .spark .cold{{stroke:var(--cold);stroke-dasharray:4 4}}
.note,.sub{{color:var(--muted);font-size:13px;margin:4px 0}}
</style></head><body><main>
<h1>Daily Uptrend Explainer</h1>
<p class="sub">Every trading day, a one-minute picture explainer of how many US stocks are in an uptrend. The chip is the breadth score (0-100, higher = healthier).</p>
<p class="sub" lang="ja">米国株のうち上昇トレンドにある銘柄の割合を、毎営業日やさしく解説します。日本語版もあります。</p>
<p>{latest_en} {latest_ja} {dashboard}</p>
{_sparkline(manifest)}
{''.join(rows)}
<p class="note">For education only, not investment advice. <span lang="ja">教育目的の情報で、投資助言ではありません。</span></p>
</main></body></html>
"""
