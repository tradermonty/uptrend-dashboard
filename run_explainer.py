#!/usr/bin/env python3
"""Write and publish today's ELI5 uptrend explainer pages (Japanese and English).

Usage (GitHub Actions runs this after data collection):
    python run_explainer.py --site site/            # site/ = gh-pages checkout
    python run_explainer.py --site site/ --force    # regenerate a date already published

Python does the analysis (uptrend-analyzer script + explainer.brief); Claude only
writes the pages, following the eli5 skill. Needs ANTHROPIC_API_KEY.
Exit codes: 0 published or nothing to do, 1 failed (site untouched).
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from explainer.brief import build_brief
from explainer.facts import build_facts
from explainer.generate import GenerationError, cost_usd, generate_pages
from explainer.site import publish

ROOT = Path(__file__).resolve().parent
ANALYZER = ROOT / "claude_skills" / "uptrend-analyzer" / "scripts" / "uptrend_analyzer.py"
log = logging.getLogger("explainer")


def run_analyzer(timeseries_csv: Path, sector_csv: Path, out_dir: Path) -> dict:
    """Run the same skill script Claude runs, to get the reference numbers."""
    result = subprocess.run(
        [sys.executable, str(ANALYZER), "--timeseries-csv", str(timeseries_csv),
         "--sector-summary-csv", str(sector_csv), "--output-dir", str(out_dir)],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"uptrend-analyzer failed ({result.returncode}):\n{result.stderr}")
    reports = sorted(Path(out_dir).glob("uptrend_analysis_*.json"))
    if not reports:
        raise RuntimeError("uptrend-analyzer wrote no JSON report")
    return json.loads(reports[-1].read_text())


def already_published(site: Path, date: str) -> bool:
    path = site / "manifest.json"
    if not path.exists():
        return False
    return any(e.get("date") == date for e in json.loads(path.read_text()))


def make_client():
    import anthropic
    # One SDK retry at most: a retried long generation is billed again.
    return anthropic.Anthropic(max_retries=1)


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--site", type=Path, required=True, help="GitHub Pages tree (gh-pages checkout)")
    p.add_argument("--timeseries-csv", type=Path, default=ROOT / "data" / "uptrend_ratio_timeseries.csv")
    p.add_argument("--sector-csv", type=Path, default=ROOT / "data" / "sector_summary.csv")
    p.add_argument("--skill", type=Path, default=ROOT / "claude_skills" / "eli5" / "SKILL.md")
    p.add_argument("--force", action="store_true", help="regenerate even if the date is published")
    return p.parse_args(argv)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args(argv)

    with tempfile.TemporaryDirectory() as tmp:
        report = run_analyzer(args.timeseries_csv, args.sector_csv, Path(tmp))
    facts = build_facts(args.timeseries_csv, report)
    log.info("facts: %s", facts.to_dict())

    if already_published(args.site, facts.date) and not args.force:
        log.info("%s is already published; nothing to do", facts.date)
        return 0

    brief = build_brief(args.timeseries_csv, report, facts)
    client = make_client()
    usage: list = []
    try:
        pages = generate_pages(client, args.skill, brief, facts, usage_log=usage)
    except Exception as e:
        if not (isinstance(e, GenerationError) or _is_api_error(e)):
            raise
        log.error("not published: %s: %s", type(e).__name__, e)
        return 1
    finally:
        _log_usage(usage)

    publish(args.site, facts, pages)
    log.info("published %s", facts.date)
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"published_date={facts.date}\n")
    return 0


def _is_api_error(e: Exception) -> bool:
    try:
        import anthropic
    except ImportError:
        return False
    return isinstance(e, anthropic.APIError)


def _log_usage(responses: list) -> None:
    tin = sum(getattr(r.usage, "input_tokens", 0) or 0 for r in responses)
    tout = sum(getattr(r.usage, "output_tokens", 0) or 0 for r in responses)
    cache = sum(getattr(r.usage, "cache_read_input_tokens", 0) or 0 for r in responses)
    cost = sum(cost_usd(r.usage) for r in responses)
    log.info("usage: %d requests, input %d, cache read %d, output %d tokens, about $%.2f",
             len(responses), tin, cache, tout, cost)


if __name__ == "__main__":
    sys.exit(main())
