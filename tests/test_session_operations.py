"""Offline workflow gates, read-only diagnosis, and historical source evidence."""

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("policy_code,gh_code,expected", [(0, 0, 0), (3, 0, 0), (1, 0, 1), (0, 1, 1)])
def test_preflight_shell_gates_without_real_github_or_finviz(tmp_path, policy_code, gh_code, expected):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, text in {
        "gh": '#!/bin/sh\n[ "$GH_CODE" -eq 0 ] || exit "$GH_CODE"\necho "2026-11-13T21:10:00Z"\n',
        "python": '#!/bin/sh\n[ "$POLICY_CODE" -eq 0 ] || exit "$POLICY_CODE"\necho 2026-11-13\n',
    }.items():
        path = bindir / name
        path.write_text(text)
        path.chmod(0o755)
    output = tmp_path / "outputs"
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", GH_CODE=str(gh_code),
               POLICY_CODE=str(policy_code), GITHUB_REPOSITORY="test/repo", GITHUB_RUN_ID="123", GITHUB_OUTPUT=str(output))
    run = subprocess.run(["bash", str(ROOT / "scripts/session_preflight.sh")], env=env, capture_output=True, text=True)
    assert run.returncode == expected
    saved = output.read_text() if output.exists() else ""
    if policy_code == 0 and gh_code == 0:
        assert saved == "eligible=true\nsession_date=2026-11-13\n"
    elif policy_code == 3 and gh_code == 0:
        assert saved == "eligible=false\n"
    else:
        assert "eligible=true" not in saved


def test_workflow_requires_eligible_preflight_for_every_mutating_step():
    text = (ROOT / ".github/workflows/collect-data.yml").read_text()
    assert "actions: read" in text
    assert "run: bash scripts/session_preflight.sh" in text
    for name in ["Collect data from Finviz", "Export CSV files", "Commit and push if data changed"]:
        block = text.split(f"- name: {name}\n", 1)[1].split("\n      - name:", 1)[0]
        assert "if: steps.session.outputs.eligible == 'true'" in block
        assert "always()" not in block and "continue-on-error" not in block
    assert '--date "$COLLECTION_SESSION"' in text


def test_audit_flags_non_sessions_and_malformed_dates_without_mutating(tmp_path):
    from audit_collection_dates import audit_collection_dates
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE uptrend_raw (date TEXT, worksheet TEXT, count INTEGER, total INTEGER)")
        con.executemany("INSERT INTO uptrend_raw VALUES (?, 'all', 1, 2)",
                        [("2026-11-13",), ("2026-08-29",), ("2026-11-26",), ("20261113",)])
    original = digest(path)
    result = audit_collection_dates(str(path))
    assert result["rows_checked"] == 4
    assert result["anomalies"] == [
        {"date": "2026-08-29", "rows": 1, "reason": "non_session_date"},
        {"date": "2026-11-26", "rows": 1, "reason": "non_session_date"},
        {"date": "20261113", "rows": 1, "reason": "invalid_date_format"},
    ]
    assert digest(path) == original
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as con:
        assert len(con.execute("SELECT * FROM sqlite_master").fetchall()) == 1


def test_audit_missing_path_cannot_create_database(tmp_path):
    from audit_collection_dates import audit_collection_dates
    path = tmp_path / "absent.db"
    with pytest.raises(sqlite3.OperationalError):
        audit_collection_dates(str(path))
    assert not path.exists()


def test_audit_calendar_unknown_is_reported(tmp_path, mocker):
    from audit_collection_dates import audit_collection_dates
    path = tmp_path / "source.db"
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE uptrend_raw (date TEXT)")
        con.execute("INSERT INTO uptrend_raw VALUES ('2026-11-13')")
    mocker.patch("audit_collection_dates.session_calendar", side_effect=ValueError("unknown"))
    assert audit_collection_dates(str(path))["anomalies"][0]["reason"] == "calendar_unknown"


def test_historical_import_uses_source_artifact_with_receipt(tmp_path):
    from import_excel import import_excel
    from src.db_client import DBClient
    source = tmp_path / "historical.xlsx"
    with pd.ExcelWriter(source, engine="openpyxl") as writer:
        pd.DataFrame({"Date": ["2024-01-02"], "Count": [5], "Total": [10]}).to_excel(writer, sheet_name="all", index=False)
    receipt = {"source_sha256": digest(source), "source_date_range": ["2024-01-02", "2024-01-02"]}
    target = tmp_path / "scratch.db"
    assert import_excel(str(source), db_path=str(target)) == {"all": 1}
    assert digest(source) == receipt["source_sha256"]
    assert DBClient(str(target)).fetch_raw_data("all")["count"].tolist() == [5]


def test_audit_cli_serializes_blob_labels_without_traceback_or_mutation(tmp_path):
    path = tmp_path / "blob-label.db"
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE uptrend_raw (date TEXT)")
        con.execute("INSERT INTO uptrend_raw VALUES (?)", (b"2026-11-13",))
    original = digest(path)
    run = subprocess.run([sys.executable, str(ROOT / "audit_collection_dates.py"), "--db", str(path)],
                         capture_output=True, text=True)
    assert run.returncode == 1
    result = json.loads(run.stdout)
    anomaly = result["anomalies"][0]
    assert anomaly["reason"] == "invalid_date_format"
    assert anomaly["storage_type"] == "blob"
    assert anomaly["date_hex"] == b"2026-11-13".hex()
    assert "Traceback" not in run.stderr
    assert digest(path) == original
