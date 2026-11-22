"""The data brief: everything Claude needs for a page, precomputed in Python."""

from pathlib import Path

import pytest

from explainer.brief import build_brief
from explainer.facts import Facts

SECTORS = ["sec_energy", "sec_technology"]
FACTS = Facts(date="2026-01-20", ratio_pct=5.0, count=50, total=1000,
              score=20.0, zone="Cautious", exposure="Defensive (30-60%)")


def _csv(tmp_path: Path, ratios: list[float]) -> Path:
    """'all' rows on consecutive dates with the given ratios, plus two sectors and an industry."""
    lines = ["worksheet,date,count,total,ratio,ma_10,slope,trend"]
    for i, r in enumerate(ratios):
        date = f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}" if i < len(ratios) - 1 else "2026-01-20"
        lines.append(f"all,{date},{int(r * 1000)},1000,{r},{r},0.001,{'up' if i % 2 else 'down'}")
        for j, ws in enumerate(SECTORS):
            lines.append(f"{ws},{date},{j},100,{j / 100},{j / 100},-0.001,down")
        lines.append(f"ind_gold,{date},1,10,0.1,0.1,0,up")
    path = tmp_path / "ts.csv"
    path.write_text("\n".join(lines) + "\n")
    return path


REPORT = {"composite": {
    "composite_score": 20.0, "zone": "Cautious", "zone_detail": "Cautious-Lower",
    "exposure_guidance": "Defensive (30-60%)",
    "component_scores": {"market_breadth": {"label": "Market Breadth (Overall)", "score": 1,
                                             "weight": 0.3}},
}, "components": {"market_breadth": {"signal": "CRISIS"},
                  "historical_context": {"percentile": 2.7}}}


@pytest.fixture
def brief(tmp_path):
    # 60 days: mid values, a dip to 3% (an earlier episode), recovery, then today at 5%
    ratios = [0.20] * 10 + [0.08, 0.03, 0.06] + [0.25] * 46 + [0.05]
    return build_brief(_csv(tmp_path, ratios), REPORT, FACTS)


class TestBuildBrief:

    def test_facts_and_score(self, brief):
        assert brief["facts"]["ratio_pct"] == 5.0
        assert brief["score"]["zone_detail"] == "Cautious-Lower"
        assert brief["score"]["components"][0] == {
            "name": "Market Breadth (Overall)", "score": 1, "weight_pct": 30, "signal": "CRISIS"}

    def test_composite_matches_rounded_facts(self, brief):
        assert brief["score"]["composite"] == FACTS.score

    def test_stale_sector_rows_are_dropped(self, tmp_path):
        ratios = [0.20] * 30 + [0.05]
        path = _csv(tmp_path, ratios)
        lines = [ln for ln in path.read_text().splitlines()
                 if not (ln.startswith("sec_energy,2026-01-20"))]
        path.write_text("\n".join(lines) + "\n")
        names = [s["name"] for s in build_brief(path, REPORT, FACTS)["sectors"]]
        assert names == ["Technology"]

    def test_thresholds(self, brief):
        assert brief["thresholds_pct"] == {"overheated": 37.0, "oversold": 9.7}

    def test_recent_window_is_last_30_days(self, brief):
        recent = brief["recent"]
        assert len(recent) == 30
        assert recent[-1] == {"date": "2026-01-20", "ratio_pct": 5.0, "count": 50,
                              "ma10_pct": 5.0, "trend": "up"}

    def test_sectors_sorted_and_industries_excluded(self, brief):
        names = [s["name"] for s in brief["sectors"]]
        assert names == ["Technology", "Energy"]
        assert brief["sectors"][1]["ratio_pct"] == 0.0
        assert brief["sectors"][1]["status"] == "Oversold"

    def test_history_stats(self, brief):
        h = brief["history"]
        assert h["days"] == 60
        assert h["min"] == {"date": "2025-01-12", "ratio_pct": 3.0}
        assert h["days_lower_than_today"] == 1
        assert h["median_pct"] == 25.0
        assert h["percentile_today"] == 2.7  # the analyzer's value, not recomputed

    def test_history_series_is_downsampled_but_keeps_ends(self, brief):
        series = brief["history"]["weekly"]
        assert series[0]["date"] == brief["history"]["first_date"]
        assert series[-1]["date"] == "2026-01-20"
        assert len(series) < 60

    def test_past_oversold_episodes_exclude_the_current_one(self, brief):
        episodes = brief["past_oversold_episodes"]
        assert len(episodes) == 1
        ep = episodes[0]
        assert ep["low_date"] == "2025-01-12" and ep["low_pct"] == 3.0
        assert ep["after_20d_pct"] == 25.0

    def test_dips_close_together_are_one_episode(self, tmp_path):
        # two dips 5 days apart, then recovery, then today back below the line
        ratios = [0.20] * 5 + [0.05] + [0.12] * 5 + [0.02] + [0.25] * 40 + [0.05]
        brief = build_brief(_csv(tmp_path, ratios), REPORT, FACTS)
        episodes = brief["past_oversold_episodes"]
        assert len(episodes) == 1
        assert episodes[0]["low_pct"] == 2.0 and episodes[0]["days"] == 7
