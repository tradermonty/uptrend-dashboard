"""The handful of numbers a daily explainer page must get right.

They come from the same CSV the workflow uploads to Claude and from the
uptrend-analyzer report, so the page can be checked against them before it
is published.
"""

import csv
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Facts:
    date: str          # ISO date of the latest market-wide row
    ratio_pct: float   # uptrend ratio in percent, 1 decimal
    count: int         # stocks in uptrend
    total: int         # stocks tracked
    score: float       # uptrend-analyzer composite score, 1 decimal
    zone: str
    exposure: str

    def to_dict(self) -> dict:
        return asdict(self)


def latest_all_row(timeseries_csv: Path) -> dict:
    with open(timeseries_csv, encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["worksheet"] == "all"]
    if not rows:
        raise ValueError(f"no 'all' rows in {timeseries_csv}")
    return max(rows, key=lambda r: r["date"])


def build_facts(timeseries_csv: Path, report: dict) -> Facts:
    row = latest_all_row(timeseries_csv)
    composite = report["composite"]
    return Facts(
        date=row["date"],
        ratio_pct=round(float(row["ratio"]) * 100, 1),
        count=int(row["count"]),
        total=int(row["total"]),
        score=round(float(composite["composite_score"]), 1),
        zone=composite["zone"],
        exposure=composite["exposure_guidance"],
    )
