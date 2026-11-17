"""Versioned Finviz export routing and read-only continuity evidence (#35)."""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from src.collection_session import session_calendar
from src.constants import VALID_WORKSHEETS

BASE_FILTERS = ["cap_microover", "sh_avgvol_o100", "sh_price_o10"]
UPTREND_FILTERS = BASE_FILTERS + [
    "ta_highlow52w_a30h",
    "ta_perf2_4wup",
    "ta_sma20_pa",
    "ta_sma200_pa",
    "ta_sma50_sa200",
]
FUND_WORKSHEETS = (
    "ind_exchangetradedfund",
    "ind_closedendfunddebt",
    "ind_closedendfundequity",
    "ind_closedendfundforeign",
)
REQUIRED_SAMPLES = ("all", "sec_financial", "ind_semiconductors", *FUND_WORKSHEETS)
DEFAULT_EVIDENCE = (
    Path(__file__).resolve().parents[1] / "docs" / "finviz-migration-evidence.json"
)


class MigrationEvidenceError(ValueError):
    """Unproven continuity; never absorbed by worksheet failure tolerance."""


def universes_for(worksheet):
    if worksheet not in VALID_WORKSHEETS:
        raise MigrationEvidenceError("unknown worksheet/filter")
    if worksheet in ("all", "sec_financial"):
        return ("stocks", "etf")
    return ("etf",) if worksheet in FUND_WORKSHEETS else ("stocks",)


def export_params(api_key, uptrend, worksheet, universe=None):
    universes_for(worksheet)  # reject changed/unsupported worksheet codes
    filters = list(UPTREND_FILTERS if uptrend else BASE_FILTERS)
    if worksheet != "all":
        filters.append(worksheet)
    params = {"v": "151", "f": ",".join(filters), "ft": "4", "auth": api_key}
    if universe is not None:
        if universe not in ("stocks", "etf"):
            raise MigrationEvidenceError("unsupported export universe")
        params.update(type=universe, c="1")
    return params


def build_export_url(base_url, api_key, uptrend, worksheet, universe):
    return (
        base_url.rstrip("/")
        + "/export/screener?"
        + urlencode(export_params(api_key, uptrend, worksheet, universe), safe=",")
    )


def policy_fingerprint():
    policy = {
        "version": 1,
        "endpoint": "/export/screener",
        "columns": "1",
        "base_filters": BASE_FILTERS,
        "uptrend_filters": UPTREND_FILTERS,
        "routes": {ws: universes_for(ws) for ws in VALID_WORKSHEETS},
    }
    return hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()


def ticker_set(values):
    if not isinstance(values, list) or any(
        not isinstance(v, str)
        or not v
        or any(c.isspace() or not c.isprintable() for c in v)
        for v in values
    ):
        raise MigrationEvidenceError("invalid ticker identities")
    normalized = {v.upper() for v in values}
    if len(normalized) != len(values):
        raise MigrationEvidenceError("duplicate ticker identities")
    return normalized


def ticker_hash(values):
    return hashlib.sha256("\n".join(sorted(values)).encode()).hexdigest()


def _time(value):
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError
        return dt.astimezone(UTC)
    except (ValueError, TypeError):
        raise MigrationEvidenceError("invalid observation timestamp") from None


def _window(start, end):
    start, end = _time(start), _time(end)
    if not timedelta(0) <= end - start <= timedelta(minutes=30):
        raise MigrationEvidenceError(
            "comparison must fit one 30-minute observation window"
        )
    local = start.astimezone(ZoneInfo("America/New_York")).date()
    if end.astimezone(ZoneInfo("America/New_York")).date() != local:
        raise MigrationEvidenceError("comparison crossed the New York observation date")
    return start, end, local


def _sample(entry, start, end):
    if (
        not isinstance(entry, dict)
        or entry.get("error")
        or entry.get("http_status") != 200
    ):
        raise MigrationEvidenceError("missing or failed export sample")
    if not start <= _time(entry.get("fetched_at")) <= end:
        raise MigrationEvidenceError("sample outside observation window")
    return ticker_set(entry.get("tickers"))


def latest_closed_session(start):
    for offset in range(15):
        day = start.astimezone(ZoneInfo("America/New_York")).date() - timedelta(
            days=offset
        )
        calendar = session_calendar(day.year)
        if calendar.is_session(day) and calendar.session_close(day) <= start:
            return day.isoformat()
    raise MigrationEvidenceError("no recent completed exchange session")


def comparison_report(samples, started_at, completed_at):
    start, end, local = _window(started_at, completed_at)
    report = {
        "schema_version": 1,
        "policy_fingerprint": policy_fingerprint(),
        "started_at": started_at,
        "completed_at": completed_at,
        "observation_date_ny": local.isoformat(),
        "latest_closed_session": latest_closed_session(start),
        "ready": False,
        "worksheets": {},
        "note": "Point-in-time routing evidence, not a guarantee of future provider semantics.",
    }
    for ws, entries in samples.items():
        routes = universes_for(ws)
        row = {"routes": list(routes), "errors": []}
        identities = {}
        for half in ("uptrend", "total"):
            try:
                legacy = _sample(entries[half]["legacy"], start, end)
                candidate = set()
                route_counts = {}
                for route in routes:
                    values = _sample(entries[half][route], start, end)
                    if candidate & values:
                        raise MigrationEvidenceError("overlapping stock/fund routes")
                    candidate |= values
                    route_counts[route] = len(values)
                row[half] = {
                    "legacy_count": len(legacy),
                    "candidate_count": len(candidate),
                    "legacy_hash": ticker_hash(legacy),
                    "candidate_hash": ticker_hash(candidate),
                    "missing": sorted(legacy - candidate),
                    "extra": sorted(candidate - legacy),
                    "route_counts": route_counts,
                }
                identities[half] = legacy, candidate
                if legacy != candidate:
                    row["errors"].append(half + ": ticker set mismatch")
            except (KeyError, TypeError, MigrationEvidenceError):
                row["errors"].append(half + ": invalid or missing sample")
        if len(identities) == 2:
            for idx, label in enumerate(("legacy", "candidate")):
                numerator, denominator = (
                    identities["uptrend"][idx],
                    identities["total"][idx],
                )
                if not numerator <= denominator:
                    row["errors"].append(label + ": numerator outside denominator")
                if not denominator and (ws == "all" or ws.startswith("sec_")):
                    row["errors"].append(label + ": empty market/sector denominator")
                row[label + "_ratio"] = (
                    len(numerator) / len(denominator) if denominator else None
                )
        report["worksheets"][ws] = row
    report["ready"] = set(REQUIRED_SAMPLES) <= report["worksheets"].keys() and all(
        not row["errors"] for row in report["worksheets"].values()
    )
    return report


def validate_evidence(report):
    """Validate trusted, reviewed evidence; this is not a cryptographic attestation."""
    try:
        if type(report["schema_version"]) is not int or report["schema_version"] != 1:
            raise ValueError
        if (
            report["ready"] is not True
            or report["policy_fingerprint"] != policy_fingerprint()
        ):
            raise ValueError
        start, _, local = _window(report["started_at"], report["completed_at"])
        if report["latest_closed_session"] != latest_closed_session(start):
            raise ValueError
        if report["observation_date_ny"] != local.isoformat():
            raise ValueError
        rows = report["worksheets"]
        if not set(REQUIRED_SAMPLES) <= rows.keys():
            raise ValueError
        for ws, row in rows.items():
            if row["routes"] != list(universes_for(ws)) or row["errors"] != []:
                raise ValueError
            for half in ("uptrend", "total"):
                item = row[half]
                n, m = item["legacy_count"], item["candidate_count"]
                if type(n) is not int or type(m) is not int or n < 0 or n != m:
                    raise ValueError
                if (
                    not re.fullmatch("[0-9a-f]{64}", item["legacy_hash"])
                    or item["legacy_hash"] != item["candidate_hash"]
                ):
                    raise ValueError
                if item["missing"] != [] or item["extra"] != []:
                    raise ValueError
                if (
                    set(item["route_counts"]) != set(universes_for(ws))
                    or any(
                        type(v) is not int or v < 0
                        for v in item["route_counts"].values()
                    )
                    or sum(item["route_counts"].values()) != m
                ):
                    raise ValueError
            n, d = row["uptrend"]["candidate_count"], row["total"]["candidate_count"]
            expected = n / d if d else None
            if n > d or (not d and (ws == "all" or ws.startswith("sec_"))):
                raise ValueError
            if row["candidate_ratio"] != expected or row["legacy_ratio"] != expected:
                raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError):
        raise MigrationEvidenceError(
            "Finviz migration evidence missing, mismatched, or unverified; run compare_finviz_exports.py and review differences before collecting"
        ) from None


def load_evidence(path=DEFAULT_EVIDENCE):
    try:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        raise MigrationEvidenceError(
            "Finviz migration evidence cannot be read"
        ) from None
    validate_evidence(report)
    return report
