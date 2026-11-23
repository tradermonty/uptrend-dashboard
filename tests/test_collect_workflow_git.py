"""Run the collect workflow's git steps in a throwaway repo (PR #45 review).

The step scripts are taken verbatim from .github/workflows/collect-data.yml and run
with the shell GitHub Actions uses (bash -eo pipefail) against a local bare remote.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/collect-data.yml"
DATA_FILES = ["uptrend.db", "uptrend_ratio_timeseries.csv", "sector_summary.csv",
              "industry_summary.csv", "sector_dispersion.csv"]
SESSION = "2026-11-13"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")


def step_script(name: str) -> str:
    text = WORKFLOW.read_text()
    block = text[text.index(f"- name: {name}\n"):]
    nxt = block.find("\n      - name:", 1)
    block = block if nxt == -1 else block[:nxt]
    lines = []
    for line in block[block.index("run: |") + len("run: |"):].splitlines()[1:]:
        if line.strip() and not line.startswith(" " * 10):
            break                                         # end of the run block
        lines.append(line[10:])
    return "\n".join(lines)


# The developer's global/system git config (signing, hooks, pull.rebase...) must not leak in
GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(cwd, *args, check=True):
    return subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True,
                          env=GIT_ENV)


def manifest(**extra):
    m = {"version": 1, "session_date": SESSION, "scope": "all", "dry_run": False,
         "generated_at": extra.pop("generated_at", "t0"), "aborted": None,
         "coverage": {"expected": 161, "fetched": 160, "persisted": 160, "empty": 0,
                      "failed": 1, "missing": 0, "stored": 160, "reconciled": True},
         "worksheets": {}}
    m.update(extra)
    return json.dumps(m, indent=2) + "\n"


class Sandbox:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.remote = tmp_path / "remote.git"
        git(tmp_path, "init", "-q", "--bare", "-b", "main", str(self.remote))
        seed = self.clone("seed")
        shutil.copytree(ROOT / "src", seed / "src", ignore=shutil.ignore_patterns("__pycache__"))
        (seed / "data").mkdir()
        for f in DATA_FILES:
            (seed / "data" / f).write_text("v1\n")
        (seed / "data" / "collection_manifest.json").write_text(
            manifest(session_date="2026-11-12"))
        self.commit_all(seed, "base")
        git(seed, "push", "-q", "origin", "main")

    def clone(self, name):
        path = self.tmp / name
        git(self.tmp, "clone", "-q", str(self.remote), str(path))
        git(path, "config", "user.name", "t")
        git(path, "config", "user.email", "t@t")
        return path

    @staticmethod
    def commit_all(path, msg):
        git(path, "add", "-A")
        git(path, "commit", "-qm", msg)

    def run_step(self, cwd, name, ref="refs/heads/main"):
        runner_temp = self.tmp / f"runner_temp_{cwd.name}"
        runner_temp.mkdir(exist_ok=True)
        env = {**GIT_ENV, "RUNNER_TEMP": str(runner_temp), "COLLECTION_SESSION": SESSION,
               "GITHUB_REF": ref,
               "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}"}
        script = self.tmp / "step.sh"
        script.write_text(step_script(name))
        return subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", str(script)],
                              cwd=cwd, env=env, capture_output=True, text=True)

    def remote_file(self, path):
        return git(self.tmp, "--git-dir", str(self.remote), "show", f"main:{path}").stdout


def write_run(path, db="v2\n", **manifest_extra):
    (path / "data" / "uptrend.db").write_text(db)
    (path / "data" / "collection_manifest.json").write_text(manifest(**manifest_extra))


COMMIT = "Commit and push if data changed"
FAILURE = "Publish collection manifest after a failed run"


@pytest.fixture
def box(tmp_path):
    return Sandbox(tmp_path)


def test_failed_run_publishes_only_a_marked_manifest(box):
    run = box.clone("run")
    write_run(run)
    box.commit_all(run, "unpushed data commit")          # push failed in the commit step
    result = box.run_step(run, FAILURE)
    assert result.returncode == 0, result.stderr
    assert box.remote_file("data/uptrend.db") == "v1\n"
    m = json.loads(box.remote_file("data/collection_manifest.json"))
    assert m["data_published"] is False and m["session_date"] == SESSION


def test_crash_without_manifest_replaces_previous_sessions_manifest(box):
    run = box.clone("run")
    (run / "data" / "uptrend.db").write_text("v2\n")     # crashed before writing a manifest
    assert box.run_step(run, FAILURE).returncode == 0
    m = json.loads(box.remote_file("data/collection_manifest.json"))
    assert (m["session_date"], m["coverage"], m["data_published"]) == (SESSION, None, False)


def test_rerun_after_failure_step_publishes_its_data(box):
    first = box.clone("first")
    rerun = box.clone("rerun")                           # re-run checks out the same SHA
    write_run(first, generated_at="t1")
    assert box.run_step(first, FAILURE).returncode == 0
    write_run(rerun, db="v3\n", generated_at="t2")
    result = box.run_step(rerun, COMMIT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert box.remote_file("data/uptrend.db") == "v3\n"
    m = json.loads(box.remote_file("data/collection_manifest.json"))
    assert m["generated_at"] == "t2" and "data_published" not in m


def test_commit_still_refuses_a_real_data_conflict(box):
    other = box.clone("other")
    run = box.clone("run")
    (other / "data" / "uptrend.db").write_text("other\n")
    box.commit_all(other, "someone else's data")
    git(other, "push", "-q", "origin", "main")
    write_run(run)
    result = box.run_step(run, COMMIT)
    assert result.returncode != 0
    assert box.remote_file("data/uptrend.db") == "other\n"


def test_rerun_with_identical_manifest_clears_the_failed_marker(box):
    first = box.clone("first")
    rerun = box.clone("rerun")
    write_run(first)
    assert box.run_step(first, FAILURE).returncode == 0
    (rerun / "data" / "uptrend.db").write_text("v3\n")
    # collect.py skipped rewriting: same outcome as the checked-out manifest
    (rerun / "data" / "collection_manifest.json").write_text(
        manifest(session_date="2026-11-12"))
    git(rerun, "checkout", "--", "data/collection_manifest.json")
    result = box.run_step(rerun, COMMIT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert box.remote_file("data/uptrend.db") == "v3\n"
    m = json.loads(box.remote_file("data/collection_manifest.json"))
    assert m["session_date"] == SESSION and "data_published" not in m


def test_branch_dispatch_never_pushes_branch_code_to_main(box):
    run = box.clone("run")
    git(run, "checkout", "-qb", "feature")
    (run / "src" / "new_code.py").write_text("x = 1\n")
    box.commit_all(run, "unreviewed code")
    write_run(run)
    for step in (COMMIT, FAILURE):
        assert box.run_step(run, step, ref="refs/heads/feature").returncode == 0
    assert box.remote_file("data/uptrend.db") == "v1\n"
    ls = git(box.tmp, "--git-dir", str(box.remote), "ls-tree", "-r", "--name-only", "main").stdout
    assert "src/new_code.py" not in ls


def test_nothing_changed_pushes_nothing(box):
    run = box.clone("run")
    before = git(box.tmp, "--git-dir", str(box.remote), "rev-parse", "main").stdout
    result = box.run_step(run, COMMIT)
    assert result.returncode == 0 and "No data changes to commit" in result.stdout
    assert git(box.tmp, "--git-dir", str(box.remote), "rev-parse", "main").stdout == before
