# Issue #5: require complete sector coverage for dispersion

Status: FINAL — independent plan review round 2 approved with no remaining findings.
Base: main `2aa04503257035d06a2377fbeccf12a383bf8f37`.

## Selection and boundaries

Issue #5 is P1 and its dependency #4 is merged. No open PRs, issue assignees or prior issue comments, matching remote branch, or matching worktree were present at selection. Existing feature branches correspond to merged PRs. Work is isolated in `/private/tmp/uptrend-issue-5`, branch `fix/issue-5-sector-coverage`; a claim comment records the scope. Recheck overlap before PR creation.

This change covers all-sector dispersion correctness and its direct consumers. It does not change collection/session dates (#3), industry freshness (#6), deployment, tracked DB/CSV contents, or rewrite published historical data. No live requests are necessary.

## Contract and implementation

1. Use the exact configured `SECTORS` set (11 sectors), ignoring `all`, industries, and unrecognized `sec_*` keys. Build the union of observed dates from every recognized sector frame with a `date` column, including frames missing `ma_10`; represent a missing `ma_10` column as all missing values. Explicitly reindex columns to all expected sectors and sort dates. Finite values alone count toward coverage. Missing keys, missing values, and infinities cannot pass coverage.
2. Retain observed dates, including incomplete interiors and tails, with additive columns `sector_count`, `expected_sector_count`, and `coverage_complete`. There are no invented holiday/session rows. Retain leading warmup dates as well: an observed all-missing/no-finite history must still expose its latest date and 0/11 coverage. With no recognized observed dates return an empty frame with the full schema; with sparse recognized sectors return diagnostic rows with no market metrics.
3. Mask incomplete rows **before** calculating dispersion, mean, range, smoothing, percentiles, velocity or regimes. No forward filling. MA10 requires 10 contiguous complete observations. Three-observation velocity requires all four endpoints/intervening observations complete, so a gap cannot create a breakout. Expanding quantiles use complete dispersion/valid velocity observations only; their previously observed valid history is retained across gaps. Mask threshold outputs on incomplete rows. Missing rows reset pending regime confirmation using the existing causal state machine; complete uninterrupted data retains numerical results.
4. `detect_dispersion_signals()` evaluates only the final observed row and returns no signals when coverage metadata is absent/incomplete or labels/metrics are invalid. It must not fall back to an older complete row. Update test fixtures that construct its documented input manually to include coverage metadata.
5. Monitor and Comparison pages show latest observed coverage and last complete as-of date. On incomplete latest coverage, suppress current signal banners/regime action advice/gauge and current regime-based rankings; historical charts/statistics remain accessible with explicit historical labels. No complete observations yields a clear coverage warning and no authoritative output. Respect existing date filtering for chart display only.
6. Append coverage columns to `prepare_dispersion_csv()` while retaining the existing six columns/order. Export the same schema in populated, sparse and empty cases; remove the export path's separate <2-sector bypass so it cannot hide incomplete dates. The `date` column plus row coverage identifies each observation; UI names latest complete date explicitly.
7. Ensure dispersion charts and regime bands/timelines do not color incomplete observations as a continuous valid regime. Keep missing regime rows as segment boundaries rather than dropping them before segmentation.
8. Synchronize `docs/design.md` with coverage contract, schemas, APIs, gap semantics and UI. Add README operating notes explaining withheld current signals and additive CSV fields. Historical calculated outputs can differ when next deliberately regenerated; do not regenerate or commit published data in this PR.

## Test-first verification

- Add failing public-pipeline tests for 2 supplied sectors, a missing configured sector, unknown sector keys, 1/2/10 valid sectors at interior/tail dates, consecutive incomplete tails, all-sector missing tail, missing `ma_10` (including a later date found only in that malformed frame), all-missing/no-finite observed histories, and non-finite values.
- Verify every metric/regime is missing on incomplete dates; current signals never reuse an earlier valid row; complete 11-sector data retains reference std/mean/range/MA/velocity/quantiles.
- Verify gap values cannot affect later percentiles/MA/velocity, pending candidates reset, and appending future rows never changes historical outputs.
- Cover CSV shape/metadata and real temporary-DB export; use synthetic data only.
- Use Streamlit AppTest with patched loaders for both consumer pages: complete latest, partial latest with prior valid history, and no complete observations. Inspect warnings/as-of text and absence of current advice/signals; verify complete-data metrics still render. Test chart boundaries around missing observations.
- Run targeted tests red, implement, run targeted tests green, then full `pytest -q` and `git diff --check`. Preserve existing meaningful tests; explicitly update expectations for the deliberate tail/coverage contract change.

## Review and delivery gates

Independent sub-agent plan review, fix findings and repeat at most three rounds; finalize only when all findings are addressed. Implement only after plan acceptance. After tests pass, independent sub-agent code review, fix findings and repeat at most three rounds. If any findings remain after round 3, report the open gate and do not claim completion. With all findings cleared: recheck remote head/overlap, commit on the dedicated branch, push, open an English PR linking/closes #5, inspect CI and report actual state. Do not merge.

## Plan review log

- Round 1: CHANGES REQUESTED, one Medium finding: dates in frames lacking `ma_10` could disappear, hiding later observations/all-missing history. Resolved by deriving dates independently of values and retaining all observed dates including leading warmup. Added dedicated malformed-later-date and no-finite-history tests.
- Round 2: APPROVE; no remaining plan findings. Implementation may proceed.

## Code review log

- Round 1: CHANGES REQUESTED. Medium: object-dtype `pd.NA`/`None` caused `np.isfinite` to raise. Added object/nullable regressions (2 failures on the pre-fix implementation, nullable case already passed) and normalized numeric values before finite filtering. Low: background-band test used uncolored `normal` regime, making its assertion vacuous. Changed to `converged` and explicitly require two bands/timeline traces and boundaries on opposite sides of the missing date.
- Round 2: APPROVE; reviewer independently ran 35 coverage/page tests and all-sector object/nullable missing-value probes, with no remaining findings.

## Final validation

- Baseline full suite: 375 passed.
- New coverage regressions: 23 failures against the original implementation, then green after the coverage change.
- Real-page navigation regressions: all 8 fail against baseline and pass with the change.
- Object/nullable regression: 2 failures and 1 pass before numeric normalization, all 3 pass after the fix.
- Final full suite: 410 passed on Python 3.14.3; `git diff --check` passed.
- No tracked DB/CSV edits, no live Finviz requests. Remote overlap and main-head checks remain unchanged before delivery.
