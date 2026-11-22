# Issue #9: dry-run without database mutations

## Selection
P2 #9 has no assignee, claim or PR. P1 #3/#5 are covered by PRs #24/#23; #6 depends on collection/freshness work. This work changes only DB construction for preview and dry-run failure exits, not PR #24 session assertions or PR #25 DB validation. Preserve all existing worktrees.

## Plan
1. New worktree from origin/main; write offline regression tests first using real temporary SQLite files and mocked Finviz HTTP/Excel input.
2. Collection dry-run must not instantiate DBClient or open its target. Pass no DB dependency to DataCollector in dry-run; existing dry_run flag must continue to bypass writes. A guarded no-write stand-in may be used if needed to enforce the boundary without editing DBClient. Normal collection keeps its database behavior.
3. Excel dry-run must never instantiate DBClient. Preserve shared parsing/filtering/counting between preview and real import. Do not broaden validation or change accepted import records. Normal import keeps existing persistence behavior.
4. Define strict dry-run exit statuses: 0 when every attempted worksheet succeeds, 1 for setup/single-worksheet/total failure, 2 for partial bulk failure, including industry failures below live tolerance. Preserve live collection tolerance and statuses. Ensure HTTP resources close on every return/exit.
5. Tests must prove absent nested target paths create no files/directories and existing legacy SQLite bytes/schema/rows/indexes remain unchanged after success and failure. Assert DBClient construction is never called in both previews, exercise single and bulk scopes, verify valid preview counts, and verify normal writes remain functional. Network is mocked; no API credential or live request required.
6. Update docs/design.md and operating documentation with preview boundaries, exit policy, and the fact collection still fetches remote data while Excel still reads its input. Run focused/full tests and a disposable combination with PRs #23–#28, checking session refusal still gates dry-run under #24.
7. Independent plan review and code review, each up to three rounds; resolve all actionable findings. Commit, push, create English PR and verify exact-head CI; do not merge or modify historical DB/CSV.

## Acceptance
Absent and existing targets remain byte/schema/file unchanged in dry-run; failed collection preview returns documented non-success; tests need no live API. Dedicated worktree and independently approved plan/code recorded before PR.


## Review and implementation record
Plan review round 1: independent reviewer approved without actionable findings. Implementation uses a private fail-closed `_DryRunDB` in collect.py and skips DBClient construction for Excel preview. No DataCollector or DBClient source changes. TDD baseline: 50 failed and 6 passed against the original implementation; additional setup/write-boundary regressions brought the focused suite to 61 tests, all passing in existing and newer dependency environments.

Validation: final full suite 436 passed; focused dry-run plus Excel tests 69 passed in the existing dependency environment. The existing Excel dry-run test was updated to assert target absence rather than creating a SQLite connection and expecting initialized schema, which contradicted this issue's acceptance. No production changes were required after the first focused green run.

Code review round 1 approved production changes and 61 focused tests without findings. Full-suite validation identified an obsolete existing Excel test contract; code review round 2 approved the corrected assertion and independently passed 69 Excel/dry-run tests. All actionable items are resolved within two rounds.

Disposable integration with exact current heads of PRs #23–#28: 751 passed, six existing warnings, including session-policy refusal tests. Source changes apply cleanly; design-document adjacent revision-history/appended sections require retaining both sides. No live API, production run, DB/CSV correction or merge was performed.
