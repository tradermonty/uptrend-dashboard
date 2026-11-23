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




def mark_unpublished(path, session_date: str, generated_at: str,
                     reason: str = "IncompleteRun") -> dict:
    """Mark the manifest of a run whose data was not committed (``data_published: false``).

    Called by the workflow's failure step. The run's DB rows were not pushed, so the
    ``stored`` counts it measured on the runner do not describe the published DB.
    When the file is missing, unreadable or from an earlier session (the run crashed or
    timed out before writing one), it is replaced by a minimal manifest for
    ``session_date`` with no coverage.
    """
    manifest = load_manifest(path)
    if manifest is None or manifest.get("session_date") != session_date:
        manifest = {
            "version": MANIFEST_VERSION, "session_date": session_date, "scope": "all",
            "dry_run": False, "generated_at": generated_at, "aborted": reason,
            "coverage": None, "worksheets": {},
        }
    manifest["data_published"] = False
    write_manifest(manifest, path)
    return manifest


def _subset_coverage(manifest: dict, worksheets: Iterable[str]) -> Optional[dict]:
    """Coverage counters over the given worksheets, from the per-worksheet entries."""
    worksheets = list(worksheets)
    entries = [manifest["worksheets"][ws] for ws in worksheets if ws in manifest["worksheets"]]
    if not entries:
        return None  # e.g. a sectors-only run has nothing to say about industries
    # A worksheet the manifest does not list was not attempted by this run
    entries += [{"outcome": "missing", "stored": False}] * (len(worksheets) - len(entries))
    c = {k: sum(1 for e in entries if e["outcome"] == k)
         for k in ("persisted", "fetched", "empty", "failed", "missing")}
    c["expected"] = len(entries)
    c["fetched"] += c["persisted"] + c["empty"]
    c["stored"] = (sum(1 for e in entries if e["stored"])
                   if all("stored" in e for e in entries) else None)
    return c


def coverage_caption(manifest: Optional[dict], worksheets: Optional[Iterable[str]] = None,
                     label: Optional[str] = None) -> str:
    """One line such as 'Collection 2026-11-20: 158 of 161 stored · 2 empty · 1 failed'.

    ``worksheets`` limits the counts to those worksheets (e.g. one sector's industries)
    and ``label`` names that subset. A manifest marked ``data_published: false`` never
    claims stored rows. Returns "" for a missing or malformed manifest.
    """
    try:
        return _caption(manifest, worksheets, label)
    except (KeyError, TypeError, ValueError, AttributeError):
        return ""


def _caption(manifest, worksheets, label) -> str:
    if not isinstance(manifest, dict) or "session_date" not in manifest:
        return ""
    published = manifest.get("data_published", True) is not False
    c = manifest.get("coverage")
    if worksheets is not None and c:
        c = _subset_coverage(manifest, worksheets)
        if c is None:
            return ""
    scope = manifest.get("scope", "all")
    title = f"Collection {manifest['session_date']}"
    if label:
        title += f" ({label})"
    elif scope != "all":
        title += f" ({scope} only)"
    if not c:
        if published:
            return ""
        return f"{title}: run did not finish, data not published"
    if not isinstance(c, dict):
        return ""
    if not published:
        head = "run failed, data not published"
    elif c.get("stored") is not None:
        head = f"{int(c['stored'])} of {int(c['expected'])} stored"
    else:
        head = f"{int(c['fetched'])} of {int(c['expected'])} fetched (dry run)"
    parts = [head]
    for key, text in (("empty", "empty (no stocks match the base filters)"),
                      ("failed", "failed"), ("missing", "not attempted")):
        if c.get(key):
            parts.append(f"{int(c[key])} {text}")
    if manifest.get("aborted") and c:
        parts.append(f"run aborted ({manifest['aborted']})")
    return f"{title}: " + " · ".join(parts)


def mark_published(path, session_date: str) -> bool:
    """Drop the ``data_published: false`` marker from the manifest of ``session_date``.

    Called by the workflow's commit step after a successful run, whose data is on main.
    A marker for another session, or no manifest, is left alone. Returns True when the
    file changed.
    """
    manifest = load_manifest(path)
    if (manifest is None or manifest.get("session_date") != session_date
            or "data_published" not in manifest):
        return False
    del manifest["data_published"]
    return write_manifest(manifest, path)


def main(argv=None) -> int:
    """``python -m src.collection_manifest {mark-unpublished|mark-published} --session D [--path P]``."""
    import argparse
    from datetime import date, datetime, timezone

    parser = argparse.ArgumentParser(description="Collection manifest maintenance")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, text in (("mark-unpublished", "Mark a failed run's manifest as not published"),
                       ("mark-published", "Drop a not-published marker after a successful run")):
        cmd = sub.add_parser(name, help=text)
        cmd.add_argument("--path", default=None, help="Manifest path (default: next to DB_PATH)")
        cmd.add_argument("--session", required=True, help="Session date of the run (YYYY-MM-DD)")
    args = parser.parse_args(argv)
    try:
        date.fromisoformat(args.session)
    except ValueError:
        print(f"Invalid session date: {args.session!r}")
        return 1
    path = args.path or default_manifest_path()
    if args.command == "mark-published":
        changed = mark_published(path, args.session)
        print(f"{path}: {'marker removed' if changed else 'no marker for this session'}")
        return 0
    m = mark_unpublished(path, args.session, generated_at=datetime.now(timezone.utc).isoformat())
    print(f"Marked {path} as not published: {coverage_caption(m)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
