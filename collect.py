"""CLI entrypoint for Finviz data collection (cron-ready)."""

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

from src.constants import SECTORS, VALID_WORKSHEETS
from src.data_collector import (
    CollectorConfig,
    CollectScope,
    DataCollector,
    configure_logging,
    redact,
)
from src.db_client import DBClient
from src.collection_session import SessionPolicyError, resolve_collection_date, utc_now

logger = logging.getLogger(__name__)

# 閾値: industry 収集失敗率がこれ未満なら warning 扱いで exit 0
# (Finviz 側のカテゴリ仕様変動で一部 industry が空データを返すケースを許容)
INDUSTRY_FAIL_TOLERANCE = 0.05  # 5% まで許容


class _DryRunDB:
    """Fail closed if preview collection accidentally attempts persistence."""

    def upsert_raw_data(self, *args, **kwargs):
        raise RuntimeError("Database writes are disabled during dry-run")


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Collect uptrend data from Finviz Elite")
    parser.add_argument("--db", default="data/uptrend.db", help="Database path")
    parser.add_argument("--worksheet", help="Collect specific worksheet only")
    parser.add_argument("--scope", choices=["sectors", "industries", "all"], default=None,
                        help="Collection scope (default: all)")
    parser.add_argument("--date", help="Assert current New York session (YYYY-MM-DD); not a historical override")
    parser.add_argument("--dry-run", action="store_true", help="Fetch data without writing to DB")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    api_key = os.environ.get("FINVIZ_API_KEY")
    configure_logging(args.verbose, secrets=[api_key])

    if not api_key:
        logger.error("FINVIZ_API_KEY environment variable is not set")
        sys.exit(1)

    # Mutual exclusion: --worksheet and --scope
    if args.worksheet and args.scope is not None:
        logger.error("--worksheet and --scope cannot be used together")
        sys.exit(1)

    # Worksheet validation
    if args.worksheet and args.worksheet not in VALID_WORKSHEETS:
        logger.error("Invalid worksheet: '%s'", args.worksheet)
        sys.exit(1)

    # Refuse invalid session assertions before opening a DB or HTTP session.
    try:
        session_date = resolve_collection_date(args.date)
    except SessionPolicyError as exc:
        logger.error("Collection refused: %s", redact(str(exc), [api_key]))
        sys.exit(1)
    logger.info("Collection session: %s (observation UTC: %s)", session_date, utc_now().isoformat())

    scope = CollectScope(args.scope) if args.scope else CollectScope.ALL
    config = CollectorConfig(finviz_api_key=api_key)
    db_client = _DryRunDB() if args.dry_run else DBClient(args.db)
    collector = DataCollector(db_client=db_client, config=config)

    try:
        if args.worksheet:
            try:
                count, total = collector.collect_worksheet(
                    args.worksheet, date=session_date, dry_run=args.dry_run,
                )
                print(f"\n  {args.worksheet}: {count}/{total}")
                if args.dry_run:
                    print("  (Dry run - no data written)")
            except Exception as exc:
                logger.error("Failed to collect %s: %s", args.worksheet, redact(str(exc), [api_key]))
                sys.exit(1)
        else:
            result = collector.collect_all(date=session_date, dry_run=args.dry_run, scope=scope)

            # Summary
            print("\nCollection Summary:")
            for ws, (count, total) in result.succeeded.items():
                ratio = f"{count / total:.1%}" if total > 0 else "N/A"
                print(f"  {ws}: {count}/{total} ({ratio})")
            print(f"  Worksheets collected: {len(result.succeeded)}")
            if result.failed:
                print(f"  Worksheets failed: {len(result.failed)}")
            if args.dry_run:
                print("  (Dry run - no data written)")

            # Industry failure warning
            if result.industry_failed:
                failed_preview = ", ".join(result.industry_failed[:5])
                if len(result.industry_failed) > 5:
                    failed_preview += "..."
                logger.warning(
                    "Industry collection: %d/%d succeeded, %d failed: %s",
                    len(result.industry_succeeded),
                    len(result.industry_succeeded) + len(result.industry_failed),
                    len(result.industry_failed),
                    failed_preview,
                )

            # Preview is a strict validation gate, independent of live tolerance.
            if args.dry_run and result.failed:
                sys.exit(2 if result.succeeded else 1)

            # Live collection retains its existing industry-failure tolerance.
            if not args.dry_run:
                if scope == CollectScope.ALL:
                    # Sector は tier 1 データなので失敗は即 exit 2
                    if len(result.sector_succeeded) == 0:
                        sys.exit(1)
                    elif result.sector_failed:
                        sys.exit(2)
                    elif len(result.industry_failed) > 0 and len(result.industry_succeeded) == 0:
                        logger.error("All industry collections failed")
                        sys.exit(2)
                    elif result.industry_failed:
                        # Industry は閾値判定（Finviz 側の空データは tolerable）
                        industry_total = len(result.industry_succeeded) + len(result.industry_failed)
                        fail_ratio = len(result.industry_failed) / industry_total
                        if fail_ratio >= INDUSTRY_FAIL_TOLERANCE:
                            logger.error(
                                "Industry failure ratio %.2f%% exceeds tolerance %.2f%% (%d/%d failed) -- exit 2",
                                fail_ratio * 100, INDUSTRY_FAIL_TOLERANCE * 100,
                                len(result.industry_failed), industry_total,
                            )
                            sys.exit(2)
                        else:
                            logger.warning(
                                "Industry failure ratio %.2f%% within tolerance %.2f%% (%d/%d failed) -- continuing with exit 0",
                                fail_ratio * 100, INDUSTRY_FAIL_TOLERANCE * 100,
                                len(result.industry_failed), industry_total,
                            )
                            # exit 0 (fallthrough)
                elif scope == CollectScope.SECTORS:
                    expected = len(SECTORS) + 1  # "all" + 11 sectors
                    if len(result.succeeded) == 0:
                        sys.exit(1)
                    elif len(result.succeeded) < expected:
                        sys.exit(2)
                elif scope == CollectScope.INDUSTRIES:
                    if len(result.succeeded) == 0:
                        sys.exit(1)
                    elif result.failed:
                        industry_total = len(result.succeeded) + len(result.failed)
                        fail_ratio = len(result.failed) / industry_total
                        if fail_ratio >= INDUSTRY_FAIL_TOLERANCE:
                            logger.error(
                                "Industry failure ratio %.2f%% exceeds tolerance %.2f%% (%d/%d failed) -- exit 2",
                                fail_ratio * 100, INDUSTRY_FAIL_TOLERANCE * 100,
                                len(result.failed), industry_total,
                            )
                            sys.exit(2)
                        else:
                            logger.warning(
                                "Industry failure ratio %.2f%% within tolerance %.2f%% (%d/%d failed) -- exit 0",
                                fail_ratio * 100, INDUSTRY_FAIL_TOLERANCE * 100,
                                len(result.failed), industry_total,
                            )
                            # exit 0 (fallthrough)
    except SessionPolicyError as exc:
        logger.error("Collection refused: %s", redact(str(exc), [api_key]))
        sys.exit(1)
    finally:
        collector.close()


if __name__ == "__main__":
    main()
