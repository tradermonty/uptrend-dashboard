# Issue #7: exact integer binding and positional bulk validation

Status: FINAL — independent plan review approved in round 1 with no findings.
Base: main `2aa04503257035d06a2377fbeccf12a383bf8f37`.
Worktree `/private/tmp/uptrend-issue-7`, branch `fix/issue-7-sqlite-integers`.

## Selection and boundaries

No assignee, claim, matching PR/remote branch/worktree was present for #7. P1 #3/#5 are handled by #24/#23; P1 #6 depends on #3 and overlaps their collection/UI work. This P2 DB integrity issue is independent and unblocks schema-migration issue #8. Record ownership in the issue and recheck overlap before PR delivery.

Change only DB scalar/bulk binding, regression tests and design/operating notes. No schema migration, SQLite global adapters, new dependencies, existing BLOB repair, published data regeneration, live requests, merge or deployment. Verify compatibility with the combined #23/#24 changes in a disposable tree without editing their worktrees.

## Input contract

- `_coerce_whole_number()` accepts Python/NumPy integral scalars except Python/NumPy booleans, and finite integer-valued Python/NumPy floating scalars. Always return a native Python `int` before SQLite binding.
- Check the native integer against SQLite signed 64-bit range before binding; `_validate_counts()` then enforces non-negative values and count <= total. Reject overflow with `ValueError`, never SQLite `OverflowError` after earlier writes.
- Both single/bulk paths reject booleans, NaN/infinities, missing values, fractional floats, strings (including numeric strings), complex/Decimal/Fraction and other unsupported types. This intentionally removes bulk-only numeric-string coercion. Current in-repo producers pass typed numeric columns; do not loosen the scalar API merely to preserve inconsistent coercion.
- Preserve exact integer values, especially >2**53 and `2**63-1`; never normalize all values through float/pandas `to_numeric`. A caller must preserve integer/object dtypes if constructing a mixed-type frame would already round values before the API sees them.

## Implementation

1. Normalize integral scalars with `int(value)`. Check booleans before numeric handling, including `np.bool_`. For floating scalars, require finiteness and no fractional part before conversion, then range-check the resulting native integer.
2. Retain bulk required-column, worksheet and existing date validation. Explicitly reject duplicated required column names before selecting columns; do not conflate duplicated row indexes with ambiguous column names.
3. Replace vectorized numeric conversion and label-based `.loc[idx]` binding with positional iteration of the four required columns (`itertuples(index=False, name=None)`). Apply the same `_validate_counts()` per row and build a fully validated native tuple list before opening the write transaction. Include zero-based row position in bulk diagnostics; never use potentially duplicated index labels to retrieve values.
4. Keep `executemany` inside the existing commit/rollback context manager. An invalid row anywhere in a batch leaves existing rows and earlier valid replacements untouched. SQL errors during execution must also roll back earlier statements. Empty frames with the correct schema remain harmless.
5. Duplicate primary keys retain existing ordered `INSERT OR REPLACE` semantics (last row wins); row-index duplicates are unrelated. Do not mutate caller frames or indexes.
6. Update the DB validation table/API notes and revision history in `docs/design.md` and a concise operating note describing typed values, bounds and no historical BLOB repair. Keep documentation hunks separate from #23/#24 where possible; verify clean three-way combination.

## Test-first validation

- Confirm baseline suite. Add failing single-row NumPy integer `typeof(count/total)='integer'` tests using raw sqlite3, including signed/unsigned NumPy integers and exact 64-bit upper bound.
- Exercise positional bulk rows with duplicate, non-default and MultiIndex labels; assert distinct values map to their correct date/worksheet, no caller mutation, and duplicate PKs still resolve by row order.
- Parameterize both APIs and both count/total fields over Python/NumPy booleans; nulls/NaN/+inf/-inf; fractional floats; numeric strings/unsupported types; negative values/count>total; Python/NumPy overflow, `2**63` and float-rounded upper bounds. Assert `ValueError` and unchanged seeded DB. Keep bulk inputs `dtype=object` where needed so pandas cannot silently pre-coerce the test input.
- Verify whole Python/NumPy floats, zero and valid integer boundaries persist as SQLite INTEGER, and values >2**53 remain exact without float conversion.
- Put an invalid final row after a valid replacement and new row; assert no writes and original values preserved. Use a temporary SQL trigger abort on a later valid row to verify actual transaction rollback (the old negative-count test fails in preflight and does not establish SQL rollback).
- Cover empty and duplicated-column frames plus integer-valued pandas nullable columns/missing entries. Run relevant DB/import/export/integration tests and full pytest, `git diff --check`, then test the combined #23/#24 tree. Use temporary DBs only; no live data edits or network.

## Review and delivery

Independent sub-agent plan review and corrections, at most three rounds, final only after all findings are addressed. Implement test-first, then independent code review and fixes for at most three rounds. If anything remains at round three, report the open gate without claiming completion. Otherwise commit, push, open an English PR closing #7, verify exact head and CI. Do not merge.

## Plan review log

- Round 1: APPROVE; no findings. Numeric-string compatibility change and caller types were independently checked.

## Code review log

- Round 1: CHANGES REQUESTED. Medium: NumPy timedelta64 is registered as Integral, so nanosecond durations could be stored as counts while day/NaT values raised TypeError. Added explicit duration rejection and 15 scalar/bulk/field/final-row regressions, all failing before the correction.
- Round 2: APPROVE; no remaining findings. Reviewer independently ran 162 binding tests and 13 additional duration-unit probes; all rejected unsupported temporal scalars consistently.

## Final validation

- Baseline: 375 passed. Initial new regressions: 43 failed / 104 passed before implementation.
- Duration review regressions: all 15 failed before the correction.
- Final DB/import/export/integration suite: 224 passed. Final full branch suite: 537 passed on Python 3.14.3.
- Combined with PR #23 `7ddbe9c` and PR #24 `61ca119`: 648 passed in an isolated disposable tree; documentation merged cleanly. Six upstream/test deprecation warnings were reported in the newer combined environment. No original worktree was changed.
- `git diff --check` passed. No DB/CSV/schema edits or live API calls. Main and parallel PRs were rechecked before delivery.
