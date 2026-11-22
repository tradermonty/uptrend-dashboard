"""Claude API orchestration, exercised against a fake client (no network, no cost)."""

import json
from types import SimpleNamespace as NS

import pytest

from explainer.facts import Facts
from explainer.generate import (
    MODEL,
    GenerationError,
    collect_output_files,
    generate_pages,
    sync_skills,
)

FACTS = Facts(date="2026-11-20", ratio_pct=6.9, count=183, total=2661,
              score=22.4, zone="Cautious", exposure="Defensive (30-60%)")


def _good_page(lang):
    data = {"date": "2026-11-20", "ratio_pct": 6.9, "count": 183, "total": 2661, "score": 22.4}
    return (f'<!doctype html><html lang="{lang}"><head><title>x</title>'
            f'<script type="application/json" id="uptrend-facts">{json.dumps(data)}</script>'
            f'</head><body><p><b data-fact="count">183</b> / 2,661 = <b data-fact="ratio_pct">6.9%</b>, '
            f'score <b data-fact="score">22</b></p></body></html>')


def _exec_result(*file_ids):
    return NS(type="bash_code_execution_tool_result",
              content=NS(type="bash_code_execution_result",
                         content=[NS(type="bash_code_execution_output", file_id=f) for f in file_ids]))


def _python_result(*file_ids):
    return NS(type="code_execution_tool_result",
              content=NS(type="code_execution_result",
                         content=[NS(type="code_execution_output", file_id=f) for f in file_ids]))


def _response(stop, blocks, container_id="cntr_1", output_tokens=5):
    container = NS(id=container_id) if container_id else None
    return NS(stop_reason=stop, content=blocks, container=container,
              usage=NS(input_tokens=10, output_tokens=output_tokens), stop_details=None, model=MODEL)


class FakeFiles:
    def __init__(self, contents):
        self.contents = contents  # file_id -> (filename, text)
        self.uploaded = []
        self.deleted = []

    def upload(self, file):
        self.uploaded.append(file[0])
        return NS(id=f"up_{len(self.uploaded)}")

    def delete(self, file_id):
        self.deleted.append(file_id)

    def retrieve_metadata(self, file_id):
        return NS(filename=self.contents[file_id][0])

    def download(self, file_id):
        return NS(text=lambda: self.contents[file_id][1])


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
    def __init__(self, responses, contents):
        self.responses = list(responses)
        self.calls = []
        self.files = FakeFiles(contents)
        self.beta = NS(messages=NS(stream=self._stream))

    def _stream(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})  # snapshot
        return FakeStream(self.responses.pop(0))


@pytest.fixture
def inputs(tmp_path):
    ts = tmp_path / "uptrend_ratio_timeseries.csv"
    ts.write_text("worksheet,date\n")
    sector = tmp_path / "sector_summary.csv"
    sector.write_text("Sector\n")
    return ts, sector


SKILLS = [{"type": "custom", "skill_id": "skill_a", "version": "v1"}]


class TestGeneratePages:

    def test_returns_both_pages_and_uses_skills(self, inputs):
        contents = {"f1": ("uptrend-ja.html", _good_page("ja")),
                    "f2": ("uptrend-en.html", _good_page("en"))}
        client = FakeClient([_response("end_turn", [_exec_result("f1", "f2")])], contents)
        pages = generate_pages(client, SKILLS, *inputs, FACTS)
        assert set(pages) == {"ja", "en"}
        call = client.calls[0]
        assert call["model"] == MODEL
        assert call["container"] == {"skills": SKILLS}
        assert {"type": "code_execution_20260521", "name": "code_execution"} in call["tools"]
        assert client.files.uploaded == ["uptrend_ratio_timeseries.csv", "sector_summary.csv"]
        uploads = [b for b in call["messages"][0]["content"] if b["type"] == "container_upload"]
        assert len(uploads) == 2

    def test_pause_turn_continues_in_same_container(self, inputs):
        contents = {"f1": ("uptrend-ja.html", _good_page("ja")),
                    "f2": ("uptrend-en.html", _good_page("en"))}
        first = _response("pause_turn", [NS(type="text", text="working")])
        second = _response("end_turn", [_exec_result("f1", "f2")])
        client = FakeClient([first, second], contents)
        generate_pages(client, SKILLS, *inputs, FACTS)
        follow = client.calls[1]
        assert follow["container"] == {"id": "cntr_1", "skills": SKILLS}
        assert follow["messages"][-1] == {"role": "assistant", "content": first.content}

    def test_failed_check_asks_claude_to_fix(self, inputs):
        bad = _good_page("ja").replace('"count": 183', '"count": 999')
        contents = {"f1": ("uptrend-ja.html", bad), "f2": ("uptrend-en.html", _good_page("en")),
                    "f3": ("uptrend-ja.html", _good_page("ja"))}
        client = FakeClient([_response("end_turn", [_exec_result("f1", "f2")]),
                             _response("end_turn", [_exec_result("f3")])], contents)
        pages = generate_pages(client, SKILLS, *inputs, FACTS)
        assert '"count": 183' in pages["ja"]
        fix_msg = client.calls[1]["messages"][-1]
        assert fix_msg["role"] == "user" and "count" in fix_msg["content"]

    def test_gives_up_after_fix_rounds(self, inputs):
        bad = _good_page("ja").replace('"count": 183', '"count": 999')
        contents = {"f1": ("uptrend-ja.html", bad), "f2": ("uptrend-en.html", _good_page("en"))}
        responses = [_response("end_turn", [_exec_result("f1", "f2")]) for _ in range(3)]
        with pytest.raises(GenerationError, match="count"):
            generate_pages(FakeClient(responses, contents), SKILLS, *inputs, FACTS)

    def test_refusal_raises(self, inputs):
        refused = _response("refusal", [])
        with pytest.raises(GenerationError, match="refus"):
            generate_pages(FakeClient([refused], {}), SKILLS, *inputs, FACTS)

    def test_missing_page_reported(self, inputs):
        contents = {"f1": ("uptrend-ja.html", _good_page("ja"))}
        responses = [_response("end_turn", [_exec_result("f1")]) for _ in range(3)]
        with pytest.raises(GenerationError, match="uptrend-en.html"):
            generate_pages(FakeClient(responses, contents), SKILLS, *inputs, FACTS)


    def test_python_saved_files_are_collected(self, inputs):
        contents = {"f1": ("uptrend-ja.html", _good_page("ja")),
                    "f2": ("uptrend-en.html", _good_page("en"))}
        client = FakeClient([_response("end_turn", [_python_result("f1", "f2")])], contents)
        assert set(generate_pages(client, SKILLS, *inputs, FACTS)) == {"ja", "en"}

    def test_refusal_without_container_raises_generation_error(self, inputs):
        refused = _response("refusal", [], container_id=None)
        with pytest.raises(GenerationError, match="refus"):
            generate_pages(FakeClient([refused], {}), SKILLS, *inputs, FACTS)

    def test_max_tokens_after_files_saved_still_returns_pages(self, inputs):
        contents = {"f1": ("uptrend-ja.html", _good_page("ja")),
                    "f2": ("uptrend-en.html", _good_page("en"))}
        client = FakeClient([_response("max_tokens", [_exec_result("f1", "f2")])], contents)
        assert set(generate_pages(client, SKILLS, *inputs, FACTS)) == {"ja", "en"}

    def test_output_token_budget_stops_the_run(self, inputs):
        responses = [_response("pause_turn", [], output_tokens=150_000) for _ in range(5)]
        with pytest.raises(GenerationError, match="budget"):
            generate_pages(FakeClient(responses, {}), SKILLS, *inputs, FACTS)

    def test_uploaded_csvs_are_deleted(self, inputs):
        contents = {"f1": ("uptrend-ja.html", _good_page("ja")),
                    "f2": ("uptrend-en.html", _good_page("en"))}
        client = FakeClient([_response("end_turn", [_exec_result("f1", "f2")])], contents)
        generate_pages(client, SKILLS, *inputs, FACTS)
        assert client.files.deleted == ["up_1", "up_2"]


class TestCollectOutputFiles:

    def test_later_file_with_same_name_wins(self):
        contents = {"a": ("uptrend-ja.html", "old"), "b": ("uptrend-ja.html", "new"),
                    "c": ("notes.txt", "x")}
        client = FakeClient([], contents)
        blocks = [_exec_result("a"), NS(type="text", text="hi"), _exec_result("b", "c")]
        assert collect_output_files(client, [_response("end_turn", blocks)]) == {
            "uptrend-ja.html": "new", "notes.txt": "x"}


class FakeSkills:
    def __init__(self, existing=()):
        self.created, self.versioned = [], []
        self.existing = list(existing)
        self.versions = NS(create=self._version)

    def list(self, source=None, limit=None):
        return self.existing

    def create(self, files, display_name=None):
        self.created.append(display_name)
        return NS(id=f"skill_{display_name}", latest_version_id="ver_1")

    def _version(self, skill_id, files):
        self.versioned.append(skill_id)
        return NS(id="ver_2")


class TestSyncSkills:

    @pytest.fixture
    def skills_dir(self, tmp_path):
        for name in ("eli5", "uptrend-analyzer"):
            d = tmp_path / "skills" / name
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(f"---\nname: {name}\n---\n")
        return tmp_path / "skills"

    def test_creates_then_reuses_then_versions(self, skills_dir, tmp_path):
        registry = tmp_path / "registry.json"
        client = NS(skills=FakeSkills())
        first = sync_skills(client, skills_dir, registry)
        assert client.skills.created == ["eli5", "uptrend-analyzer"]
        assert first == [{"type": "custom", "skill_id": "skill_eli5", "version": "ver_1"},
                         {"type": "custom", "skill_id": "skill_uptrend-analyzer", "version": "ver_1"}]
        assert sync_skills(client, skills_dir, registry) == first
        assert client.skills.versioned == []
        (skills_dir / "eli5" / "SKILL.md").write_text("---\nname: eli5\n---\nchanged\n")
        third = sync_skills(client, skills_dir, registry)
        assert client.skills.versioned == ["skill_eli5"]
        assert third[0]["version"] == "ver_2"

    def test_lost_registry_reuses_existing_skill(self, skills_dir, tmp_path):
        existing = [NS(id="skill_old", display_name="eli5", latest_version_id="ver_9")]
        client = NS(skills=FakeSkills(existing))
        params = sync_skills(client, skills_dir, tmp_path / "registry.json")
        assert client.skills.created == ["uptrend-analyzer"]
        assert client.skills.versioned == ["skill_old"]
        assert params[0] == {"type": "custom", "skill_id": "skill_old", "version": "ver_2"}

    def test_ignores_pycache(self, skills_dir, tmp_path):
        registry = tmp_path / "registry.json"
        client = NS(skills=FakeSkills())
        sync_skills(client, skills_dir, registry)
        cache = skills_dir / "eli5" / "__pycache__"
        cache.mkdir()
        (cache / "x.pyc").write_bytes(b"\0")
        sync_skills(client, skills_dir, registry)
        assert client.skills.versioned == []
