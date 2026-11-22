"""Vendored uptrend-analyzer skill must run offline from local CSV files.

The Claude code-execution container has no internet access, so the skill
reads the CSV files the workflow uploads instead of fetching them.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "claude_skills" / "uptrend-analyzer" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from data_fetcher import UptrendDataFetcher  # noqa: E402

TS_HEADER = "worksheet,date,count,total,ratio,ma_10,slope,trend\n"
SECTORS = [
    "sec_basicmaterials", "sec_communicationservices", "sec_consumercyclical",
    "sec_consumerdefensive", "sec_energy", "sec_financial", "sec_healthcare",
    "sec_industrials", "sec_realestate", "sec_technology", "sec_utilities",
]


def _write_timeseries(path: Path, days: int = 40) -> Path:
    lines = [TS_HEADER]
    for i in range(days):
        date = f"2026-{9 + i // 28:02d}-{1 + i % 28:02d}"
        for ws in ["all", *SECTORS]:
            ratio = 0.10 + 0.002 * i
            lines.append(f"{ws},{date},{int(ratio * 1000)},1000,{ratio},{ratio},0.001,up\n")
    path.write_text("".join(lines))
    return path


@pytest.fixture
def timeseries_csv(tmp_path):
    return _write_timeseries(tmp_path / "uptrend_ratio_timeseries.csv")


class TestLocalFetcher:

    def test_reads_local_timeseries_without_network(self, timeseries_csv, monkeypatch):
        fetcher = UptrendDataFetcher(timeseries_path=str(timeseries_csv))
        monkeypatch.setattr(fetcher, "_download", lambda url: pytest.fail("network used"))
        rows = fetcher.fetch_timeseries()
        assert len(rows) == 40 * 12
        assert fetcher.get_latest_all()["worksheet"] == "all"

    def test_missing_sector_summary_path_returns_empty(self, timeseries_csv, tmp_path):
        fetcher = UptrendDataFetcher(
            timeseries_path=str(timeseries_csv),
            sector_summary_path=str(tmp_path / "missing.csv"),
        )
        assert fetcher.fetch_sector_summary() == []

    def test_import_does_not_require_requests(self):
        source = (SCRIPTS / "data_fetcher.py").read_text()
        assert "\nimport requests" not in source


class TestCli:

    def test_cli_writes_json_from_local_csv(self, timeseries_csv, tmp_path):
        out = tmp_path / "reports"
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "uptrend_analyzer.py"),
             "--timeseries-csv", str(timeseries_csv), "--output-dir", str(out)],
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, result.stderr
        reports = list(out.glob("uptrend_analysis_*.json"))
        assert len(reports) == 1
        data = json.loads(reports[0].read_text())
        assert 0 <= data["composite"]["composite_score"] <= 100
