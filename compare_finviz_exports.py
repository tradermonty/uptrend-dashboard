"""Read-only Finviz migration sampling. Never open the DB or publish CSVs."""

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote_plus

import requests
from dotenv import load_dotenv

from src.data_collector import configure_logging, parse_finviz_export
from src.finviz_universe import (
    DEFAULT_EVIDENCE,
    REQUIRED_SAMPLES,
    MigrationEvidenceError,
    comparison_report,
    export_params,
    universes_for,
)


def collect_comparison(
    api_key,
    worksheets=REQUIRED_SAMPLES,
    *,
    session=None,
    request_interval=2.0,
    timeout=30.0,
):
    """Sample matched legacy/new pairs with no publication/storage dependencies."""
    for ws in worksheets:
        universes_for(ws)
    owned = session is None
    session = session or requests.Session()
    started = datetime.now(UTC).isoformat()
    samples = {}
    try:
        for ws in worksheets:
            samples[ws] = {}
            for half in ("uptrend", "total"):
                samples[ws][half] = {}
                for route in ("legacy", *universes_for(ws)):
                    universe = None if route == "legacy" else route
                    params = export_params(api_key, half == "uptrend", ws, universe)
                    endpoint = "export.ashx" if route == "legacy" else "export/screener"
                    entry = {"fetched_at": datetime.now(UTC).isoformat()}
                    try:
                        response = session.get(
                            "https://elite.finviz.com/" + endpoint,
                            params=params,
                            timeout=timeout,
                        )
                        entry["http_status"] = response.status_code
                        response.raise_for_status()
                        frame = parse_finviz_export(response.content)
                        column = next(
                            c for c in frame.columns if c.casefold() == "ticker"
                        )
                        values = frame[column].tolist()
                        if any(
                            api_key in value or api_key in unquote_plus(value)
                            for value in values
                        ):
                            raise ValueError("reflected credential")
                        entry["tickers"] = values
                    except (requests.RequestException, ValueError):
                        entry["error"] = (
                            "export_sample_failed"  # never persist exception/URL/body
                        )
                    samples[ws][half][route] = entry
                    time.sleep(request_interval)
    finally:
        if owned:
            session.close()
    return comparison_report(samples, started, datetime.now(UTC).isoformat())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New diagnostic JSON outside data/; never overwritten",
    )
    parser.add_argument(
        "--worksheet",
        action="append",
        choices=REQUIRED_SAMPLES,
        help="Optional subset; incomplete sampling is never ready for collection",
    )
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent
    output = args.output.resolve()
    if (
        output.suffix != ".json"
        or output.is_relative_to(root / "data")
        or output == DEFAULT_EVIDENCE.resolve()
    ):
        print(
            "ERROR: choose a new diagnostic .json outside publication data/ and the approved evidence path",
            file=sys.stderr,
        )
        return 1
    if output.exists():
        print(
            "ERROR: diagnostic output already exists; choose a new path",
            file=sys.stderr,
        )
        return 1
    load_dotenv()
    key = os.environ.get("FINVIZ_API_KEY")
    configure_logging(False, secrets=[key])
    if not key:
        print("ERROR: FINVIZ_API_KEY is required", file=sys.stderr)
        return 1
    try:
        report = collect_comparison(key, args.worksheet or REQUIRED_SAMPLES)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, allow_nan=False)
    except (OSError, MigrationEvidenceError):
        print(
            "ERROR: comparison/report failed; no collection or publication was attempted",
            file=sys.stderr,
        )
        return 1
    print(f"Comparison report: {output}; ready={report['ready']}")
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    sys.exit(main())
