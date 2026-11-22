"""Ask Claude to write one explainer page per language from a precomputed brief.

Python does all the analysis (``explainer.brief``). Claude gets the eli5 skill
text as instructions plus the brief as JSON, and answers with one HTML
document. There is no code execution container, so each page is a single
request. A page that fails ``verify_html`` is sent back with the problems for
up to ``FIX_ROUNDS`` fixes in the same conversation.
"""

import json
import logging
import re
from pathlib import Path

from explainer.facts import Facts
from explainer.verify import verify_html

MODEL = "claude-opus-5-5"
EFFORT = "high"
MAX_TOKENS = 48000
FIX_ROUNDS = 2
LANGS = ("ja", "en")
BETAS = ["server-side-fallback-2026-07-01"]
PRICE_PER_MTOK = {"input": 4.0, "output": 20.0, "cache_read": 0.4, "cache_write": 5.0}
COST_BUDGET_USD = 3.0  # hard cap for the whole run: a request is sent only if its worst case fits
log = logging.getLogger(__name__)


class GenerationError(RuntimeError):
    pass


AUDIENCE = {
    "ja": ("ja", "Japanese", "Japanese individual investors who are new to market breadth"),
    "en": ("en", "English", "English-speaking individual investors who are new to market breadth"),
}

SYSTEM = """You write a daily, picture-first explainer of the US stock market's uptrend ratio \
for a public website. Follow the eli5 skill below for how to explain.

Hard rules:
- Use only numbers that appear in the data brief. Never compute new statistics, estimate, or \
recall numbers from memory. Draw every chart to scale from the brief's values.
- No advice to buy or sell any security. Present the score's zone and exposure guidance as the \
tool's reading, and end with a one-line note that the page is educational, not investment advice.
- Past episodes may be shown only from past_oversold_episodes, with a plain caveat that a few \
past cases do not predict the next one.
- Define the uptrend ratio simply as the share of tracked US stocks that are in an uptrend. Do \
not invent a more specific technical definition.

Page requirements:
1. Answer with one complete standalone HTML document and nothing else: <!doctype html>, \
<html lang="..."> as requested, <meta charset="utf-8">, \
<meta name="viewport" content="width=device-width,initial-scale=1">, and a short <title>.
2. Everything inline (CSS and SVG). No external scripts, stylesheets, fonts, images or @import. \
Use a system font stack.
3. Works at 390px width with no horizontal scrolling; supports light and dark via \
prefers-color-scheme with colors defined as CSS custom properties.
4. Put this facts block in <head>, copied from brief.facts:
   <script type="application/json" id="uptrend-facts">{"date": ..., "ratio_pct": ..., \
"count": ..., "total": ..., "score": ...}</script>
5. Show the three key numbers in visible text, each in an element with a data-fact attribute: \
<span data-fact="ratio_pct">6.9%</span>, <span data-fact="count">183</span>, \
<span data-fact="score">22</span> (the brief's values). Use the attribute only for these values.
6. Short: readable in about a minute. One idea per panel, a picture first, one or two lines of text.

<eli5_skill>
{skill}
</eli5_skill>"""


def build_system(skill_md: str) -> str:
    return SYSTEM.replace("{skill}", skill_md.strip())


def build_request(brief: dict, lang: str) -> str:
    code, language, audience = AUDIENCE[lang]
    return (f'Write the page in {language} (<html lang="{code}">) for {audience}. '
            f"Write it natively in {language}, not as a translation.\n\n"
            f"<data_brief>\n{json.dumps(brief, ensure_ascii=False, indent=1)}\n</data_brief>")


_FENCE = re.compile(r"^```(?:html)?\s*\n(.*?)\n```\s*$", re.S)


def extract_html(response) -> str:
    """The HTML document from the answer, without any fence, preamble or trailing note."""
    text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()
    lower = text.lower()
    start = lower.find("<!doctype")
    if start < 0:
        start = lower.find("<html")
    end = lower.rfind("</html>")
    if start >= 0 and end > start:
        return text[start:end + len("</html>")]
    m = _FENCE.match(text)
    return m.group(1).strip() if m else text


def cost_usd(usage) -> float:
    def n(attr):
        return getattr(usage, attr, 0) or 0
    return (n("input_tokens") * PRICE_PER_MTOK["input"]
            + n("output_tokens") * PRICE_PER_MTOK["output"]
            + n("cache_read_input_tokens") * PRICE_PER_MTOK["cache_read"]
            + n("cache_creation_input_tokens") * PRICE_PER_MTOK["cache_write"]) / 1e6


def _call(client, system: str, messages: list):
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=messages,
        output_config={"effort": EFFORT},
        betas=BETAS,
        fallbacks="default",
    ) as stream:
        return stream.get_final_message()


def _ask(client, system: str, messages: list, responses: list):
    spent = sum(cost_usd(r.usage) for r in responses)
    worst_next = MAX_TOKENS * PRICE_PER_MTOK["output"] / 1e6
    if spent + worst_next > COST_BUDGET_USD:
        raise GenerationError(
            f"cost budget: ${spent:.2f} spent + up to ${worst_next:.2f} for the next request "
            f"would pass ${COST_BUDGET_USD:.2f}")
    response = _call(client, system, messages)
    responses.append(response)
    if getattr(response, "model", MODEL) != MODEL:
        log.warning("served by %s (fallback); cost estimate uses %s prices", response.model, MODEL)
    if response.stop_reason == "refusal":
        raise GenerationError(f"Claude refused the request: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise GenerationError("response hit max_tokens before the page was finished")
    messages.append({"role": "assistant", "content": response.content})
    return response


def generate_page(client, system: str, brief: dict, lang: str, facts: Facts,
                  responses: list) -> str:
    messages = [{"role": "user", "content": build_request(brief, lang)}]
    html = extract_html(_ask(client, system, messages, responses))
    problems = verify_html(html, facts, lang)
    for _ in range(FIX_ROUNDS):
        if not problems:
            return html
        log.warning("%s page failed checks: %s", lang, problems)
        messages.append({"role": "user", "content": (
            "The automatic check found these problems. Use the data brief's values. "
            "Answer with the corrected complete HTML document only:\n"
            + "\n".join(f"- {p}" for p in problems))})
        html = extract_html(_ask(client, system, messages, responses))
        problems = verify_html(html, facts, lang)
    if problems:
        raise GenerationError(f"{lang} page failed the checks:\n" + "\n".join(problems))
    return html


def generate_pages(client, skill_md_path: Path, brief: dict, facts: Facts,
                   usage_log: list | None = None) -> dict[str, str]:
    """Return {lang: html} for pages that passed every check, or raise GenerationError."""
    system = build_system(Path(skill_md_path).read_text(encoding="utf-8"))
    responses = usage_log if usage_log is not None else []
    return {lang: generate_page(client, system, brief, lang, facts, responses) for lang in LANGS}
