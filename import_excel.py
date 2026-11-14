"""Excel to SQLite import tool for uptrend dashboard."""

import argparse
import logging
from typing import Dict, List, Optional

import pandas as pd

from src.constants import VALID_WORKSHEETS
from src.db_client import DBClient

logger = logging.getLogger(__name__)


def import_excel(
    filepath: str,
    db_path: str = "data/uptrend.db",
    sheets: Optional[List[str]] = None,
    dry_run: bool = False,
) -> Dict[str, int]:
    """Import Excel file into SQLite database.

    Args:
        filepath: Path to the Excel file.
        db_path: Path to the SQLite database.
        sheets: List of sheet names to import. If None, imports all valid sheets.
        dry_run: If True, count rows but don't write to DB.

    Returns:
        Dict mapping sheet name to number of imported rows.
    """
    all_sheets = pd.read_excel(filepath, sheet_name=None, engine="openpyxl")
    client = None if dry_run else DBClient(db_path)
    result = {}

    for sheet_name, df in all_sheets.items():
        if sheet_name not in VALID_WORKSHEETS:
            logger.warning("Skipping unknown sheet: %s", sheet_name)
            continue

        if sheets is not None and sheet_name not in sheets:
            continue

        # Extract required columns
        if "Date" not in df.columns or "Count" not in df.columns or "Total" not in df.columns:
            logger.warning("Sheet %s missing required columns, skipping", sheet_name)
            continue

        df = df[["Date", "Count", "Total"]].copy()

        # Drop rows with empty/null dates or Count/Total
        df = df.dropna(subset=["Date", "Count", "Total"])
        df = df[df["Date"].astype(str).str.strip() != ""]

        # Convert dates to YYYY-MM-DD
        df["Date"] = pd.to_datetime(df["Date"], format="mixed", dayfirst=False, errors="coerce")
        df = df.dropna(subset=["Date"])

        # Ensure Count/Total are numeric
        df["Count"] = pd.to_numeric(df["Count"], errors="coerce")
        df["Total"] = pd.to_numeric(df["Total"], errors="coerce")
        df = df.dropna(subset=["Count", "Total"])

        # Reject non-integer values (e.g., 1.5) instead of silently truncating via astype(int)
        non_integer_mask = (df["Count"] % 1 != 0) | (df["Total"] % 1 != 0)
        if non_integer_mask.any():
            logger.warning(
                "Sheet %s: dropping %d rows with non-integer Count/Total",
                sheet_name,
                int(non_integer_mask.sum()),
            )
            df = df.loc[~non_integer_mask].copy()

        # Reject logically invalid rows
        invalid_logic_mask = (df["Count"] < 0) | (df["Total"] < 0) | (df["Count"] > df["Total"])
        if invalid_logic_mask.any():
            logger.warning(
                "Sheet %s: dropping %d rows with invalid Count/Total relationship",
                sheet_name,
                int(invalid_logic_mask.sum()),
            )
            df = df.loc[~invalid_logic_mask].copy()

        row_count = len(df)
        result[sheet_name] = row_count

        if not dry_run and row_count > 0:
            bulk_df = pd.DataFrame({
                "date": df["Date"].dt.strftime("%Y-%m-%d"),
                "worksheet": sheet_name,
                "count": df["Count"].astype(int),
                "total": df["Total"].astype(int),
            })
            client.upsert_bulk(bulk_df)

        logger.info("Sheet %s: %d rows %s", sheet_name, row_count,
                     "(dry run)" if dry_run else "imported")

    return result


def main():
    parser = argparse.ArgumentParser(description="Import Excel data into SQLite")
    parser.add_argument("filepath", help="Path to Excel file")
    parser.add_argument("--db", default="data/uptrend.db", help="Database path")
    parser.add_argument("--sheet", action="append", dest="sheets", help="Sheet name to import (repeatable)")
    parser.add_argument("--dry-run", action="store_true", help="Count rows without writing")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    result = import_excel(args.filepath, db_path=args.db, sheets=args.sheets, dry_run=args.dry_run)

    print("\nImport Summary:")
    total = 0
    for sheet, count in result.items():
        print(f"  {sheet}: {count} rows")
        total += count
    print(f"  Total: {total} rows")
    if args.dry_run:
        print("  (Dry run - no data written)")


if __name__ == "__main__":
    main()
