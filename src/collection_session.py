"""Offline XNYS session policy for current Finviz snapshots (never backfills)."""

import argparse
from datetime import date, datetime, timezone
from functools import lru_cache
import re
import sys
from zoneinfo import ZoneInfo

import exchange_calendars as xcals

NEW_YORK = ZoneInfo("America/New_York")


class SessionPolicyError(ValueError):
    """Fatal policy violation, never subject to worksheet failure tolerance."""


class NonSessionDay(SessionPolicyError):
    """The observed New York date is a holiday or weekend."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_date_label(value: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise SessionPolicyError("Date must be exactly YYYY-MM-DD using ASCII digits") from None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise SessionPolicyError("Date must be a real calendar date") from None


def _aware_now(now=None) -> datetime:
    value = utc_now() if now is None else now
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise SessionPolicyError("A timezone-aware observation clock is required") from None
    return value.astimezone(timezone.utc)


@lru_cache(maxsize=16)
def session_calendar(year: int):
    """Build a bounded local calendar, including that year's special closes."""
    return xcals.get_calendar("XNYS", start=f"{year:04d}-01-01", end=f"{year:04d}-12-31")


def resolve_collection_date(requested=None, *, now=None) -> str:
    """Assert a same-New-York-date, after-actual-close live snapshot session."""
    assertion = parse_date_label(requested) if requested is not None else None
    observed = _aware_now(now)
    day = observed.astimezone(NEW_YORK).date()
    if assertion is not None and assertion != day:
        raise SessionPolicyError("Live snapshots cannot be labeled with a past or future New York date") from None
    try:
        calendar = session_calendar(day.year)
        is_session = calendar.is_session(day.isoformat())
        close = calendar.session_close(day.isoformat()) if is_session else None
    except Exception:
        raise SessionPolicyError("Cannot determine XNYS session; collection refused") from None
    if not is_session:
        raise NonSessionDay(f"No XNYS session on {day.isoformat()}") from None
    if observed < close:
        raise SessionPolicyError(f"XNYS session {day.isoformat()} has not closed") from None
    return day.isoformat()


def resolve_run_session(created_at: str, *, now=None) -> str:
    """Pin a workflow to the New York date in GitHub's run-creation evidence."""
    try:
        if not isinstance(created_at, str):
            raise ValueError
        origin = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if origin.tzinfo is None or origin.utcoffset() is None:
            raise ValueError
    except (ValueError, TypeError):
        raise SessionPolicyError("Missing or invalid workflow creation timestamp") from None
    observed = _aware_now(now)
    if origin > observed:
        raise SessionPolicyError("Workflow creation timestamp is in the future") from None
    return resolve_collection_date(origin.astimezone(NEW_YORK).date().isoformat(), now=observed)


def main():
    parser = argparse.ArgumentParser(description="Validate a workflow's live collection session without network or DB access")
    parser.add_argument("--run-created-at", required=True, help="GitHub workflow run created_at (aware ISO timestamp)")
    args = parser.parse_args()
    try:
        print(resolve_run_session(args.run_created_at))
    except NonSessionDay as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except SessionPolicyError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
