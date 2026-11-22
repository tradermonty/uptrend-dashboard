"""Precompute everything an explainer page shows, so Claude only writes the page.

The brief is plain JSON: the day's facts, the analyzer's score breakdown, the
last 30 trading days, the 11 sectors, long-run history statistics, a weekly
history series for a long chart, and past oversold episodes with what the
ratio was 20 trading days later.
"""

import csv
import statistics
from pathlib import Path

from explainer.facts import Facts

OVERHEATED = 0.37
OVERSOLD = 0.097
RECENT_DAYS = 30
WEEKLY_STEP = 5
AFTER_DAYS = 20
MERGE_GAP = 10  # trading days

SECTOR_NAMES = {
    "sec_basicmaterials": "Basic Materials", "sec_communicationservices": "Communication Services",
    "sec_consumercyclical": "Consumer Cyclical", "sec_consumerdefensive": "Consumer Defensive",
    "sec_energy": "Energy", "sec_financial": "Financial", "sec_healthcare": "Healthcare",
    "sec_industrials": "Industrials", "sec_realestate": "Real Estate",
    "sec_technology": "Technology", "sec_utilities": "Utilities",
}


def _pct(x) -> float:
    return round(float(x) * 100, 1)


def _load(timeseries_csv: Path) -> tuple[list[dict], dict[str, dict]]:
    market, sectors = [], {}
    with open(timeseries_csv, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ws = row["worksheet"]
            if ws == "all":
                market.append(row)
            elif ws in SECTOR_NAMES and (ws not in sectors or row["date"] > sectors[ws]["date"]):
                sectors[ws] = row
    market.sort(key=lambda r: r["date"])
    if market:  # a sector without a row for the latest market date is left out, not shown stale
        sectors = {ws: r for ws, r in sectors.items() if r["date"] == market[-1]["date"]}
    return market, sectors


def _status(ratio: float) -> str:
    if ratio > OVERHEATED:
        return "Overbought"
    if ratio < OVERSOLD:
        return "Oversold"
    return "Normal"


def _episodes(market: list[dict]) -> list[dict]:
    """Runs of days below the oversold line, except the run still open today."""
    runs, start = [], None
    for i, row in enumerate(market):
        below = float(row["ratio"]) < OVERSOLD
        if below and start is None:
            start = i
        elif not below and start is not None:
            runs.append((start, i - 1))
            start = None
    merged: list[tuple[int, int]] = []
    for a, b in runs:  # dips within MERGE_GAP trading days belong to one episode
        if merged and a - merged[-1][1] <= MERGE_GAP:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    if start is not None and merged and start - merged[-1][1] <= MERGE_GAP:
        merged.pop()  # the open episode started earlier: it is today's, not a past one
    episodes = []
    for a, b in merged:
        low = min(range(a, b + 1), key=lambda k: float(market[k]["ratio"]))
        after = low + AFTER_DAYS
        episodes.append({
            "start": market[a]["date"], "end": market[b]["date"], "days": b - a + 1,
            "low_date": market[low]["date"], "low_pct": _pct(market[low]["ratio"]),
            "after_20d_date": market[after]["date"] if after < len(market) else None,
            "after_20d_pct": _pct(market[after]["ratio"]) if after < len(market) else None,
        })
    return episodes


def build_brief(timeseries_csv: Path, report: dict, facts: Facts) -> dict:
    market, sectors = _load(timeseries_csv)
    composite = report["composite"]
    components = report.get("components", {})
    ratios = [float(r["ratio"]) for r in market]
    today = ratios[-1]
    low_i = min(range(len(market)), key=lambda k: ratios[k])

    weekly_idx = list(range(0, len(market), WEEKLY_STEP))
    if weekly_idx[-1] != len(market) - 1:
        weekly_idx.append(len(market) - 1)

    return {
        "facts": facts.to_dict(),
        "score": {
            "composite": facts.score,  # same rounding as the facts block the page is checked against
            "zone": composite["zone"],
            "zone_detail": composite.get("zone_detail"),
            "exposure_guidance": composite["exposure_guidance"],
            "scale": "0-100, higher = healthier breadth",
            "components": [
                {"name": c["label"], "score": c["score"], "weight_pct": round(c["weight"] * 100),
                 "signal": components.get(key, {}).get("signal")}
                for key, c in composite.get("component_scores", {}).items()
            ],
        },
        "thresholds_pct": {"overheated": _pct(OVERHEATED), "oversold": _pct(OVERSOLD)},
        "recent": [
            {"date": r["date"], "ratio_pct": _pct(r["ratio"]), "count": int(r["count"]),
             "ma10_pct": _pct(r["ma_10"]), "trend": r["trend"]}
            for r in market[-RECENT_DAYS:]
        ],
        "sectors": sorted(
            ({"name": SECTOR_NAMES[ws], "ratio_pct": _pct(r["ratio"]), "count": int(r["count"]),
              "total": int(r["total"]), "ma10_pct": _pct(r["ma_10"]), "trend": r["trend"],
              "status": _status(float(r["ratio"]))}
             for ws, r in sectors.items()),
            key=lambda s: -s["ratio_pct"],
        ),
        "history": {
            "first_date": market[0]["date"],
            "days": len(market),
            "min": {"date": market[low_i]["date"], "ratio_pct": _pct(ratios[low_i])},
            "max_pct": _pct(max(ratios)),
            "median_pct": _pct(statistics.median(ratios)),
            "days_lower_than_today": sum(1 for x in ratios[:-1] if x < today),
            "percentile_today": components.get("historical_context", {}).get("percentile"),
            "weekly": [{"date": market[i]["date"], "ratio_pct": _pct(ratios[i])} for i in weekly_idx],
        },
        "past_oversold_episodes": _episodes(market),
    }
