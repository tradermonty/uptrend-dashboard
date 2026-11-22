# Issue #13: comparison date ranges

## Selection and boundaries
P2 #13 is unclaimed and has no existing PR. P1 #3/#5 have PRs; #6 depends on unresolved collection/freshness work. PR #23 changes only the sector comparison dispersion sidebar, whereas this change owns the separate comparison date filter. No collection, database, dispersion, detail navigation, preview or historical data changes.

## Implementation plan
1. Use a dedicated new worktree from origin/main. Add regression tests before implementation (TDD).
2. Add a shared comparison UI helper in a new module. Bounds use the union of dates across all selected nonempty datasets, independent of selection order. Keep the existing configured two-year default window, clamped to union bounds. Do not interpolate, fill or fabricate observations.
3. Integrate both sector and industry comparison date-filter blocks. Explicitly stop with a meaningful message for no available dates, incomplete date input, or a range with no observations. Report each unavailable series and show per-series observed coverage within the selected range, so staggered or disjoint histories are visible. Lack of common overlap does not prevent comparing available observations under the union policy.
4. Use distinct stable widget keys per page, reset to union defaults when the set of selected datasets or bounds changes; retain manual date selection on ordinary reruns. Sort selection identity so reordering has no effect. Avoid stale out-of-bound widget state.
5. Unit-test union, order, empty/missing/NaT dates and disjoint histories. Use real page AppTests with mocked loaders and chart capture to verify both pages (including cross-sector mode), latest observations, missing coverage, empty/partial input, and selection transitions.
6. Update docs/design.md and an operating note with union/missing-data policy and limitations. Run focused and full tests, plus a disposable combination of existing PRs #23–#27 to confirm no conflicting behavior.
7. Independent plan and code reviews, each at most three rounds; resolve findings before commit and English PR. Verify exact-head CI. Do not merge.

## Acceptance
Selection order cannot alter bounds; stale first series cannot hide newer dates; both pages handle empty selection/range/unavailable data; coverage is explicit; no stored data is modified.

## Plan review
Round 1: independent reviewer approved without actionable gaps. Implementation inspection corrected the description of the existing default window from three years to the configured two years; behavior remains delegated to `default_start_date()`.

## Completion evidence
- Code review round 1: independent reviewer approved with no actionable findings; focused tests independently passed (19).
- TDD baseline: 13 regressions failed before implementation; final full suite: 394 passed.
- Final focused suite: 19 passed in both existing and newer Streamlit environments.
- Disposable source combination with PRs #23–#27: 690 passed with six existing warnings; final focused 19 passed. Source changes apply cleanly. Adjacent design revision-history entries require retaining both rows when integrating.
- Historical database and CSV files remain unchanged. Hosted browser manual validation was not performed; real multipage Streamlit AppTests verify interactions.
