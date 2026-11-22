"""Read-only diagnosis of SQLite date labels; never repairs or refetches data."""

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

from src.collection_session import SessionPolicyError, parse_date_label, session_calendar


def audit_collection_dates(db_path: str) -> dict:
    path = Path(db_path).resolve()
    # mode=ro refuses missing files and cannot initialize tables or indexes.
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        dates = connection.execute(
            "SELECT date, typeof(date), COUNT(*) FROM uptrend_raw "
            "GROUP BY date, typeof(date) ORDER BY date"
        ).fetchall()
    anomalies = []
    for label, storage_type, count in dates:
        reason = None
        try:
            day = parse_date_label(label)
        except SessionPolicyError:
            reason = "invalid_date_format"
        else:
            try:
                if not session_calendar(day.year).is_session(label):
                    reason = "non_session_date"
            except Exception:
                reason = "calendar_unknown"
        if reason:
            anomaly = {"date": label, "rows": count, "reason": reason}
            if not isinstance(label, str):
                anomaly["storage_type"] = storage_type
            if isinstance(label, bytes):
                anomaly["date"] = None
                anomaly["date_hex"] = label.hex()
            anomalies.append(anomaly)
    return {"dates_checked": len(dates), "rows_checked": sum(count for _, _, count in dates),
            "anomalies": anomalies}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Existing SQLite DB to inspect read-only")
    args = parser.parse_args()
    try:
        result = audit_collection_dates(args.db)
    except (OSError, sqlite3.Error):
        print("Cannot read the existing SQLite database", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 1 if result["anomalies"] else 0


if __name__ == "__main__":
    sys.exit(main())
