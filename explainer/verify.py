"""Gate for Claude-written explainer pages.

A page is published only when this returns no problems. It checks the facts
block the prompt asks Claude to embed, the key numbers a reader sees (each
inside an element marked ``data-fact="ratio_pct" | "count" | "score"``), and
that the page is self-contained.
"""

import json
import re
from html.parser import HTMLParser

from explainer.facts import Facts

FACTS_KEYS = ("date", "ratio_pct", "count", "total", "score")
VISIBLE_KEYS = ("ratio_pct", "count", "score")
MAX_BYTES = 1_000_000

_URL = r"(?:https?:)?//"
_EXTERNAL = [
    (re.compile(r"<script\b[^>]*\bsrc\s*=", re.I), "external script"),
    (re.compile(rf"<link\b[^>]*\bhref\s*=\s*[\"']?{_URL}", re.I), "external stylesheet or link"),
    (re.compile(rf"url\(\s*[\"']?{_URL}", re.I), "external url() in CSS"),
    (re.compile(rf"<(?:img|iframe|video|audio|source|embed|object)\b[^>]*\b(?:src|data)\s*=\s*[\"']?{_URL}",
                re.I), "external media"),
    (re.compile(r"@import", re.I), "external @import"),
]
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source",
         "track", "wbr"}


class _Page(HTMLParser):
    """Collects the lang attribute, title, facts block and data-fact texts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lang = None
        self.has_body = False
        self.title = ""
        self.facts_raw = None
        self.fact_texts: dict[str, list[str]] = {}
        self._open: list[tuple[str, str | None]] = []  # (tag, data-fact key)
        self._in_title = False
        self._in_facts = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.lang = a.get("lang")
        elif tag == "body":
            self.has_body = True
        elif tag == "title":
            self._in_title = True
        elif tag == "script" and a.get("id") == "uptrend-facts":
            self._in_facts = True
            self.facts_raw = ""
        if tag in _VOID:
            return
        key = a.get("data-fact")
        if key:
            self.fact_texts.setdefault(key, []).append("")
        self._open.append((tag, key))

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag == "script":
            self._in_facts = False
        for i in range(len(self._open) - 1, -1, -1):
            if self._open[i][0] == tag:
                del self._open[i:]
                break

    def handle_data(self, data):
        if self._in_facts:
            self.facts_raw += data
            return
        if self._in_title:
            self.title += data
        open_keys = {key for _, key in self._open if key}
        for key in open_keys:
            self.fact_texts[key][-1] += data


def _check_facts_block(raw, facts: Facts) -> list[str]:
    if raw is None:
        return ['missing <script type="application/json" id="uptrend-facts"> block']
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return [f"uptrend-facts is not valid JSON: {e}"]
    if not isinstance(data, dict):
        return ["uptrend-facts must be a JSON object"]
    problems = []
    for key in FACTS_KEYS:
        expected = getattr(facts, key)
        got = data.get(key)
        if isinstance(expected, float):
            same = isinstance(got, (int, float)) and abs(float(got) - expected) < 0.05
        else:
            same = got == expected
        if not same:
            problems.append(f"uptrend-facts {key}={got!r}, expected {expected!r}")
    return problems


def _numbers(text: str) -> list[float]:
    return [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)]


def _shows(key: str, text: str, facts: Facts) -> bool:
    text = text.replace("％", "%")
    if key == "ratio_pct":
        return any(abs(float(n) - facts.ratio_pct) < 0.05
                   for n in re.findall(r"(\d+(?:\.\d+)?)\s*%", text))
    if key == "count":
        return facts.count in _numbers(text)
    return any(abs(n - facts.score) < 0.05 or n == round(facts.score) for n in _numbers(text))


def _check_visible_numbers(page: _Page, facts: Facts) -> list[str]:
    labels = {"ratio_pct": f"{facts.ratio_pct}%", "count": str(facts.count),
              "score": str(round(facts.score))}
    problems = []
    for key in VISIBLE_KEYS:
        texts = page.fact_texts.get(key, [])
        if not texts:
            problems.append(f'visible text does not show {labels[key]} in a data-fact="{key}" element')
            continue
        wrong = [t.strip() for t in texts if not _shows(key, t, facts)]
        if wrong:
            problems.append(f'data-fact="{key}" shows {wrong!r}, expected {labels[key]}')
    return problems


def verify_html(html: str, facts: Facts, lang: str) -> list[str]:
    problems = []
    if len(html.encode("utf-8")) > MAX_BYTES:
        problems.append(f"page is larger than {MAX_BYTES} bytes")
    page = _Page()
    page.feed(html)
    page_lang = (page.lang or "").lower()
    if page_lang.split("-")[0] != lang:
        problems.append(f'<html lang> is {page.lang!r}, expected "{lang}"')
    if not page.has_body:
        problems.append("missing <body> tag")
    if not page.title.strip():
        problems.append("missing <title>")
    problems += _check_facts_block(page.facts_raw, facts)
    problems += _check_visible_numbers(page, facts)
    for pattern, label in _EXTERNAL:
        if pattern.search(html):
            problems.append(f"{label}: pages must be self-contained (no external resources)")
    return problems
