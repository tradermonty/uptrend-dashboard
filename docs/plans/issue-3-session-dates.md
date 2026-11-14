# Issue #3: prevent relabeling live snapshots as historical sessions

Status: FINAL — independent plan review approved in round 2; no remaining findings.
Base: main `2aa04503257035d06a2377fbeccf12a383bf8f37`.
Worktree: `/private/tmp/uptrend-issue-3`; branch `fix/issue-3-session-dates`.

## Selection / scope

P1 Issue #3 has no assignee, prior claim or corresponding PR/branch/worktree. Issue #6 depends on it and overlaps PR #23's consumers; #5 already has PR #23. The selected work instead targets collection/CLI/session policy, workflow preflight, read-only diagnosis and documentation. Recheck overlap before push; separately test combination with PR #23 without modifying its worktree. Do not change tracked DB/CSV data or merge/deploy.

## Session policy

- Add `src/collection_session.py` using `zoneinfo` and pinned `exchange_calendars==4.13.2` (XNYS). Its calendar is local/offline; no network calendar lookup is needed. Verify the installed API against the upstream source (https://github.com/gerrymanoim/exchange_calendars).
- A live snapshot may be collected only on the current America/New_York calendar date if it is an XNYS session and its actual close has occurred. At close is permitted. Holidays/weekends, before-close requests and runs delayed past New York midnight are rejected; no fallback to the previous session. UTC midnight while New York is still on the same evening is allowed. This same policy applies to dry runs.
- `--date` is an optional assertion of the derived session, never a historical override. Require exactly ASCII `YYYY-MM-DD` and a real calendar date before any network access, even on direct collector calls. Explicit past/future dates fail. Default dates never use the host timezone. Missing calendar support/out-of-range/invalid clock states fail closed with a concise, credential-free error.
- Use a testable UTC `utc_now()` boundary and a pure `resolve_collection_date(requested=None, now=None)` function accepting an aware datetime for deterministic tests. Avoid tests that depend on the actual current day.

## Collector / CLI / scheduler

1. Validate CLI session before creating DBClient/DataCollector. Invalid requests exit 1 with no HTTP call or target-file creation. Log the resolved session and UTC observation time. All collection modes (bulk/single/dry-run) call the same resolver.
2. Direct `collect_worksheet` and `collect_all` validate dates before the first HTTP request. Bulk validation occurs outside the per-worksheet failure catcher. Use a dedicated `SessionPolicyError` (and non-session subclass), re-raised before ordinary `ValueError` worksheet handling, so no industry tolerance can absorb a policy violation. During long collection, revalidate the pinned session before each worksheet, before every actual HTTP GET/retry (including between uptrend and total), and again after HTTP reads before writing/returning, so crossing New York midnight cannot persist a snapshot labeled with yesterday's session. Existing earlier writes are not rolled back (snapshot staging belongs to #10); failures prevent publication.
3. Catch session-policy errors at the CLI boundary and exit nonzero without a traceback. Do not weaken content validation, retry behavior, per-worksheet failure tolerance, or secret redaction.
4. Keep the scheduled DST selector, but add an explicit calendar preflight to the collect job: legitimate holiday/weekend invocations skip collection/export/commit with an explanation; malformed explicit dates/clock/calendar errors are failures. Manual workflow runs obey the same session policy. Early closes are allowed by actual close-time validation even though cron remains at the normal close schedule. Read the workflow run `created_at` through the GitHub API with `actions: read`; derive its New York origin date, assert it in preflight, and pass the resolved date to `collect.py --date`. A queued run or rerun crossing New York dates is rejected. Missing, malformed or unavailable origin evidence fails closed, never defaults to now. Gate collection/export/commit on eligible preflight. The cron payload has no intended timestamp: delays before GitHub creates the workflow run cannot be inferred, and this evidence limitation must be documented. Preserve failure-based publication gates.

## Read-only diagnosis / historical correction

- Add `audit_collection_dates.py --db PATH`, using SQLite URI `mode=ro`, to inspect distinct stored date labels against XNYS. Report JSON with date, row count and reason for invalid-format/non-session/calendar-unknown dates; exit nonzero if anomalies/unknowns exist. It must not initialize or migrate a DB, invoke Finviz, or alter DB bytes/schema. Missing path is an error and must not create a DB.
- Run it against an isolated copy of the current tracked DB, compare its hash before/after and record the date-label findings. A non-session label is an anomaly, not proof of a particular cause or permission to delete/relabel rows.
- Document the existing `import_excel.py SOURCE.xlsx --db SCRATCH.db` path for genuine historical source data. Require a source/date-range explanation and SHA-256 receipt, original DB backup/hash, explicit copy target, before/after counts and review before promotion. Exercise that procedure offline using a synthetic Excel file and temporary DB; do not modify the importer or pretend a live `--date` call is historical recovery.

## Test-first validation

- Pure policy tests: exact format (including compact dates, ISO week dates, unicode digits, whitespace), invalid calendar dates, historical/future assertions; timezone-aware clock requirement; regular close boundaries, early close, observed holiday, weekend, DST before/after, UTC midnight and New York midnight/late start; calendar errors/out-of-range.
- Public collector/CLI tests: forbidden date makes zero HTTP requests and preserves seeded historical rows; CLI refusal creates no nonexistent DB; default and asserted session match; direct bulk and single plus dry-run enforce the same policy; cross-midnight after fetch causes no write; crossings during retry, between responses and on the final industry abort without later GET/write and produce nonzero CLI outcomes even under failure tolerance; crossing between worksheets cannot silently publish under a new session.
- Existing collector tests currently use Saturday `2026-02-07`. Convert those synthetic fixtures to a valid session and freeze the clock at after-close for the test module, without bypassing the resolver. Separate boundary tests use their own clock fixtures.
- Workflow tests check actual preflight skip/fail classification and that skipped/failed policy checks cannot run export/commit. Test created_at timezone conversion, delayed execution, stale reruns and malformed/unavailable origin evidence. Keep shell quoting/data handling safe and use no live secrets/API.
- Audit tests cover non-session and malformed dates, unchanged DB hash/schema, absent target, calendar unknowns; exercise source-hash historical import on temporary artifacts.
- Run regression tests red, implement then green, full pytest and `git diff --check`. Test combination with PR #23 in an isolated temporary tree. Record local/CI evidence separately.

## Review / delivery

Independent sub-agent plan review, address findings, repeat at most three rounds and finalize only when all are resolved. Then implement test-first. Independently review code and fix findings for at most three rounds. If anything remains unresolved at the limit, report the open gate. Otherwise commit/push dedicated branch, open an English PR closing #3, confirm exact head/CI, and report. No merge.

## Plan review log

- Round 1: CHANGES REQUESTED. High: session violations could be swallowed by ValueError worksheet tolerance; made policy errors fatal and added per-GET/retry/inter-response revalidation plus final-industry regression. Medium: scheduler origin was undefined; added created_at evidence, actions:read, origin-date assertion, skip/fail gating and evidence-limit documentation/tests.
- Round 2: APPROVE; all plan findings resolved.

## Code review log

- Round 1: CHANGES REQUESTED. Medium: midnight error responses could enter industry tolerance; added response/error-path guards with suppressed exception context and four last-industry regressions. Medium: new calendar requires Python 3.10+, so corrected the supported minimum. Low: invalid BLOB date labels broke audit JSON; added storage-type/hex representation and a CLI/no-mutation regression. All five new failure cases were reproduced before fixes.
- Round 2: APPROVE; all findings resolved. Reviewer independently ran 76 session/operations tests and additional malformed/timeout/direct-HTTP midnight traceback probes.

## Final validation

- Baseline full suite: 375 passed.
- Final branch suite: 451 passed on Python 3.14.3 (four upstream calendar/pandas deprecation warnings).
- Review-fix regressions: five failures before correction, all pass after correction; targeted collector/session/operations suite: 204 passed.
- Combined with PR #23 at `7ddbe9c486be37852bfd3cdd07baaa6449725472`: clean three-way README/design merges and 486 tests passed in a disposable archive; its original worktree was untouched.
- Copied tracked DB audit: 842 dates / 34,318 rows; 60 non-session labels covering 1,718 rows. Copy SHA-256 unchanged before/after. Cause unestablished; no correction or published-data regeneration performed.
- `git diff --check` passed; no live Finviz requests. Remote main and parallel PR inventory rechecked before delivery.
