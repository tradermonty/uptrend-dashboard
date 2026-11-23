"""Per-run collection outcome manifest and coverage counters (Issue #6).

Every worksheet the run was expected to collect gets exactly one outcome:

- ``persisted``: fetched with total > 0 and written to the DB
- ``fetched``:   fetched with total > 0 in a dry run (nothing written)
- ``empty``:     fetched with total = 0 (an industry with no stock passing the
                 base filters); deliberately not written, and not a failure
- ``failed``:    the request or validation failed
- ``missing``:   expected but never attempted

Coverage counters reconcile: expected = fetched + failed + missing, where
fetched = persisted (or dry-run fetched) + empty. ``stored`` is the number of
expected worksheets that have a DB row for the session after the run (each
worksheet also records ``stored``, so a failure on a second same-day run next to
a row stored by the first run is visible), and ``reconciled`` is False when a
worksheet reported as persisted has no row. A run stopped by a fatal error
(``aborted``) still gets a manifest; worksheets it never reached are ``missing``.
"""

import json
import os
from pathlib import Path
from typing import Dict, Iterable, Optional

MANIFEST_VERSION = 1
MANIFEST_FILENAME = "collection_manifest.json"


def default_manifest_path() -> Path:
    """Manifest next to the DB the pages read (``DB_PATH``, default data/uptrend.db)."""
    return Path(os.environ.get("DB_PATH", "data/uptrend.db")).parent / MANIFEST_FILENAME

_NOT_STORED = ("empty", "failed", "missing")


def build_manifest(
    result,
    expected: Iterable[str],
    session_date: str,
    scope: str,
    dry_run: bool,
    stored: Optional[Iterable[str]],
    last_stored: Optional[Dict[str, Optional[str]]],
    generated_at: str,
    aborted: Optional[str] = None,
) -> dict:
    """Build the manifest dict for one collect_all run.

    Args:
        result: CollectResult (succeeded: {worksheet: (count, total)}, failed: [worksheet]).
        expected: Worksheets the run's scope covers, in collection order.
        stored: Worksheets with a DB row for ``session_date`` after the run; None in a dry run.
        last_stored: Latest stored date per worksheet (for rows not stored this session).
        aborted: Name of the fatal error that stopped the run, or None when it completed.
    """
    expected = list(expected)
    failed = set(result.failed)
    last_stored = last_stored or {}
    stored_set = None if stored is None else set(stored)
    worksheets = {}
    for ws in expected:
        if ws in result.succeeded:
            count, total = result.succeeded[ws]
            if total == 0:
                outcome = "empty"
            else:
                outcome = "fetched" if dry_run else "persisted"
            entry = {"outcome": outcome, "count": int(count), "total": int(total)}
        elif ws in failed:
            entry = {"outcome": "failed"}
        else:
            entry = {"outcome": "missing"}
        if entry["outcome"] in _NOT_STORED:
            entry["last_stored"] = last_stored.get(ws)
        if stored_set is not None:
            entry["stored"] = ws in stored_set
        worksheets[ws] = entry

    def n(outcome):
        return sum(1 for e in worksheets.values() if e["outcome"] == outcome)

    persisted = n("persisted")
    fetched = persisted + n("fetched") + n("empty")
    if stored_set is None:
        stored_count = None
        reconciled = True
    else:
        stored_count = sum(1 for ws in expected if ws in stored_set)
        reconciled = all(ws in stored_set for ws, e in worksheets.items()
                         if e["outcome"] == "persisted")
    coverage = {
        "expected": len(expected),
        "fetched": fetched,
        "persisted": persisted,
        "empty": n("empty"),
        "failed": n("failed"),
        "missing": n("missing"),
        "stored": stored_count,
    }
    coverage["reconciled"] = bool(
        reconciled and coverage["expected"] == fetched + coverage["failed"] + coverage["missing"]
    )
    return {
        "version": MANIFEST_VERSION,
        "session_date": session_date,
        "scope": scope,
        "dry_run": bool(dry_run),
        "generated_at": generated_at,
        "aborted": aborted,
        "coverage": coverage,
        "worksheets": worksheets,
    }


def write_manifest(manifest: dict, path) -> bool:
    """Write the manifest atomically (temp file + rename).

    Returns False and leaves the file alone when only ``generated_at`` would change,
    so a repeat run with the same outcome does not produce a new data commit.
    """
    path = Path(path)
    previous = load_manifest(path)
    if previous is not None and _without_timestamp(previous) == _without_timestamp(manifest):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return True


def _without_timestamp(manifest: dict) -> dict:
    return {k: v for k, v in manifest.items() if k != "generated_at"}


def load_manifest(path=None) -> Optional[dict]:
    """The manifest dict, or None when the file is absent or unreadable."""
    if path is None:
        path = default_manifest_path()
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def coverage_caption(manifest: Optional[dict]) -> str:
    """One line such as 'Collection 2026-11-20: 158 of 161 stored · 2 empty · 1 failed'."""
    if not manifest or not manifest.get("coverage") or "session_date" not in manifest:
        return ""
    c = manifest["coverage"]
    stored = c.get("stored")
    head = (f"{stored} of {c['expected']} stored" if stored is not None
            else f"{c['fetched']} of {c['expected']} fetched (dry run)")
    parts = [head]
    for key, label in (("empty", "empty (no stocks match the base filters)"),
                       ("failed", "failed"), ("missing", "not attempted")):
        if c.get(key):
            parts.append(f"{c[key]} {label}")
    if manifest.get("aborted"):
        parts.append(f"run aborted ({manifest['aborted']})")
    scope = manifest.get("scope", "all")
    label = f"Collection {manifest['session_date']}" + ("" if scope == "all" else f" ({scope} only)")
    return f"{label}: " + " · ".join(parts)
