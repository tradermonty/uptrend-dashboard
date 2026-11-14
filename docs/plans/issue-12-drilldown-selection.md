# Issue #12: apply drilldown intent before detail selectors

Status: FINAL — independent plan review approved in round 1 without findings.
Base: main `2aa04503257035d06a2377fbeccf12a383bf8f37`.
Worktree `/private/tmp/uptrend-issue-12`, branch `fix/issue-12-drilldown-selection`.

## Selection and scope

Issue #12 is an independent P2 with no assignee, prior claim, corresponding PR/branch/worktree. P1 #3/#5 are handled by #24/#23; #6 depends on them and overlaps their surfaces. #7 is in #25; #8 depends on that DB work. Current work targets `pages/1_Sector_Detail.py` and `pages/3_Industry_Detail.py`, distinct from the active source changes. Recheck overlap before delivery and test a combined #23/#24/#25 tree in isolation.

Keep existing navigation intent keys (`selected_sector`, `selected_industry`) so main/Sector Detail/Heatmap producers remain compatible. Do not change data computation, ranking, freshness/session rules, loaders, DB, imports, published data, or unrelated pages. Do not merge/deploy.

## Selector contract

1. Give each detail selector an explicit, page-specific widget key and store canonical sector/industry keys as values, with `format_func` providing the existing display names. Pending navigation keys and persistent widget keys must be distinct.
2. Industry Detail: inspect pending industry intent before creating either selector. Validate against configured `INDUSTRIES`; for a valid target, set the sector-filter widget state to the target's parent sector (or All Sectors if no parent exists), and the industry widget state to the exact canonical target. Then build the widgets and options. This must override an existing Healthcare filter or previously visited selection.
3. Consume a valid pending target only after both widget values have resolved to the requested target/context. Valid configured targets without data still select the target and display its no-data warning; never silently show another industry's values. Invalid/unknown pending targets are explicitly discarded with an actionable warning and leave a valid prior manual selection intact.
4. Without pending navigation, retain valid manual filter/industry choices. If the user changes the filter and the old industry no longer belongs to the available options, choose the first industry in the existing display-name sort order. Persist All Sectors as a safe explicit option. Recover stale/invalid widget state to a valid fallback before constructing widgets.
5. Sector Detail: apply the same validated, page-specific selector state pattern to pending `selected_sector`, consume only after the target is selected, and retain ordinary manual selection on later reruns.
6. Preserve chart/table producers' existing target payloads. Verify actual Sector Detail chart/table and Heatmap table navigation through registered Streamlit pages. If source selection-event replay is observed, fix the minimal producer state needed to apply each user navigation once; do not expand scope speculatively.
7. The chosen target must drive parent caption, status metrics, chart title/data and download identity consistently. Keep normal display labels and industry ordering. Do not change missing-data behavior beyond making the intended target explicit.

## Test-first verification

- Baseline full suite. Real-page AppTests with synthetic calculated data and different industry/sector ratios; patch only data loading, never destination widgets or selection results. Start AppTest at the real `app.py` multipage entrypoint with patched loaders, then use the public `AppTest.switch_page()` API for visits.
- Reproduce Healthcare filter -> Semiconductors intent and prove Technology plus Semiconductors is selected, the target is consumed only after application, and metrics/chart/download correspond to Semiconductors.
- Repeated intents to the same target and across sectors on an already-visited page; preserve target on a rerun until selectors apply it. Test ordinary manual industry changes, filter changes and All Sectors with no pending intent.
- Sector Detail: manual Healthcare selection followed by pending Technology, then repeated cross-sector selection, with exact metrics and consumption assertions.
- Exercise chart/table/heatmap producer routes with registered `st.switch_page`. For event surfaces AppTest cannot drive, simulate only the source event response while executing the real source and destination pages/navigation. Test repeated visits to catch stale source selection loops.
- Unknown targets, stale persistent widget values, configured targets without data and empty data must not cause exceptions or silently display another target. No-data warnings must name the requested target. Make input fixtures independent from real DB and keys.
- Verify new regressions fail on the baseline, then pass after changes. Run focused page tests, full pytest and `git diff --check`; verify compatibility with #23/#24/#25 in a disposable combined tree without modifying their worktrees.

## Documentation and review gates

Synchronize affected screen/state descriptions and a dated component revision in `docs/design.md`, plus a concise navigation operating note and this plan/review log. Keep hunks separate from active documentation changes and verify clean three-way combination.

Independent plan review and corrections for at most three rounds; finalize only when all findings are resolved. Implement test-first, then independent code review and corrections for at most three rounds. If findings remain after round three, report the open gate. Otherwise commit/push a dedicated branch, open an English PR closing #12, and verify exact head/CI. No merge.

## Plan review log

- Round 1: APPROVE; no findings. Canonical state, pending-intent consumption, manual filters and source/destination test coverage were independently checked.

## Code review log

- Round 1: APPROVE; reviewer independently ran 17 page tests and additional manual-filter/rerun probes; standalone full suite 392 passed.
- Compatibility follow-up: the newer Streamlit environment did not preserve a temporary harness navigation registration across reruns (5 source-route test failures). Replaced the temporary entrypoint/buttons with the real production `app.py` and public AppTest page-switch API. All 17 page tests pass in both local dependency environments; destination/source product code remains unchanged.
- Round 2: APPROVE; reviewer independently ran all 17 tests in both dependency environments and confirmed producer events/destination assertions were not weakened.

## Final validation

- Baseline full suite: 375 passed. Final navigation regressions on baseline product code: 14 failed / 3 passed.
- All 17 navigation tests pass in both local dependency environments. Final standalone suite: 392 passed on Python 3.14.3.
- Combined with #23 `7ddbe9c`, #24 `61ca119` and #25 `46597d0`: 665 passed, six existing upstream/test deprecation warnings, and a clean three-way documentation merge in a disposable tree. Original worktrees were not modified.
- `git diff --check` passed. No live API requests or tracked DB/CSV edits. Main and parallel PRs rechecked before delivery.
