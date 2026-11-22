"""Claude API orchestration, exercised against a fake client (no network, no cost)."""

import json
from types import SimpleNamespace as NS

import pytest

from explainer.facts import Facts
from explainer.generate import (
    COST_BUDGET_USD,
    MODEL,
    GenerationError,
    build_request,
    build_system,
    cost_usd,
    extract_html,
    generate_pages,
)

FACTS = Facts(date="2026-11-20", ratio_pct=6.9, count=183, total=2661,
              score=22.4, zone="Cautious", exposure="Defensive (30-60%)")
BRIEF = {"facts": FACTS.to_dict(), "recent": [{"date": "2026-11-20", "ratio_pct": 6.9}]}


def _page(lang, count=183):
    data = {"date": "2026-11-20", "ratio_pct": 6.9, "count": count, "total": 2661, "score": 22.4}
    return (f'<!doctype html><html lang="{lang}"><head><title>x</title>'
            f'<script type="application/json" id="uptrend-facts">{json.dumps(data)}</script>'
            f'</head><body><p><b data-fact="count">{count}</b> / 2,661 = '
            f'<b data-fact="ratio_pct">6.9%</b>, score <b data-fact="score">22</b></p></body></html>')


def _response(text, stop="end_turn", input_tokens=10_000, output_tokens=10_000):
    blocks = [NS(type="thinking", thinking=""), NS(type="text", text=text)]
    return NS(stop_reason=stop, content=blocks, stop_details=None, model=MODEL,
              usage=NS(input_tokens=input_tokens, output_tokens=output_tokens,
                       cache_read_input_tokens=0, cache_creation_input_tokens=0))


class FakeStream:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.response


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = NS(messages=NS(stream=self._stream))

    def _stream(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})  # snapshot
        return FakeStream(self.responses.pop(0))


@pytest.fixture
def skill(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text("---\nname: eli5\n---\nBig pictures, few words.\n")
    return path


class TestGeneratePages:

    def test_one_request_per_language_without_container(self, skill):
        client = FakeClient([_response(_page("ja")), _response(_page("en"))])
        pages = generate_pages(client, skill, BRIEF, FACTS)
        assert set(pages) == {"ja", "en"}
        assert len(client.calls) == 2
        call = client.calls[0]
        assert call["model"] == MODEL
        assert "container" not in call and "tools" not in call
        assert "Big pictures, few words." in call["system"][0]["text"]
        assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
        assert '"ratio_pct": 6.9' in call["messages"][0]["content"]
        assert 'lang="ja"' in call["messages"][0]["content"]
        assert 'lang="en"' in client.calls[1]["messages"][0]["content"]

    def test_failed_check_asks_for_a_fix(self, skill):
        client = FakeClient([_response(_page("ja", count=999)), _response(_page("ja")),
                             _response(_page("en"))])
        pages = generate_pages(client, skill, BRIEF, FACTS)
        assert 'data-fact="count">183' in pages["ja"]
        fix = client.calls[1]["messages"]
        assert fix[-2]["role"] == "assistant"
        assert fix[-1]["role"] == "user" and "count" in fix[-1]["content"]

    def test_gives_up_after_fix_rounds(self, skill):
        client = FakeClient([_response(_page("ja", count=999)) for _ in range(3)])
        with pytest.raises(GenerationError, match="count"):
            generate_pages(client, skill, BRIEF, FACTS)

    def test_refusal_raises(self, skill):
        client = FakeClient([_response("", stop="refusal")])
        with pytest.raises(GenerationError, match="refus"):
            generate_pages(client, skill, BRIEF, FACTS)

    def test_max_tokens_raises(self, skill):
        client = FakeClient([_response("<!doctype html><html", stop="max_tokens")])
        with pytest.raises(GenerationError, match="max_tokens"):
            generate_pages(client, skill, BRIEF, FACTS)

    def test_cost_budget_stops_further_requests(self, skill):
        # spent so far + the next request's worst case must stay within the budget
        expensive = _response(_page("ja", count=999), input_tokens=0,
                              output_tokens=int(COST_BUDGET_USD / 20 * 1e6) - 20_000)
        client = FakeClient([expensive, _response(_page("ja"))])
        with pytest.raises(GenerationError, match="budget"):
            generate_pages(client, skill, BRIEF, FACTS)
        assert len(client.calls) == 1

    def test_usage_log_collects_every_response(self, skill):
        log = []
        client = FakeClient([_response(_page("ja")), _response(_page("en"))])
        generate_pages(client, skill, BRIEF, FACTS, usage_log=log)
        assert len(log) == 2


class TestHelpers:

    def test_extract_html_strips_fence_and_preamble(self):
        html = _page("ja")
        assert extract_html(_response(f"```html\n{html}\n```")) == html
        assert extract_html(_response(f"Here it is:\n{html}")) == html
        assert extract_html(_response(html)) == html

    def test_extract_html_drops_text_around_the_document(self):
        html = _page("ja")
        assert extract_html(_response(f"Here:\n```html\n{html}\n```\nDone.")) == html
        assert extract_html(_response(f"{html}\n\nNote: ok")) == html
        bare = html.replace("<!doctype html>", "")
        assert extract_html(_response(f"Sure!\n{bare}\nbye")) == bare

    def test_cost(self):
        usage = NS(input_tokens=1_000_000, output_tokens=100_000,
                   cache_read_input_tokens=0, cache_creation_input_tokens=0)
        assert cost_usd(usage) == pytest.approx(6.0)

    def test_system_embeds_skill_and_request_embeds_brief(self):
        assert "<eli5_skill>\nhello\n</eli5_skill>" in build_system("hello\n")
        assert "<data_brief>" in build_request(BRIEF, "en")
