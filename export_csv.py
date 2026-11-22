"""CLI entrypoint for exporting CSV files from the uptrend database."""

import argparse
import logging
import os
import sys

from src.db_client import DBClient
from src.data_loader import load_all_data
import pandas as pd

from src.data_processor import (
    build_industry_summary,
    build_sector_summary,
    prepare_all_timeseries_csv,
    prepare_dispersion_csv,
)
from src.indicator_calculator import calculate_sector_dispersion

logger = logging.getLogger(__name__)


def export_csv(db_path: str, output_dir: str) -> dict:
    """Export CSV files from the database.

    Returns:
        Dict like:
        {
            "timeseries": {"path": "data/uptrend_ratio_timeseries.csv", "rows": 4720},
            "summary": {"path": "data/sector_summary.csv", "rows": 11},
        }
        Empty dict if no data found.
    """
    all_data = load_all_data(db_path=db_path)

    if not all_data:
        logger.warning("No data found in database")
        return {}

    # Timeseries CSV
    timeseries_df = prepare_all_timeseries_csv(all_data)
    timeseries_path = os.path.join(output_dir, "uptrend_ratio_timeseries.csv")
    timeseries_df.to_csv(timeseries_path, index=False)

    # Sector Summary CSV
    summary_df = build_sector_summary(all_data)
    summary_df = summary_df.drop(columns=["_key"], errors="ignore")
    summary_path = os.path.join(output_dir, "sector_summary.csv")
    summary_df.to_csv(summary_path, index=False)

    # Industry Summary CSV
    ind_summary_df = build_industry_summary(all_data)
    ind_summary_df = ind_summary_df.drop(columns=["_key"], errors="ignore")
    ind_summary_path = os.path.join(output_dir, "industry_summary.csv")
    ind_summary_df.to_csv(ind_summary_path, index=False)

    # Sector Dispersion CSV — always regenerate to prevent stale files
    disp_path = os.path.join(output_dir, "sector_dispersion.csv")
    disp_df = calculate_sector_dispersion(all_data)
    disp_csv = prepare_dispersion_csv(disp_df)
    disp_csv.to_csv(disp_path, index=False)

    return {
        "timeseries": {"path": timeseries_path, "rows": len(timeseries_df)},
        "summary": {"path": summary_path, "rows": len(summary_df)},
        "industry_summary": {"path": ind_summary_path, "rows": len(ind_summary_df)},
        "dispersion": {"path": disp_path, "rows": len(disp_csv)},
    }


def main():
    parser = argparse.ArgumentParser(description="Export CSV files from uptrend database")
    parser.add_argument("--db", default="data/uptrend.db", help="Database path")
    parser.add_argument("--output-dir", default="data/", help="Output directory")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
    )

    if not os.path.isfile(args.db):
        logger.error("Database not found: %s", args.db)
        sys.exit(1)

    if not os.path.isdir(args.output_dir):
        logger.error("Output directory not found: %s", args.output_dir)
        sys.exit(1)

    result = export_csv(args.db, args.output_dir)

    if not result:
        logger.error("No data in database — no CSV files generated")
        sys.exit(1)

    print("\nExport Summary:")
    for key, info in result.items():
        print(f"  {key}: {info['path']} ({info['rows']} rows)")


if __name__ == "__main__":
    main()
