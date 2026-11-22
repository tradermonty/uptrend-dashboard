# Finviz universe migration — Issue #35

## Verified routing and observation

Read-only sampling: `2026-11-17T06:09:30.642858+00:00` to `2026-11-17T06:10:39.335083+00:00` (UTC). New York observation date: `2026-11-17`; latest completed XNYS session: `2026-11-16`. The latter is calendar context, not a provider-certified quote timestamp. Both exports were sampled in this one window; no historical backfill or published-data rewrite was performed.

| Worksheet | Legacy numerator / denominator | New numerator / denominator | Ratio | New universe |
|---|---:|---:|---:|---|
| all | 508 / 2730 | 508 / 2730 | 18.6081% | stocks + etf |
| sec_financial | 105 / 581 | 105 / 581 | 18.0723% | stocks + etf |
| ind_semiconductors | 1 / 47 | 1 / 47 | 2.1277% | stocks |
| ind_exchangetradedfund | 0 / 0 | 0 / 0 | N/A (no write) | etf |
| ind_closedendfunddebt | 0 / 47 | 0 / 47 | 0.0000% | etf |
| ind_closedendfundequity | 0 / 35 | 0 / 35 | 0.0000% | etf |
| ind_closedendfundforeign | 0 / 3 | 0 / 3 | 0.0000% | etf |

All matched numerator and denominator ticker hashes are identical, with zero missing/extra identities. See [the reviewed machine-readable evidence](finviz-migration-evidence.json). Matching counts alone are insufficient: equal-sized replacements still fail comparison.

The stocks-only denominator would have been 2,645 for all and 496 for Financial; 85 closed-end fund identities would disappear. The three fund groups contribute 47 + 35 + 3 = 85. Combining stock and ETF exports retains those identities in the market/Financial aggregates. The ETF industry itself matches at 0/0 under these exact base filters; this is a valid empty observation, not proof that every ETF filter always works. Existing industry 0/0 handling skips persistence so no false zero-ratio point is added.

## Runtime policy

- `all` and `sec_financial`: disjoint union of `type=stocks` and `type=etf`, applied to both numerator and denominator.
- ETF and three closed-end fund worksheets: `type=etf`.
- All other configured worksheets: `type=stocks`.
- Production count requests use `/export/screener`, explicit `c=1` (Ticker), and the original `v=151`, `ft=4`, price/cap/volume/technical filters. Unknown worksheet/filter codes are rejected.
- Separately governed route (v5.9, `src/constituent_collector.py`): after the counts are written, two market-wide `type=stocks` exports feed the industry stock lists only — details with `BASE_FILTERS` and `c=1,2,3,4,6,42,47,66`, and uptrend tickers with `UPTREND_FILTERS` and `c=1`. They never produce or change a count, are not part of `policy_fingerprint()` or the reviewed evidence, and reuse the same filters, session policy, response contract and redaction. Their failure (including a policy refusal) only logs and leaves the previous stock lists in place; header-only details, uptrend ⊄ details, or more than 5% of stocks in unknown industries are rejected without writing.
- A repeated identity across routes is an error, not silent deduplication. Each numerator must be a subset of its denominator. Partial/invalid exports cannot produce a stored pair.
- Startup validates the reviewed evidence schema, complete required sampling, observation window/session, policy fingerprint, route counts, equal hashes/counts, ratios, and absence of differences/errors. A changed filter/routing policy or failed/incomplete comparison requires new reviewed evidence. CLI refusal occurs before opening the target DB. No network sampling is hidden inside collection startup.

## Repeatable read-only comparison

```bash
python compare_finviz_exports.py --output /tmp/finviz-comparison-new.json
```

The API key comes from `FINVIZ_API_KEY` / dotenv. The tool performs only export GETs and writes a new explicit diagnostic JSON. It never opens the database, invokes CSV publication, overwrites an existing report, writes under repository `data/`, or directly replaces the approved evidence. Exit 0 means all required comparisons match; exit 2 means differences, invalid responses, or incomplete sampling; exit 1 means setup/output failure. A worksheet subset is useful for diagnosis but cannot authorize the whole migration.

Required samples are all, Financial, semiconductors, ETF, and the three closed-end fund groups. HTTP errors, HTML, malformed CSV, duplicate tickers, unbounded/missing sample windows, and identity or subset differences leave the report not ready. The existing CSV parser continues to accept genuine header-only exports. Failed samples never become zero counts.

Review the diagnostic (including errors, missing/extra identities, counts/ratios and observation context) before copying matching evidence into `docs/finviz-migration-evidence.json` in a reviewed source change. A JSON file is trusted reviewed evidence, not a signed attestation or a guarantee of future provider semantics. No override flag silently accepts drift.

Repeat the comparison around the December 7, 2026 cutover and after provider/filter changes. This pre-cutover observation cannot verify future behavior. If an old universe cannot be reproduced, withhold publication of the affected new series, record the break and effective session, and review versioned-series/consumer handling before publishing. Never relabel or rewrite prior raw history to make the series appear continuous.

## Regression coverage

`tests/test_finviz_migration.py` covers stock/fund routing, preserved query filters, identity-set changes despite equal counts, incomplete/changed evidence, failed exports, mixed-route overlap, numerator membership, header-only funds, preserved historical rows and DB hashes, pre-DB CLI refusal, secret-free comparison failures and no-overwrite reports. Existing collector retry, secret-redaction, failure-tolerance and dry-run assertions remain covered with explicit empty ETF legs in stock-only fixtures.

## Validation result

- Python 3.11.15, full repository suite: **784 passed** (four existing pandas deprecation warnings).
- Focused collector/migration/session/dry-run suite: **288 passed**.
- New modules and migration tests pass Ruff; `git diff --check` passes.
- Read-only live comparison: all seven required worksheets matched both numerator and denominator identities, counts and ratios in the window above.
- SHA-256 fingerprints of all 11 data files across the original checkout and isolated implementation worktree were unchanged after sampling and the full suite. No production collection or publication was run.

This validates the sampled pre-cutover behavior and offline guards. It does not establish post-December-7 behavior; repeat the documented comparison around the provider cutover.

## Operational cutover tracking

See [the 2026-11-18 cutover ledger and comparison impact](uptrend-cutover-20261118.md). It separates the Dashboard’s verified first new-route session (2026-11-17) from the upstream stocks-only series, whose first production write remains unverified. The 79-fund exclusion belongs to the upstream definition change.
