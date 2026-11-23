"""CLI entrypoint for Finviz data collection (cron-ready)."""

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

from src.collection_session import SessionPolicyError, resolve_collection_date, utc_now
from src.constants import SECTORS, VALID_WORKSHEETS
from src.data_collector import (
    CollectorConfig,
    CollectScope,
    DataCollector,
    CollectResult,
    configure_logging,
    redact,
    scope_worksheets,
)
from src.collection_manifest import build_manifest, write_manifest
from src.constituent_collector import collect_constituents_safely
from src.db_client import DBClient
from src.finviz_universe import MigrationEvidenceError, load_evidence

logger = logging.getLogger(__name__)

# 閾値: industry 収集失敗率がこれ未満なら warning 扱いで exit 0
# (Finviz 側のカテゴリ仕様変動で一部 industry が空データを返すケースを許容)
INDUSTRY_FAIL_TOLERANCE = 0.05  # 5% まで許容


class _DryRunDB:
    """Fail closed if preview collection accidentally attempts persistence."""

    def upsert_raw_data(self, *args, **kwargs):
        raise RuntimeError("Database writes are disabled during dry-run")


def _write_manifest_safely(args, db_client, result, scope, session_date, aborted=None) -> None:
    """Record per-worksheet outcomes and coverage (Issue #6); never changes the exit status."""
    path = args.manifest or os.path.join(os.path.dirname(args.db) or ".", "collection_manifest.json")
    try:
        manifest = build_manifest(
            result=result, expected=scope_worksheets(scope), session_date=session_date,
            scope=scope.value, dry_run=False,
            stored=db_client.worksheets_on(session_date), last_stored=db_client.last_dates(),
            generated_at=utc_now().isoformat(), aborted=aborted,
        )
        write_manifest(manifest, path)
    except Exception as exc:  # The manifest is a report; collection results stand without it.
        logger.error("Failed to write collection manifest %s: %s", path, exc)
        return
    c = manifest["coverage"]
    log = logger.info if c["reconciled"] else logger.error
    log("Coverage %s: expected=%d fetched=%d persisted=%d empty=%d failed=%d missing=%d stored=%d reconciled=%s",
        session_date, c["expected"], c["fetched"], c["persisted"], c["empty"], c["failed"],
        c["missing"], c["stored"], c["reconciled"])


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
    parser.add_argument("--manifest", default=None,
                        help="Collection manifest path (default: collection_manifest.json next to --db)")
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
    try:
        load_evidence(config.migration_evidence_path)
    except MigrationEvidenceError as exc:
        logger.error("Collection refused: %s", exc)
        sys.exit(1)
    db_client = _DryRunDB() if args.dry_run else DBClient(args.db)
    collector = DataCollector(db_client=db_client, config=config)

    partial = None
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
            partial = CollectResult()  # filled in place; survives a fatal abort
            result = collector.collect_all(
                date=session_date, dry_run=args.dry_run, scope=scope, result=partial,
            )

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
            else:
                _write_manifest_safely(args, db_client, result, scope, session_date)

            # Industry stock lists (v5.9): 2 extra requests, never affects exit status
            if not args.dry_run and scope in (CollectScope.ALL, CollectScope.INDUSTRIES):
                collect_constituents_safely(collector, db_client, session_date, secrets=[api_key])

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
    except (SessionPolicyError, MigrationEvidenceError) as exc:
        logger.error("Collection refused: %s", redact(str(exc), [api_key]))
        if partial is not None and not args.dry_run:
            _write_manifest_safely(args, db_client, partial, scope, session_date,
                                   aborted=type(exc).__name__)
        sys.exit(1)
    except Exception as exc:
        # Unexpected crash (e.g. sqlite3.OperationalError): record what was reached, then
        # fail as before. A job timeout or cancellation never gets here; the workflow's
        # failure step covers it (mark-unpublished).
        if partial is not None and not args.dry_run:
            _write_manifest_safely(args, db_client, partial, scope, session_date,
                                   aborted=type(exc).__name__)
        raise
    finally:
        collector.close()


if __name__ == "__main__":
    main()
