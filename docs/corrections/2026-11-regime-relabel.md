# Correction plan: one-time regime relabel in `sector_dispersion.csv`

| Item | Value |
|---|---|
| Issue / PR | #4 / #19 |
| Affected file | `data/sector_dispersion.csv`, `regime` column only |
| Rows affected | 56 of 587 |
| Date range | 2024-08-05 to 2026-09-22 |
| Measured against | `main` at `580de32` |

## Why history changes

`_stabilize_regime` rewrote whole runs after measuring their final length, so a label depended on later
observations and a transition was backdated to the start of its run. `_confirm_regime` labels each row using only
data up to that row, and a transition appears on its confirmation date. The published labels from the old
calculation cannot be reproduced without lookahead, so they are replaced rather than kept alongside.

This is a correction of derived data. `data/uptrend.db` is not modified. `date`, `dispersion`, `mean_ratio`, `range`
and `level_regime` are unchanged on every row, and no dates are added or removed.

## What changes for consumers

- **Dashboard:** pages compute regimes when read, so they show the new labels once the merged code is deployed.
- **`data/sector_dispersion.csv`:** this file is committed to a public repository, so anyone can read it through its
  raw URL. The README does not list it, and external consumers are unknown. It changes at the first fully successful
  Collect Finviz Data run after merge. Until then, the CSV and the dashboard can disagree.
- **Forward-return and sector-edge statistics:** these are computed from regime transitions, so their values change.
- **After this correction:** labels are prefix-invariant, so later runs add rows without relabeling earlier ones.

## How it is applied

1. Merge PR #19. No CSV is edited by hand, and the PR does not include a regenerated CSV.
2. The next run of `.github/workflows/collect-data.yml` in which `collect.py` exits 0 runs `export_csv.py` and commits
   the new file. A partial or failed collection stops the job before the export, which delays the relabel. To apply it
   sooner, trigger the workflow manually with `workflow_dispatch`.

## Verification after the first run

1. The commit changes `regime` on exactly the rows listed below, apart from rows newly appended by that run.
2. Every other column on existing rows is unchanged, comparing numeric columns with a tolerance of 1e-9 because
   float output can differ in the last digits between platforms.
3. On later runs, existing rows stay unchanged.

## Rollback

Revert the merge commit of PR #19. The next fully successful run regenerates the CSV with the previous calculation.
If later commits edited the same part of `docs/design.md`, the revert needs that conflict resolved. The earlier file
also stays available in Git history.

## Summary of label changes

| Change | Rows |
|---|---|
| converged to normal | 14 |
| normal to converged | 14 |
| diverged to normal | 14 |
| normal to diverged | 14 |

## All affected rows

| Date | Before | After |
|---|---|---|
| 2024-08-05 | converged | normal |
| 2024-08-06 | converged | normal |
| 2024-09-02 | normal | converged |
| 2024-09-03 | normal | converged |
| 2024-11-18 | diverged | normal |
| 2024-11-19 | diverged | normal |
| 2024-12-02 | normal | diverged |
| 2024-12-03 | normal | diverged |
| 2024-12-31 | converged | normal |
| 2025-01-02 | converged | normal |
| 2025-01-17 | normal | converged |
| 2025-01-21 | normal | converged |
| 2025-02-07 | diverged | normal |
| 2025-02-10 | diverged | normal |
| 2025-02-21 | normal | diverged |
| 2025-02-24 | normal | diverged |
| 2025-03-03 | converged | normal |
| 2025-03-04 | converged | normal |
| 2025-04-22 | normal | converged |
| 2025-04-23 | normal | converged |
| 2025-06-04 | converged | normal |
| 2025-06-05 | converged | normal |
| 2025-06-17 | normal | converged |
| 2025-06-18 | normal | converged |
| 2025-06-25 | converged | normal |
| 2025-06-26 | converged | normal |
| 2025-07-08 | normal | converged |
| 2025-07-09 | normal | converged |
| 2025-08-07 | converged | normal |
| 2025-08-08 | converged | normal |
| 2025-08-13 | normal | converged |
| 2025-08-14 | normal | converged |
| 2025-08-22 | diverged | normal |
| 2025-08-25 | diverged | normal |
| 2025-11-07 | normal | diverged |
| 2025-11-10 | normal | diverged |
| 2025-11-25 | diverged | normal |
| 2025-11-26 | diverged | normal |
| 2026-04-09 | normal | diverged |
| 2026-04-10 | normal | diverged |
| 2026-05-13 | diverged | normal |
| 2026-05-14 | diverged | normal |
| 2026-05-27 | normal | diverged |
| 2026-05-28 | normal | diverged |
| 2026-06-09 | converged | normal |
| 2026-06-10 | converged | normal |
| 2026-06-18 | normal | converged |
| 2026-06-19 | normal | converged |
| 2026-07-29 | diverged | normal |
| 2026-07-30 | diverged | normal |
| 2026-08-04 | normal | diverged |
| 2026-08-05 | normal | diverged |
| 2026-08-14 | diverged | normal |
| 2026-08-17 | diverged | normal |
| 2026-09-21 | normal | diverged |
| 2026-09-22 | normal | diverged |
