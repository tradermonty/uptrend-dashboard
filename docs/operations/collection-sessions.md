# Collection sessions and historical-source recovery

## Live collection

Finviz exports are current snapshots, not a historical API. `collect.py` and the collector use the current **America/New_York** date only when XNYS has a session and its actual close has occurred. The pinned `exchange_calendars==4.13.2` dependency supplies an offline calendar, including holidays, DST offsets and early closes. Python 3.10+ is required by this dependency (CI uses 3.11, deployment specifies 3.12). No broker API or live calendar lookup is used.

`--date YYYY-MM-DD` is an assertion that must match that New York date. It must use exact ASCII ISO format. A past/future date, compact date, ISO week date or nonexistent date is refused before HTTP and, in the CLI, before opening the target DB. Dry runs enforce the same session policy. They still retain the existing separate filesystem/exit-status limitations tracked in Issue #9.

Examples:

- Regular winter session: allowed at/after 21:00 UTC (16:00 New York).
- Regular summer session: allowed at/after 20:00 UTC (16:00 New York).
- 2026-11-27 early close: allowed at/after 18:00 UTC (13:00 New York).
- 00:01 UTC can still belong to the previous New York evening; the UTC date is not the label.
- At New York midnight, collection for the previous date is refused. No fallback to Friday on Saturday, or to the last session on a holiday.

The CLI logs the resolved session and observation time. The collector rechecks before every GET/retry, after responses and transport errors before ordinary failure classification, between the uptrend and total responses, and before persistence. A session violation is fatal even if only the final industry fails and would otherwise be within the 5% tolerance. Earlier successful worksheet writes can remain in a scratch/local DB; transactional snapshot staging is Issue #10. A failing workflow does not export or publish those partial results.

## Scheduled and manual GitHub execution

Both cron and workflow_dispatch use `scripts/session_preflight.sh`. It retrieves this run's original `created_at` from the GitHub API (`actions: read`), pins its New York date, and compares it with the current allowed session. Collection receives that explicit session assertion. A queued job or a rerun crossing New York dates fails instead of assigning today's live data to its original date.

A same-date holiday/weekend is a deliberate skip (policy exit 3, shell success with `eligible=false`); collection, export and commit are all gated off. Before-close execution, stale origin dates, missing/malformed origin evidence, API lookup failures and calendar errors are failures. Manual runs follow the same policy; rerun on the same New York session evening only, after resolving the original failure.

GitHub's cron event payload does not provide an intended firing timestamp. The run-creation timestamp detects delay after GitHub creates a run; it cannot establish whether GitHub created an entire scheduled event a day late. Do not infer unobserved acquisition timestamps from cron text.

## Read-only diagnosis

```bash
python audit_collection_dates.py --db data/uptrend.db > date-audit.json
```

This command opens an existing SQLite file in URI `mode=ro`, reads grouped date labels, and closes the connection. It does not call Finviz, create tables/indexes, migrate or repair data. An invalid BLOB date is represented by `date: null`, `date_hex` and `storage_type: blob`; other invalid non-string labels retain their JSON-safe value and SQLite storage type. Exit 0 means no detected label anomalies; 1 means invalid/non-session/calendar-unknown labels were found; 2 means the DB could not be read. A valid session label alone does not establish source provenance or freshness. Audit a consistent standalone backup/copy when the operational database is being written; do not make a raw file copy of an actively changing WAL database.

Offline evidence on 2026-11-14, copied tracked DB from commit `2aa04503257035d06a2377fbeccf12a383bf8f37`:

- SHA-256 before/after audit: `7cf1ae291241e604664fb486782a665b7b4f7b0b97a4f8240134d4aa23d7d477` (unchanged).
- 842 distinct date labels / 34,318 rows checked; 60 non-session labels covering 1,718 rows.
- Examples include 2026-08-29 (158 rows), 2026-09-07 (158), 2026-11-07 (158), and 2026-11-14 (158). Earlier labels also occur on weekends/holidays.
- These are label anomalies under the chosen session contract. Their cause, original source date semantics and whether any correction is warranted are **not established**. No existing row was changed, deleted, relabeled or re-exported.

## Historical corrections require an original dated source

Do not recover old days with `collect.py --date OLD_DATE`: that fetches a live snapshot and is now refused. The existing explicit historical path is `import_excel.py` with a genuinely dated source workbook. Before using it:

1. Preserve the source workbook unchanged. Record its original source/system, acquisition time, date range/date semantics, source SHA-256, correction reason and exact intended worksheets/dates. Stop if source provenance or dates cannot be established.
2. Take a consistent SQLite backup and record its SHA-256 and revision. Prepare a separate candidate DB from that backup; all preview/import commands below target the candidate, never the published DB.
3. Record exact commands and run the import against the candidate, restricting worksheets as appropriate:

```bash
python import_excel.py approved-source.xlsx --db candidate.db --sheet all --dry-run
python import_excel.py approved-source.xlsx --db candidate.db --sheet all
python audit_collection_dates.py --db candidate.db > candidate-date-audit.json
```

Here `--sheet all` means only the market worksheet named `all`, not every worksheet. Omit `--sheet` to import all valid workbook sheets, or repeat it for specific sheets. The existing import uses UPSERT; it is not an automatic reconciliation or deletion tool.

4. Save a receipt containing the source hash/provenance/date range, original/candidate DB hashes, import command/output, and before/after row/value differences for the intended keys. Review those differences, remaining audit anomalies, rollback and any downstream export effects before separately approved promotion. Do not automatically “fix” all anomalies reported by the audit.

The offline regression exercise creates a synthetic `all` workbook for 2024-01-02, records its SHA-256/date range, imports into a temporary DB, verifies the stored count/total and confirms the source hash is unchanged. This proves the separate source-import path, not the authenticity or correctness of any production correction.
