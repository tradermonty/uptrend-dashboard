"""Ask Claude, with the uptrend-analyzer and eli5 skills, to write the day's pages.

Flow:
1. ``sync_skills`` uploads the skills in ``claude_skills/`` to the Skills API
   the first time, and a new version only when their files change. Skill IDs
   and the file hash are kept in ``claude_skills/registry.json``.
2. ``generate_pages`` uploads the CSV files, runs one conversation in a code
   execution container with both skills loaded, and downloads the HTML files
   Claude leaves in ``$OUTPUT_DIR``.
3. Each page goes through ``verify_html``. If a check fails, the problems are
   sent back in the same container for a fix, up to ``FIX_ROUNDS`` times.
"""

import hashlib
import json
import logging
from pathlib import Path

from explainer.facts import Facts
from explainer.verify import verify_html

MODEL = "claude-opus-5-5"
EFFORT = "high"
MAX_TOKENS = 64000
MAX_CONTINUATIONS = 10
FIX_ROUNDS = 2
OUTPUT_TOKEN_BUDGET = 400_000  # whole run, all turns; ~$8 at $20/MTok
LANGS = ("ja", "en")
BETAS = ["server-side-fallback-2026-07-01"]
CODE_EXECUTION = {"type": "code_execution_20260521", "name": "code_execution"}
# (tool result block type, inner result type): bash commands and Python both return files
RESULT_TYPES = {"bash_code_execution_tool_result": "bash_code_execution_result",
                "code_execution_tool_result": "code_execution_result"}
log = logging.getLogger(__name__)


class GenerationError(RuntimeError):
    pass


def page_name(lang: str) -> str:
    return f"uptrend-{lang}.html"


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------
def _skill_files(skill_dir: Path) -> list[tuple[str, bytes]]:
    files = []
    for path in sorted(skill_dir.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            files.append((path.relative_to(skill_dir.parent).as_posix(), path.read_bytes()))
    return files


def _hash(files: list[tuple[str, bytes]]) -> str:
    h = hashlib.sha256()
    for name, data in files:
        h.update(name.encode() + b"\0" + data + b"\0")
    return h.hexdigest()


def _find_skill(client, name: str):
    for skill in client.skills.list(source="custom", limit=100):
        if skill.display_name == name:
            return skill
    return None


def sync_skills(client, skills_dir: Path, registry_path: Path) -> list[dict]:
    """Make sure every skill in ``skills_dir`` is uploaded and current; return container params."""
    registry = json.loads(registry_path.read_text()) if registry_path.exists() else {}
    params = []
    for skill_dir in sorted(p for p in skills_dir.iterdir() if (p / "SKILL.md").exists()):
        name = skill_dir.name
        files = _skill_files(skill_dir)
        digest = _hash(files)
        entry = registry.get(name)
        if entry is None:
            existing = _find_skill(client, name)
            if existing is not None:  # registry was lost: add a version instead of a duplicate
                version = client.skills.versions.create(existing.id, files=files)
                entry = {"skill_id": existing.id, "version": version.id, "hash": digest}
            else:
                skill = client.skills.create(files=files, display_name=name)
                entry = {"skill_id": skill.id, "version": skill.latest_version_id, "hash": digest}
        elif entry["hash"] != digest:
            version = client.skills.versions.create(entry["skill_id"], files=files)
            entry = {**entry, "version": version.id, "hash": digest}
        registry[name] = entry
        params.append({"type": "custom", "skill_id": entry["skill_id"], "version": entry["version"]})
    registry_path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n")
    return params


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
SYSTEM = """You write a daily, picture-first explainer of the US stock market's uptrend ratio \
for a public website. Two skills are loaded in your container: uptrend-analyzer (computes the \
breadth score) and eli5 (how to explain it to someone new to the topic). Follow both skills.

Hard rules for every page:
- Every number on the page comes from the uploaded CSV files or the analyzer's JSON report. \
Never estimate, round differently, or recall numbers from memory. Draw charts to scale from the data.
- No advice to buy or sell any security. Describe the analyzer's zone and exposure guidance \
as the tool's reading, and end with a one-line note that the page is educational, not investment advice.
- Past episodes may be shown only from this data, with a plain caveat that a few past cases \
do not predict the next one."""

PAGE_RULES = """Page requirements (both pages):
1. A complete standalone HTML document: <!doctype html>, <html lang="{{lang}}">, <meta charset>, \
<meta name="viewport" content="width=device-width,initial-scale=1">, and a short <title>.
2. Everything inline (CSS and SVG). No external scripts, stylesheets, fonts, images or @import. \
Use a system font stack.
3. Works at 390px width with no horizontal scrolling; supports light and dark via \
prefers-color-scheme with colors defined as CSS custom properties.
4. Put this exact facts block in <head>, filled from the analyzer output:
   <script type="application/json" id="uptrend-facts">{"date": "YYYY-MM-DD", "ratio_pct": <market-wide \
ratio x 100, 1 decimal>, "count": <stocks in uptrend>, "total": <stocks tracked>, "score": <composite score, \
1 decimal>}</script>
5. Show the three key numbers in visible text, each wrapped in an element with a data-fact \
attribute: <span data-fact="ratio_pct">6.9%</span>, <span data-fact="count">183</span>, \
<span data-fact="score">22</span> (your values). Use the attribute only for these exact values.
6. Short: readable in about a minute. One idea per panel, a picture first, one or two lines of text."""

TASK = """Today's job.

The two uploaded CSV files are in your container (find them with \
`find / -name "uptrend_ratio_timeseries*.csv" -o -name "sector_summary*.csv" 2>/dev/null`). \
The container has no internet access, so run the uptrend-analyzer skill's script in offline mode:
  python3 <uptrend-analyzer skill dir>/scripts/uptrend_analyzer.py \\
      --timeseries-csv <timeseries csv> --sector-summary-csv <sector summary csv> --output-dir /tmp/reports

Then, using the eli5 skill, write two pages about the latest day in the data:
- uptrend-ja.html: Japanese, for Japanese individual investors new to market breadth.
- uptrend-en.html: English, for English-speaking individual investors. Write it natively, \
not as a word-for-word translation; the numbers must be identical.

{rules}

When both pages are final, copy them into $OUTPUT_DIR in a single bash command \
(`cp uptrend-ja.html uptrend-en.html "$OUTPUT_DIR"/`). Files elsewhere are not returned. \
Finish with one short line saying the files are saved."""


def build_task() -> str:
    return TASK.format(rules=PAGE_RULES.replace("{{lang}}", "ja or en"))


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------
def _call(client, messages: list, container: dict):
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM,
        messages=messages,
        container=container,
        tools=[CODE_EXECUTION],
        output_config={"effort": EFFORT},
        betas=BETAS,
        fallbacks="default",
    ) as stream:
        return stream.get_final_message()


def _run_turn(client, messages: list, skills: list, container_id: str | None, responses: list):
    """Run until Claude ends its turn, continuing through pause_turn. Returns the container id."""
    for _ in range(MAX_CONTINUATIONS):
        container = {"skills": skills} if container_id is None else {"id": container_id, "skills": skills}
        response = _call(client, messages, container)
        responses.append(response)
        if response.stop_reason == "refusal":
            raise GenerationError(f"Claude refused the request: {response.stop_details}")
        container_id = getattr(response.container, "id", None) or container_id
        spent = sum(getattr(r.usage, "output_tokens", 0) or 0 for r in responses)
        if spent > OUTPUT_TOKEN_BUDGET:
            raise GenerationError(f"output token budget exceeded ({spent} > {OUTPUT_TOKEN_BUDGET})")
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason == "max_tokens":
            log.warning("response hit max_tokens; checking the files saved so far")
        if response.stop_reason != "pause_turn":
            return container_id
    raise GenerationError(f"turn did not finish after {MAX_CONTINUATIONS} continuations")


def collect_output_files(client, responses: list) -> dict[str, str]:
    """Download every file Claude left in $OUTPUT_DIR; a later file with the same name wins."""
    files: dict[str, str] = {}
    for response in responses:
        for block in response.content:
            inner = RESULT_TYPES.get(getattr(block, "type", None))
            if inner is None:
                continue
            result = block.content
            if getattr(result, "type", None) != inner:
                log.warning("skipped code execution result of type %s", getattr(result, "type", None))
                continue
            for out in result.content:
                name = client.files.retrieve_metadata(out.file_id).filename
                files[name] = client.files.download(out.file_id).text()
    return files


def _problems(files: dict[str, str], facts: Facts) -> dict[str, list[str]]:
    problems = {}
    for lang in LANGS:
        name = page_name(lang)
        if name not in files:
            problems[name] = ["file was not saved to $OUTPUT_DIR"]
            continue
        found = verify_html(files[name], facts, lang)
        if found:
            problems[name] = found
    return problems


def _describe(problems: dict[str, list[str]]) -> str:
    return "\n".join(f"- {name}: {p}" for name, items in problems.items() for p in items)


def generate_pages(client, skills: list, timeseries_csv: Path, sector_csv: Path,
                   facts: Facts, usage_log: list | None = None) -> dict[str, str]:
    """Return {lang: html} for pages that passed every check, or raise GenerationError."""
    uploads = []
    for path in (timeseries_csv, sector_csv):
        meta = client.files.upload(file=(path.name, path.read_bytes(), "text/csv"))
        uploads.append({"type": "container_upload", "file_id": meta.id})
    try:
        return _converse(client, skills, uploads, facts, usage_log)
    finally:
        for upload in uploads:
            try:
                client.files.delete(upload["file_id"])
            except Exception as e:  # cleanup must not hide the real result
                log.warning("could not delete uploaded file %s: %s", upload["file_id"], e)


def _converse(client, skills: list, uploads: list, facts: Facts, usage_log) -> dict[str, str]:

    messages = [{"role": "user", "content": [*uploads, {"type": "text", "text": build_task()}]}]
    responses = usage_log if usage_log is not None else []
    container_id = _run_turn(client, messages, skills, None, responses)
    files = collect_output_files(client, responses)
    problems = _problems(files, facts)

    for _ in range(FIX_ROUNDS):
        if not problems:
            break
        messages.append({"role": "user", "content": (
            "The automatic check found these problems. The correct values come from the "
            "analyzer report and the CSV. Fix the pages and copy the corrected files into "
            f"$OUTPUT_DIR again:\n{_describe(problems)}")})
        start = len(responses)
        container_id = _run_turn(client, messages, skills, container_id, responses)
        files.update(collect_output_files(client, responses[start:]))
        problems = _problems(files, facts)

    if problems:
        raise GenerationError("pages failed the checks:\n" + _describe(problems))
    return {lang: files[page_name(lang)] for lang in LANGS}
