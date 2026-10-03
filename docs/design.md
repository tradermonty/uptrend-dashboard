# US Market Uptrend Stock Ratio Dashboard Design Document

| Item | Details |
|------|---------|
| Document Type | Software Design Document |
| Project Name | uptrend-dashboard |
| Created | 2026-02-08 |
| Revised | 2026-10-03 |
| Status | v5.1 Sector Dispersion Analysis |

---

## Revision History

| Date | Version | Changes |
|------|---------|---------|
| 2026-02-08 | v1 | Initial version (Google Sheets based) |
| 2026-02-08 | v2 | Migrated data store from Google Sheets to SQLite. Ported derived data calculations to Python. Added Excel import functionality |
| 2026-02-08 | v2.1 | Removed signal logic (Long/Short Entry/Exit). Changed chart trend display to green/red/gray color coding |
| 2026-02-08 | v2.2 | Code review fixes. Improved DB connection management, centralized constants, empty data handling, added logging, test improvements |
| 2026-02-08 | v2.3 | Sector Comparison chart improvements. 10MA display, threshold lines, custom palette, latest value annotations, Y-axis % format, legend sorting |
| 2026-10-03 | v5.1 | Sector Dispersion regime stabilization made causal: `_stabilize_regime` replaced by `_confirm_regime` sequential state machine (no lookahead, prefix-invariant labels, transition emitted only on confirmation date) |
| 2026-04-11 | v5.0 | Sector Dispersion Analysis: cross-sectional dispersion indicator, regime classification, signal detection, forward return stats, new Dispersion Monitor page, CSV export |
| 2026-04-11 | v4.4 | Code quality fixes: extracted `data_loader.py` (DIP fix), unified threshold constants, date validation, exit code gaps, CI concurrency guard |
| 2026-02-18 | v4.3 | Default display period limit: date_input defaults to max 2 years via `default_start_date()`, `python-dateutil` dependency |
| 2026-02-16 | v4.2 | Industry Heatmap: Treemap page for all 149 industries, grouped by sector with RdYlGn colorscale |
| 2026-02-16 | v4.1 | Sector Detail: added Industry Summary CSV download button (2-column layout) |
| 2026-02-16 | v4.0 | Industry-level uptrend analysis: 149 industries, Industry Detail/Comparison pages, data collection scope, CSV export |
| 2026-02-14 | v3.5 | Automated CSV export via GitHub Actions for LLM data access via raw URL |
| 2026-02-14 | v3.4 | CSV download buttons on main page for LLM data analysis |
| 2026-02-11 | v3.3 | Sector summary bar chart click → Sector Detail page navigation |
| 2026-02-11 | v3.2 | Data validation hardening, secret masking, CI test workflow. DB CHECK constraints, Python-level count/total validation, import_excel row filtering, mask_secrets/safe_http_error, GitHub Actions pytest |

### v5.1 Key Changes (Causal Regime Confirmation)

- **Causal regime stabilization**: `_stabilize_regime()` (whole-run re-labelling with lookahead) replaced by `_confirm_regime()` — a left-to-right sequential confirmation state machine. A regime change is confirmed only on the `min_days`-th consecutive valid day; before that, rows keep the previous confirmed regime (absorbing short blips as noise reduction).
- **No lookahead / prefix-invariant labels**: each row's regime depends only on observations up to that row, so appending future history never relabels an earlier row. This is the core defect fix for Issue #4.
- **Missing observations**: a NaN day resets the in-progress candidate run (a missing day provides no evidence), is emitted as NaN, and does not extend a run; it delays confirmation by requiring `min_days` consecutive valid days. (Old behavior counted a NaN-interrupted run as contiguous because it operated on `dropna()`; this is an intentional, conservative change.)
- **Initial regime**: the first non-NaN classification establishes the baseline immediately; it is never relabeled.
- **Forward-return events**: composite `(regime, level_regime)` transition events now occur at the confirmation date rather than the run start, removing backdating in `calculate_forward_returns()` / `calculate_sector_edge()`.
- **New tests**: `TestConfirmRegime`, `TestDispersionRegimePrefixInvariance`, `TestForwardReturnsConfirmationDate`.

### v5.0 Key Changes (Sector Dispersion Analysis)

- **Cross-sectional dispersion indicator**: `calculate_sector_dispersion()` computes std dev across 11 sectors' 10MA values per day, with expanding-window adaptive thresholds (p25/p75/p90/median)
- **Regime classification**: `converged` (σ < expanding p25), `normal`, `diverged` (σ > expanding p75), with `level_regime` based on mean ratio (`low`/`mid`/`high`)
- **Signal detection**: `detect_dispersion_signals()` with 3 signals: CAPITULATION (converged+low), DIVERGENCE_WARNING (diverged), BREAKOUT_VELOCITY (velocity > p90 & dispersion < median)
- **Forward returns**: `calculate_forward_returns()` using composite state transition events (not daily samples) to avoid overlapping-sample bias
- **Sector edge**: `calculate_sector_edge()` computes per-sector performance after regime transitions, keyed by (regime, level_regime) for CAPITULATION-specific ranking
- **New page**: `pages/6_Dispersion_Monitor.py` — Signal banner, dual-axis dispersion chart, regime timeline, regime-aware sector ranking, historical stats
- **Sector Comparison integration**: Sidebar dispersion gauge with regime badge and link to Dispersion Monitor
- **New data processor functions**: `build_sector_ranking_table()` (regime-aware sort), `prepare_dispersion_csv()`
- **New chart functions**: `build_dispersion_chart()` (dual-axis with time-series p25/p75 traces), `build_regime_timeline_chart()` (horizontal bar regime visualization)
- **CSV export**: `data/sector_dispersion.csv` always regenerated (stale-file prevention); empty CSV with headers if insufficient sectors
- **New constants**: `DISPERSION_CONVERGED_FALLBACK`, `DISPERSION_DIVERGED_FALLBACK`, `MEAN_RATIO_LOW/HIGH`, `DISPERSION_VELOCITY_WINDOW`, `DISPERSION_MIN_HISTORY`, `CHART_HEIGHT_DISPERSION/REGIME_TIMELINE`
- **Data guard**: All pages handle insufficient dispersion data gracefully (st.warning + st.stop or N/A display)

### v4.0 Key Changes (Industry-Level Analysis)

- **149 industries added**: `ind_advertisingagencies` through `ind_wastemanagement`, each mapped to one of 11 sectors via `SECTOR_INDUSTRIES` / `INDUSTRY_TO_SECTOR`
- **VALID_WORKSHEETS**: 12 → 161 (1 `all` + 11 sectors + 149 industries)
- **New constants**: `INDUSTRIES`, `INDUSTRY_DISPLAY_NAMES`, `SECTOR_INDUSTRIES`, `INDUSTRY_TO_SECTOR`, `MAX_INDUSTRY_COMPARISON`, `is_sector()`, `is_industry()`
- **Data collection scope**: `CollectScope` enum (`SECTORS`/`INDUSTRIES`/`ALL`), `CollectResult` dataclass with sector/industry split properties. `collect.py --scope all|sectors|industries`. Exit code: sector failures determine exit code, industry failures are warnings only
- **New pages**: `3_Industry_Detail.py` (2-stage selector, parent sector display, status metrics), `4_Industry_Comparison.py` (Within Sector / Cross-Sector modes)
- **Sector Detail drilldown**: Industry summary chart + table with click-to-navigate to Industry Detail
- **Chart functions**: `build_industry_summary_chart()`, `build_industry_comparison_chart()`, shared `_build_comparison_chart()` extracted from sector comparison
- **Data processor**: `get_industry_display_name()`, `build_industry_summary()`, `get_sector_for_industry()`, `style_status_row()` shared across pages
- **Data loader**: `load_sector_data()`, `load_industry_data()`, `cached_load_sector_data()` / `cached_load_all_data()` cross-page cache (moved to `data_loader.py` in v4.4). DB client: `fetch_all_raw_data(worksheets=)` filter
- **CSV export**: Added `industry_summary.csv` as 3rd export file
- **Tests**: 132 → 187 tests (→ 204 after v4.2, → 210 after v4.3)

### v3.5 Key Changes (Automated CSV Export)

- **Automated CSV export**: `export_csv.py` CLI generates 2 CSV files after data collection, committed to git for raw URL access
  - **Timeseries**: `data/uptrend_ratio_timeseries.csv` — all 12 worksheets combined with `worksheet` column, sorted by `sorted(keys())` (`all` first, then `sec_*` alphabetical)
  - **Sector Summary**: `data/sector_summary.csv` — `build_sector_summary()` output minus internal `_key` column
- **New function in `data_processor.py`**: `prepare_all_timeseries_csv(all_data: Dict[str, DataFrame]) -> DataFrame` — combines all worksheets via `prepare_timeseries_csv()`, adds `worksheet` column, formats dates as `YYYY-MM-DD` strings
- **New CLI**: `export_csv.py` — `--db`, `--output-dir`, `--verbose` options. Exit code 1 on DB not found, output dir not found, or empty DB
- **GitHub Actions**: Added "Export CSV files" step after data collection; `git add` includes `data/*.csv`
- **CSV format**: UTF-8, header row, no index, raw decimals (0.29 not 29%), NaN as empty string, dates as `YYYY-MM-DD`
- **Error handling**: `export_csv.py` failure stops workflow before commit step, preventing DB/CSV inconsistency
- **Tests**: 117 → 132 tests (+7 `prepare_all_timeseries_csv`, +8 `export_csv`)

### v3.4 Key Changes (CSV Download)

- **CSV download buttons**: Added 2 download buttons at the bottom of the main page for LLM-friendly data export
  - **Ratio Time Series**: `date, count, total, ratio, ma_10, slope, trend` — date-filtered `calculate_indicators()` output with string trend column ("up"/"down"), excluding chart-only columns
  - **Sector Summary**: `Sector, Ratio, 10MA, Trend, Slope, Status` — `build_sector_summary()` output minus internal `_key` column
- **New function in `data_processor.py`**: `prepare_timeseries_csv()`
- **Values exported as raw decimals** (e.g., 0.29 not 29%) for machine readability
- **Tests**: 114 → 117 tests (added 3 CSV export tests)

### v3.3 Key Changes (Sector Summary Click Navigation)

- **Click-to-navigate**: Clicking a bar in the Sector Summary horizontal bar chart **or a row in the summary table** navigates to the Sector Detail page with that sector pre-selected
- **`_key` column**: Added internal worksheet key column to `build_sector_summary()` output for chart `customdata` mapping (hidden from `st.dataframe` display)
- **`customdata` on bar trace**: `build_sector_summary_chart()` passes `_key` values as `customdata` on the `go.Bar` trace
- **`on_select` event**: `app.py` uses `st.plotly_chart(on_select="rerun")` and `st.dataframe(on_select="rerun", selection_mode="single-row")` to capture click events, sets `st.session_state["selected_sector"]`, and calls `st.switch_page()`
- **Sector Detail pre-selection**: `pages/1_Sector_Detail.py` reads `st.session_state.pop("selected_sector")` to set `st.selectbox` default index
- **Streamlit version**: Bumped minimum to `>=1.35.0` for `on_select` parameter support
- **Tests**: 114 tests (added `test_sector_summary_chart_customdata`)

### v3.2 Key Changes (Data Validation, Secret Masking, CI)

- **DB CHECK constraints**: Added `CHECK (count >= 0)`, `CHECK (total >= 0)`, `CHECK (count <= total)` to `uptrend_raw` table definition
- **Python-level validation**: Added `_coerce_whole_number()` (type coercion with bool rejection), `_validate_counts()` (non-negative, count <= total) to `DBClient`
- **Bulk validation**: `upsert_bulk()` now validates missing columns, non-numeric, non-integer, negative, and count > total before DB write
- **Import filtering**: `import_excel.py` drops non-integer and logically invalid (negative, count > total) rows with warnings instead of silently truncating
- **Secret masking**: Added `mask_secrets()` function to sanitize `auth=` query params from logs/exceptions. Added `_safe_http_error()` to create sanitized HTTPError without URL leakage
- **10MA display fix**: Changed `if status["ratio_10ma"]` to `if status["ratio_10ma"] is not None` to correctly display 0.0% instead of "N/A"
- **External link security**: Added `rel="noopener noreferrer"` to Finviz link
- **CI**: Added `.github/workflows/test.yml` for automated pytest on push/PR
- **Tests**: 105 → 113 tests (secret masking edge cases, bool rejection, float coercion, bulk validation)

### v2.3 Key Changes (Sector Comparison Chart Improvements)

- **MA line as primary display**: Added `use_ma` parameter to `build_sector_comparison_chart()`. Defaults to displaying `ma_10` (10-day moving average), significantly reducing noise
- **Threshold lines**: Upper (37%) / Lower (9.7%) displayed as dashed lines, adding context to the chart
- **11-color custom palette**: Defined `SECTOR_PALETTE`, solving Plotly's default similar-color problem
- **Latest value annotations**: Labels showing sector name and current value (%) at the right end of each line
- **Y-axis percentage format**: `tickformat=".0%"` converts 0.37 to 37%
- **Legend sorting**: Legend automatically sorted by latest value in descending order for at-a-glance ranking
- **Display toggle**: Added "Smoothed (10MA)" / "Raw Ratio" radio buttons to the Sector Comparison page

### v2.2 Key Changes (Code Review Fixes)

- **DB connection management**: Introduced `_connection()` context manager. All methods use `with` pattern. Changed `upsert_bulk()` to `executemany()` + single transaction. Guaranteed rollback on exception
- **Centralized constants**: Created `src/constants.py`. Consolidated `SECTORS`, `VALID_WORKSHEETS`, `SECTOR_DISPLAY_NAMES`. Eliminated 4 duplicate definitions
- **Logging**: Set `logging.getLogger(__name__)` in all source modules
- **Empty data handling**: Added empty DataFrame guards to `get_current_status()`, `build_sector_summary()`, `calculate_indicators()`
- **Worksheet validation**: Added `VALID_WORKSHEETS` check in `upsert_raw_data()`, `upsert_bulk()`
- **NaN handling**: `_calc_ratio()` handles NaN in count/total with `fillna(0)`
- **MarketStatus dataclass**: Changed `get_current_status()` return value from dict to `MarketStatus` dataclass (maintaining dict compatibility)
- **Date filter helper**: Extracted `filter_by_date_range()` shared by `app.py` / `pages/*.py`
- **Chart function decomposition**: Split `build_ratio_chart()` into 5 smaller functions
- **Magic number constants**: Consolidated chart heights, thresholds, etc. into `src/constants.py`
- **Public API cleanup**: Renamed `_sector_display_name` to `get_sector_display_name`
- **Test improvements**: Eliminated private function dependencies, added integration tests (Excel → DB → calculation → chart)

### v2 Key Changes

- **Data store**: Google Sheets → SQLite (`data/uptrend.db`)
- **Data access layer**: `sheets_client.py` → `db_client.py`
- **Derived data calculation**: Google Sheets formulas → `indicator_calculator.py` (Python/pandas calculation)
- **Data migration**: Added bulk import tool `import_excel.py` for importing from Excel files
- **Dependencies**: Removed `gspread`, `oauth2client`. Added `openpyxl`
- **stocktrading changes**: Change write destination from Google Sheets to SQLite (future work)

---

## 1. Overview

### 1.1 Purpose

Provide an interactive web dashboard for visualizing Uptrend Stock Ratio data in the US market.

Data is read from raw data (Count, Total) stored in SQLite, derived indicators (Ratio, 10MA, Slope, Trend) are calculated in Python, and trend states are visualized with green (up) / red (down) / gray (insufficient data) color coding.

### 1.2 Scope

- Read raw data (Count, Total) from SQLite
- Python calculation of derived indicators (Ratio, 10MA, Slope, Trend)
- Time series visualization of Ratio for the full market (all), 11 sectors, and 149 industries
- Green/red/gray color-coded trend state display
- Cross-sector and cross-industry comparison charts
- Sector → Industry drilldown navigation
- Historical data import from Excel files

### 1.3 Out of Scope

- Direct access to Finviz / Alpaca APIs
- Trade execution / position management
- User authentication / access control
- Changes to stocktrading write logic (listed as future work only)

---

## 2. System Architecture

### 2.1 Overall Structure

```
┌───────────────────────────────────────────────────────────────┐
│                      Streamlit App                             │
│                                                               │
│  ┌──────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐│
│  │ app.py   │ │1_Sector_    │ │2_Sector_    │ │3_Industry_  │ │4_Industry_  │ │5_Industry_  ││
│  │ (Main)   │ │ Detail.py   │ │ Comparison  │ │ Detail.py   │ │ Comparison  │ │ Heatmap.py  ││
│  └────┬─────┘ └──────┬──────┘ └──────┬──────┘ └──────┬──────┘ └──────┬──────┘ └──────┬──────┘│
│       │              │               │               │               │       │
│       └──────────────┼───────────────┼───────────────┼───────────────┘       │
│                        │                                      │
│              ┌─────────▼────────────┐                         │
│              │  chart_builder.py    │  ← Plotly Figure gen    │
│              └─────────┬────────────┘                         │
│                        │                                      │
│              ┌─────────▼────────────┐                         │
│              │  data_processor.py   │  ← Status aggregation   │
│              └─────────┬────────────┘                         │
│                        │                                      │
│              ┌─────────▼────────────┐                         │
│              │indicator_calculator  │  ← Derived indicator    │
│              │         .py         │     (Ratio, 10MA, etc.) │
│              └─────────┬────────────┘                         │
│                        │                                      │
│              ┌─────────▼────────────┐                         │
│              │  data_loader.py      │  ← Load + cache +       │
│              │                      │     CSV→DB bootstrap    │
│              └─────────┬────────────┘                         │
│                        │                                      │
│              ┌─────────▼────────────┐                         │
│              │  db_client.py        │  ← SQLite read/write    │
│              └─────────┬────────────┘                         │
│                        │                                      │
└────────────────────────┼──────────────────────────────────────┘
                         │ sqlite3
                         ▼
              ┌────────────────────────┐
              │  data/uptrend.db       │
              │  (SQLite)              │
              └────────────────────────┘

┌──────────────────────┐
│  import_excel.py     │ ← Excel → SQLite bulk import
│  (CLI tool)          │
└──────┬───────────────┘
       │ pd.read_excel() + INSERT
       ▼
  data/uptrend.db
```

### 2.2 Layer Structure

| Layer | File | Responsibility |
|-------|------|----------------|
| Presentation | `app.py`, `pages/*.py` | Streamlit UI, user interaction |
| Chart | `src/chart_builder.py` | Plotly Figure object generation |
| Processing | `src/data_processor.py` | Status aggregation, sector summary building |
| Calculation | `src/indicator_calculator.py` | Derived indicator calculation (Ratio, 10MA, Slope, Trend) |
| Data Access | `src/db_client.py` | SQLite read/write, table initialization |
| CLI Tools | `import_excel.py` | Historical data import from Excel |
| CLI Tools | `export_csv.py` | CSV export for LLM access (v3.5, +industry_summary v4.0) |

### 2.3 Data Flow

```
[Dashboard Display]

SQLite (uptrend_raw: date, worksheet, count, total)
  │
  │ db_client.fetch_raw_data(worksheet)
  ▼
pd.DataFrame (date, count, total)          ← Raw data only
  │
  │ indicator_calculator.calculate_indicators(df)
  ▼
pd.DataFrame (+ ratio, ma_10, slope,       ← Derived indicators added
               trend_up, trend_down,
               upper, lower)
  │
  │ data_processor / chart_builder
  ▼
st.plotly_chart()                           ← Browser rendering


[Excel Import]

Excel file (past Google Sheets export)
  │
  │ import_excel.py → pd.read_excel()
  ▼
Extract date, worksheet (=sheet name), count, total
  │
  │ db_client.upsert_raw_data()
  ▼
SQLite uptrend_raw table
```

---

## 3. Data Design

### 3.1 Data Source

| Attribute | Value |
|-----------|-------|
| Storage | SQLite |
| File path | `data/uptrend.db` |
| Access mode | Read-only from the dashboard |
| Stored data | Raw data (Count, Total) only |
| Derived data | Calculated in Python at read time (not stored in DB) |

### 3.2 Design Policy: Store Raw Data Only

**Rationale:**

1. **Single Source of Truth** — Count/Total is the only true data. Ratio and other values are always derived from it
2. **Immediate reflection of calculation logic changes** — When changing MA period or thresholds, only code changes are needed (no DB recalculation)
3. **Minimal DB size** — Only 4 columns. Under ~1 MB even after 10 years of operation
4. **Data consistency** — No inconsistency of derived data (stale data remaining after calculation logic changes)

### 3.3 SQLite Table Definition

```sql
CREATE TABLE IF NOT EXISTS uptrend_raw (
    date      TEXT    NOT NULL,   -- 'YYYY-MM-DD' (ISO 8601)
    worksheet TEXT    NOT NULL,   -- 'all', 'sec_technology', etc.
    count     INTEGER NOT NULL CHECK (count >= 0),   -- uptrend stock count
    total     INTEGER NOT NULL CHECK (total >= 0),   -- total stock count
    CHECK (count <= total),
    PRIMARY KEY (date, worksheet)
);

CREATE INDEX IF NOT EXISTS idx_uptrend_raw_worksheet
    ON uptrend_raw (worksheet, date);
```

**Table: `uptrend_raw`**

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| date | TEXT | NOT NULL, PK | Date (YYYY-MM-DD) |
| worksheet | TEXT | NOT NULL, PK | Category name |
| count | INTEGER | NOT NULL, CHECK >= 0 | Uptrend stock count |
| total | INTEGER | NOT NULL, CHECK >= 0 | Total stock count |

**Table-level CHECK constraint:** `count <= total`

> **Note (v3.2):** CHECK constraints are enforced only for newly created databases. Existing databases retain the original schema since `CREATE TABLE IF NOT EXISTS` skips table creation when the table already exists. Python-level validation in `_validate_counts()` and `upsert_bulk()` provides equivalent enforcement regardless of DB schema version.

**Composite primary key:** `(date, worksheet)` — Prevents duplicates for the same date and category
**Index:** `(worksheet, date)` — Optimizes time-series queries by category

### 3.4 Worksheet Values

| Value | Description | Data Start Date | Approx. Rows |
|-------|-------------|-----------------|--------------|
| `all` | Full market aggregate | 2023-08-11 | ~650 |
| `sec_basicmaterials` | Basic Materials | 2024-07-21 | ~370 |
| `sec_communicationservices` | Communication Services | 2024-07-21 | ~370 |
| `sec_consumercyclical` | Consumer Cyclical | 2024-07-21 | ~370 |
| `sec_consumerdefensive` | Consumer Defensive | 2024-07-21 | ~370 |
| `sec_energy` | Energy | 2024-07-21 | ~370 |
| `sec_financial` | Financial | 2024-07-21 | ~370 |
| `sec_healthcare` | Healthcare | 2024-07-21 | ~370 |
| `sec_industrials` | Industrials | 2024-07-21 | ~370 |
| `sec_realestate` | Real Estate | 2024-07-21 | ~370 |
| `sec_technology` | Technology | 2024-07-21 | ~370 |
| `sec_utilities` | Utilities | 2024-07-21 | ~370 |
| `ind_*` (149 entries) | Industries (e.g., `ind_semiconductors`, `ind_banksregional`, etc.) | v4.0+ | — |

> **v4.0:** 149 industry worksheets added. Full list defined in `src/constants.py` `INDUSTRIES`. Each industry belongs to exactly one sector via `SECTOR_INDUSTRIES` mapping. Total: 161 worksheets (1 `all` + 11 `sec_*` + 149 `ind_*`).

### 3.5 Data Volume Estimate

| Item | Before v4.0 | After v4.0 |
|------|-------------|------------|
| Worksheets | 12 | 161 |
| Daily row increase | 12 | 161 |
| Annual row increase | ~3,024 | ~40,572 |
| Total rows after 10 years | ~35,000 | ~408,000 |
| DB size after 10 years | ~1 MB | ~13 MB |

### 3.6 Derived Data Definitions

The following data is not stored in the DB; `indicator_calculator.py` calculates it at read time.

| Column | Formula | Description |
|--------|---------|-------------|
| ratio | `count / total` | Uptrend stock ratio (0.0–1.0) |
| ma_10 | `ratio.rolling(10).mean()` | 10-day simple moving average of Ratio |
| slope | `ma_10.diff()` | 1-day change of 10MA |
| trend_up | `ratio` (when slope > 0) / NaN | Ratio value during uptrend |
| trend_down | `ratio` (when slope <= 0) / NaN | Ratio value during downtrend |
| upper | constant `0.37` | Overbought threshold |
| lower | constant `0.097` | Oversold threshold |

### 3.7 Status Determination Logic

```
Trend:
  slope > 0 → "up" (green)
  slope <= 0 → "down" (red)
  slope is NaN (insufficient data) → "neutral" (gray)

Status:
  ratio > upper (0.37) → "Overbought"
  ratio < lower (0.097) → "Oversold"
  otherwise → "Normal"
```

### 3.8 Chart Color Coding

The Ratio time series line is color-coded segment by segment according to trend state.

| Trend State | Condition | Color | Color Code |
|-------------|-----------|-------|------------|
| Uptrend | slope > 0 | Green | `#00cc96` |
| Downtrend | slope <= 0 | Red | `#ef553b` |
| Insufficient data | slope is NaN (below MA calculation period) | Gray | `#636efa` |

Implementation: Plotly `Scatter` traces are split into segments of consecutive identical trend states, with the corresponding color assigned to each segment. Boundary points between adjacent segments are duplicated to prevent gaps.

---

## 4. Module Design

### 4.0 constants.py — Constants Module (new in v2.2, extended v4.0)

Centrally manages constants used across all modules.

| Constant | Description |
|----------|-------------|
| `SECTORS` | List of 11 sector worksheet names |
| `INDUSTRIES` | List of 149 industry worksheet names (v4.0) |
| `VALID_WORKSHEETS` | `["all"] + SECTORS + INDUSTRIES` (161 entries, v4.0) |
| `SECTOR_DISPLAY_NAMES` | Sector suffix → display name mapping |
| `INDUSTRY_DISPLAY_NAMES` | Industry suffix → display name mapping (v4.0) |
| `SECTOR_INDUSTRIES` | Sector key → list of industry keys mapping (v4.0) |
| `INDUSTRY_TO_SECTOR` | Industry key → sector key reverse lookup (v4.0) |
| `MAX_INDUSTRY_COMPARISON` | Max industries in comparison chart (15, v4.0) |
| `UPPER_THRESHOLD` | Overbought threshold (0.37) |
| `LOWER_THRESHOLD` | Oversold threshold (0.097) |
| `MA_PERIOD` | Moving average period (10) |
| `CHART_HEIGHT_*` | Chart height constants (`CHART_HEIGHT_HEATMAP = 700` added v4.2) |
| `DEFAULT_DISPLAY_YEARS` | Default display period limit in years (2, v4.3) |

**Helper functions (v4.0):**

| Function | Signature | Description |
|----------|-----------|-------------|
| `is_sector` | `(ws: str) -> bool` | Check if worksheet is a sector |
| `is_industry` | `(ws: str) -> bool` | Check if worksheet is an industry |

### 4.1 db_client.py — Data Access Layer

**Class: `DBClient`**

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `(db_path: str = "data/uptrend.db")` | DB connection, automatic table creation |
| `_connection` | `() -> ContextManager` | DB connection context manager (auto commit/rollback/close) |
| `_init_tables` | `() -> None` | Execute CREATE TABLE IF NOT EXISTS |
| `_coerce_whole_number` | `(value, field_name) -> int` | Static. Coerce int-like values to int; reject bool, non-integer float (v3.2) |
| `_validate_counts` | `(count, total) -> Tuple[int, int]` | Coerce + validate non-negative, count <= total (v3.2) |
| `upsert_raw_data` | `(date, worksheet, count, total) -> None` | Single row UPSERT with worksheet + count/total validation |
| `upsert_bulk` | `(df: DataFrame) -> None` | DataFrame bulk UPSERT with comprehensive validation (v3.2) |
| `fetch_raw_data` | `(worksheet: str) -> DataFrame` | Fetch all data for specified category |
| `fetch_all_raw_data` | `(worksheets=None) -> Dict[str, DataFrame]` | Fetch categories (all if None, filtered subset if specified, v4.0) |
| `get_worksheets` | `() -> List[str]` | List of registered category names |
| `get_date_range` | `(worksheet: str) -> Tuple[str, str]` | Date range for specified category |

**Count/Total Validation (v3.2):**

`upsert_raw_data` applies `_validate_counts()` which coerces types via `_coerce_whole_number()` and validates business rules. `upsert_bulk` performs equivalent validation at the DataFrame level before DB write:

| Check | `upsert_raw_data` | `upsert_bulk` |
|-------|-------------------|---------------|
| Missing columns | N/A | `required_columns - set(df.columns)` |
| Bool rejection | `isinstance(value, bool)` → ValueError | N/A (pandas converts) |
| Non-numeric | `_coerce_whole_number` type check | `pd.to_numeric(errors="coerce")` + NaN check |
| Non-integer | `float.is_integer()` check | `counts % 1 != 0` mask |
| Negative | `count_i < 0` check | `counts < 0` mask |
| count > total | `count_i > total_i` check | `counts > totals` mask |

**DB Connection Management Pattern (v2.2):**

```python
@contextmanager
def _connection(self):
    conn = sqlite3.connect(self.db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
```

All DB operation methods use the `with self._connection() as conn:` pattern, ensuring connection leak prevention and transaction safety.

**UPSERT Statement:**

```sql
INSERT OR REPLACE INTO uptrend_raw (date, worksheet, count, total)
VALUES (?, ?, ?, ?)
```

**fetch_raw_data Query:**

```sql
SELECT date, count, total
FROM uptrend_raw
WHERE worksheet = ?
ORDER BY date ASC
```

**Caching:**

| Function | Module | TTL | Description |
|----------|--------|-----|-------------|
| `load_all_data()` | `data_loader.py` | — | Loads all 161 worksheets + `calculate_indicators()`. Auto-bootstraps DB from CSV if needed |
| `load_sector_data()` | `data_loader.py` | — | Loads `["all"] + SECTORS` (12 worksheets) + `calculate_indicators()` |
| `load_industry_data()` | `data_loader.py` | — | Loads industries (optional sector filter) + `calculate_indicators()` |
| `cached_load_all_data()` | `data_loader.py` | 3600 sec | `@st.cache_data` wrapper for `load_all_data()`, cross-page shared |
| `cached_load_sector_data()` | `data_loader.py` | 3600 sec | `@st.cache_data` wrapper for `load_sector_data()`, cross-page shared |

### 4.2 indicator_calculator.py — Derived Indicator Calculation Layer (new)

| Function | Signature | Description |
|----------|-----------|-------------|
| `calculate_indicators` | `(df: DataFrame, config: IndicatorConfig = None) -> DataFrame` | Adds all derived indicator columns to the raw data DataFrame |
| `_calc_ratio` | `(df) -> Series` | count / total (NaN handled with `fillna(0)`) |
| `_calc_ma` | `(ratio, period) -> Series` | Moving average |
| `_calc_slope` | `(ma) -> Series` | 1-day change of MA |
| `_calc_trend` | `(ratio, slope) -> (Series, Series)` | trend_up, trend_down |

**IndicatorConfig:**

```python
@dataclass
class IndicatorConfig:
    ma_period: int = 10           # Moving average period
    upper_threshold: float = 0.37 # Overbought threshold
    lower_threshold: float = 0.097 # Oversold threshold
```

Consolidating settings into a class enables managing threshold and MA period changes in a single place.

**Input DataFrame (from db_client):**

| Column | Type |
|--------|------|
| date | datetime64 |
| count | int |
| total | int |

**Output DataFrame (after calculate_indicators):**

| Column | Type | Calculated From |
|--------|------|-----------------|
| date | datetime64 | Unchanged |
| count | int | Unchanged |
| total | int | Unchanged |
| ratio | float | count / total |
| ma_10 | float | ratio.rolling(10).mean() |
| slope | float | ma_10.diff() |
| trend_up | float or NaN | ratio if slope > 0 |
| trend_down | float or NaN | ratio if slope <= 0 |
| upper | float | constant 0.37 |
| lower | float | constant 0.097 |

### 4.3 data_processor.py — Status Aggregation Layer

Responsibility changes from v1:

| v1 Responsibility | v2 Change |
|-------------------|-----------|
| Type conversion/cleaning (`process_worksheet_data`) | **Removed** — Types are determined at DB fetch time |
| `_clean_numeric` helper | **Removed** — No longer needed |
| `get_current_status` | **Retained** — Extract status from latest row |
| `build_sector_summary` | **Retained** — Build sector summary |
| `_sector_display_name` | **Retained** — Category name to display name conversion |

**v2.2 Functions:**

| Function | Signature | Description |
|----------|-----------|-------------|
| `get_current_status` | `(df: DataFrame) -> MarketStatus` | Extract status from latest row (empty DF handling) |
| `build_sector_summary` | `(all_data: Dict) -> DataFrame` | Build all-sector summary (empty data handling) |
| `get_sector_display_name` | `(name: str) -> str` | Category name → display name conversion (public API) |
| `filter_by_date_range` | `(df, start, end) -> DataFrame` | Date range filter |
| `prepare_timeseries_csv` | `(df: DataFrame) -> DataFrame` | Select/format columns for time series CSV export (v3.4) |
| `prepare_all_timeseries_csv` | `(all_data: Dict[str, DataFrame]) -> DataFrame` | Combine all worksheets into single timeseries CSV with `worksheet` column (v3.5) |
| `get_industry_display_name` | `(name: str) -> str` | Industry key → display name conversion (v4.0) |
| `build_industry_summary` | `(all_data: Dict, sector_key=None) -> DataFrame` | Industry summary (all or filtered by sector, v4.0) |
| `get_sector_for_industry` | `(industry_key: str) -> Optional[str]` | Reverse lookup: industry → parent sector (v4.0) |
| `style_status_row` | `(row) -> list` | Row styling for Trend/Status columns, shared across pages (v4.0) |
| `build_industry_summary_with_sector` | `(all_data: Dict) -> DataFrame` | Industry summary with Sector and Total columns for heatmap (v4.2) |
| `default_start_date` | `(min_date: date, max_date: date) -> date` | Default start date clamped to at most DEFAULT_DISPLAY_YEARS years before max_date (v4.3) |

**MarketStatus dataclass (new in v2.2):**

```python
@dataclass
class MarketStatus:
    date: str
    ratio: float
    ratio_10ma: Optional[float]
    trend: str
    slope: float
    is_overbought: bool
    is_oversold: bool
```

Provides dict-compatible `__getitem__`, `__contains__`, `keys()` methods. Improves type safety without breaking existing code.

**get_current_status Return Value (unchanged from v1):**

```python
{
    "date": str,           # "2024-01-08"
    "ratio": float,        # 0.29
    "ratio_10ma": float,   # 0.288
    "trend": str,          # "up" | "down"
    "slope": float,        # 0.001
    "is_overbought": bool, # False
    "is_oversold": bool,   # False
}
```

> **Note:** Column names referenced by `get_current_status` changed in v2. `"10MA ratio"` → `"ma_10"`, `"Trend Up ratio"` → `"trend_up"`, etc. Aligned with indicator_calculator output column names.

**build_sector_summary Output Columns (unchanged from v1):**

| Column | Type | Description |
|--------|------|-------------|
| Sector | str | Display name |
| Ratio | float | Latest ratio |
| 10MA | float | Latest ma_10 |
| Trend | str | "Up" / "Down" |
| Slope | float | Latest slope |
| Status | str | "Overbought" / "Oversold" / "Normal" |
| _key | str | Internal worksheet key (e.g., "sec_technology"). Used for chart `customdata`; excluded from `st.dataframe` display (v3.3) |

### 4.4 chart_builder.py — Chart Generation Layer

v2.1 removed signal markers and switched to Ratio line color coding. v2.2 split `build_ratio_chart` into 5 helper functions.

**Public Functions:**

| Function | Signature | Description |
|----------|-----------|-------------|
| `build_ratio_chart` | `(df, title) -> go.Figure` | Ratio time series chart (calls helpers below) |
| `build_sector_summary_chart` | `(summary_df) -> go.Figure` | Sector horizontal bar chart (with `customdata` for click navigation, v3.3) |
| `build_sector_comparison_chart` | `(all_data, selected, use_ma=True) -> go.Figure` | Sector comparison overlay (v2.3, refactored v4.0) |
| `build_industry_summary_chart` | `(summary_df, sector_name="") -> go.Figure` | Industry horizontal bar chart with click navigation (v4.0) |
| `build_industry_comparison_chart` | `(all_data, selected_industries=None, use_ma=True) -> go.Figure` | Industry comparison overlay (v4.0) |
| `build_industry_heatmap` | `(summary_df, color_mode="ratio", size_mode="uniform") -> go.Figure` | Industry treemap grouped by sector (v4.2) |

**build_ratio_chart Internal Helpers (v2.2 decomposition):**

| Function | Description |
|----------|-------------|
| `_add_ratio_segments(fig, df)` | Add color-coded Ratio segments by trend state |
| `_add_moving_average(fig, df)` | Add 10MA line |
| `_add_peaks_and_troughs(fig, df)` | Add peak/trough markers on 10MA |
| `_add_threshold_lines(fig, df)` | Add Upper/Lower threshold lines |
| `_apply_chart_layout(fig, df, title)` | Apply layout settings (title, axes, height, etc.) |

**Column Name Mapping (v1 → v2):**

| v1 (from Google Sheets) | v2 (indicator_calculator output) |
|--------------------------|-------------------------------|
| Ratio | ratio |
| 10MA ratio | ma_10 |
| Trend Up ratio | trend_up |
| Trend Down ratio | trend_down |
| Upper ratio | upper |
| Lower ratio | lower |
| Slope | slope |
**build_ratio_chart Trace Structure (v2.1: signal markers removed, color segmentation):**

| # | Trace | Type | Color | Style |
|---|-------|------|-------|-------|
| 1~N | Ratio (segments) | Scatter line | Green `#00cc96` / Red `#ef553b` / Gray `#636efa` | Solid width=2, color-coded by trend state |
| N+1 | 10MA | Scatter line | `#ff7f0e` (orange) | Dashed width=1.5 |
| N+2 | Upper | Scatter line | `#d62728` (red) | Dotted width=1 |
| N+3 | Lower | Scatter line | `#2ca02c` (green) | Dotted width=1 |

> Ratio line is split into segments where the same trend state persists. Each segment's color represents the trend direction (up=green, down=red, insufficient data=gray). Legend shows only "Ratio (Up)" / "Ratio (Down)" rather than per-segment entries, with `showlegend=False` suppressing duplicate legend items.

**build_sector_comparison_chart Trace Structure (v2.3 revision):**

| # | Trace | Type | Color | Style |
|---|-------|------|-------|-------|
| 1~11 | Sector lines (ma_10 or ratio) | Scatter line | 11 colors from `SECTOR_PALETTE` | Solid width=2, legend sorted by latest value descending |
| 12 | Upper (0.37) | hline + legend trace | `#d62728` (red) | Dashed width=1 |
| 13 | Lower (0.097) | hline + legend trace | `#2ca02c` (green) | Dashed width=1 |

`SECTOR_PALETTE` (defined in chart_builder.py):

| Index | Color | Color Code |
|-------|-------|------------|
| 0 | Blue | `#1f77b4` |
| 1 | Orange | `#ff7f0e` |
| 2 | Green | `#2ca02c` |
| 3 | Red | `#d62728` |
| 4 | Purple | `#9467bd` |
| 5 | Brown | `#8c564b` |
| 6 | Pink | `#e377c2` |
| 7 | Gray | `#7f7f7f` |
| 8 | Olive | `#bcbd22` |
| 9 | Cyan | `#17becf` |
| 10 | Dark Orange | `#ff6600` |

> With `use_ma=True` (default), the `ma_10` column is plotted, reducing noise with smooth lines. With `use_ma=False`, the raw `ratio` is displayed. Each sector line has a `Sector Name XX%` annotation at its right end. Y-axis uses `tickformat=".0%"` for percentage display.

### 4.5 import_excel.py — Excel Import Tool (new)

**Purpose:** Import historical data from Google Sheets-exported Excel files into SQLite.

**CLI Interface:**

```bash
# Single file (reads all sheets)
python import_excel.py data/export.xlsx

# Specific sheets only
python import_excel.py data/export.xlsx --sheet all --sheet sec_technology

# Specify DB path
python import_excel.py data/export.xlsx --db data/uptrend.db

# Dry run (shows counts without INSERT)
python import_excel.py data/export.xlsx --dry-run
```

**Processing Flow:**

```
1. Read all sheets from Excel file with pd.read_excel(sheet_name=None)
   → Get Dict[str, DataFrame]

2. For each sheet:
   a. Validate that sheet name is a valid worksheet value
   b. Extract Date, Count, Total columns
   c. Convert Date to YYYY-MM-DD format
   d. Remove empty/invalid rows (null dates, non-numeric values)
   e. Drop non-integer Count/Total rows (e.g., 1.5) with warning (v3.2)
   f. Drop logically invalid rows (negative, count > total) with warning (v3.2)

3. Bulk write to SQLite with db_client.upsert_bulk(df)
   → INSERT OR REPLACE overwrites existing data

4. Display result report:
   - Import row count per sheet
   - Skipped row count (no date, etc.)
   - Overwritten duplicate row count
```

**Expected Excel File Format:**

`.xlsx` file downloaded from Google Sheets. Each sheet contains the following columns:

| Column | Required | Description |
|--------|----------|-------------|
| Date | Yes | Date (M/D/YYYY, etc., any format parseable by pandas) |
| Count | Yes | Uptrend stock count |
| Total | Yes | Total stock count |
| Other | No | Ignored (pre-calculated columns like Ratio, 10MA, etc.) |

---

## 5. Screen Design

Screen layout is unchanged from v1. Only the data source changes; UI remains the same.

### 5.1 Main Page (app.py)

```
┌─────────────────────────────────────────────────────────────┐
│ Sidebar                │ US Market Uptrend Stock Ratio       │
│ ┌───────────────────┐  │                                     │
│ │ [Settings]        │  │ ┌──────┐┌──────┐┌──────┐┌────────┐│
│ │                   │  │ │Ratio ││ 10MA ││Trend ││ Status ││
│ │ [Refresh Data]    │  │ │29.0% ││28.8% ││ Up   ││ Normal ││
│ │                   │  │ └──────┘└──────┘└──────┘└────────┘│
│ │ Date Range:       │  │ Last updated: 2024-01-08            │
│ │ [2023-08-11]      │  │                                     │
│ │ [2024-01-08]      │  │ Full Market Ratio                   │
│ │                   │  │ ┌─────────────────────────────────┐ │
│ └───────────────────┘  │ │    [Ratio Chart]                │ │
│                        │ └─────────────────────────────────┘ │
│                        │                                     │
│                        │ Sector Summary                      │
│                        │ ┌───────────────────┐┌────────────┐│
│                        │ │ [Horizontal Bar]  ││ [Table]    ││
│                        │ │  Chart            ││ Sector ... ││
│                        │ │ (clickable→Detail)││(click→Detail)│
│                        │ └───────────────────┘└────────────┘│
│                        │                                     │
│                        │ ─────────────────────────────────── │
│                        │ Data Download                       │
│                        │ ┌────────────────┐┌────────────────┐│
│                        │ │ Download Ratio ││ Download       ││
│                        │ │ Time Series    ││ Sector Summary ││
│                        │ └────────────────┘└────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

### 5.2 Sector Detail Page (pages/1_Sector_Detail.py)

```
┌─────────────────────────────────────────────────────────────┐
│ Sector Detail                                               │
│                                                             │
│ Select Sector: [Technology ▼]                               │
│                                                             │
│ ┌──────┐┌──────┐┌──────┐┌──────┐┌────────┐                │
│ │Ratio ││ 10MA ││Trend ││Slope ││ Status │                │
│ └──────┘└──────┘└──────┘└──────┘└────────┘                │
│                                                             │
│ Date Range: [start] ~ [end]                                 │
│                                                             │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │    [Ratio Chart — green/red/gray trend colors]          │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ ─────────────────────────────────────────────────────────── │
│ Industries in {Sector}                              (v4.0)  │
│ ┌─────────────────────┐ ┌───────────────────────────────┐  │
│ │ [Horizontal Bar     │ │ [Table: Industry, Ratio,      │  │
│ │  Chart]             │ │  10MA, Trend, Slope, Status]  │  │
│ │ (click→Ind Detail)  │ │ (click row→Industry Detail)   │  │
│ └─────────────────────┘ └───────────────────────────────┘  │
│                                                             │
│ ─────────────────────────────────────────────────────────── │
│ Data Download                                               │
│ ┌────────────────────────┐┌─────────────────────────────┐  │
│ │ Download {Sector}      ││ Download {Sector}            │  │
│ │ Time Series            ││ Industry Summary             │  │
│ └────────────────────────┘└─────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 5.3 Sector Comparison Page (pages/2_Sector_Comparison.py)

```
┌─────────────────────────────────────────────────────────────┐
│ Sector Comparison                                           │
│                                                             │
│ Select Sectors: [x] Basic Materials  [x] Technology  ...    │
│                                                             │
│ Date Range: [start] ~ [end]                                 │
│                                                             │
│ Display Mode: (●) Smoothed (10MA)  ( ) Raw Ratio            │
│                                                             │
│ ┌─────────────────────────────────────────────────────┬───┐ │
│ │                                          Upper 37%  │   │ │
│ │    [Multi-line Overlay Chart]            ─ ─ ─ ─ ─  │ L │ │
│ │    - 11-color custom palette                        │ e │ │
│ │    - MA10 or Raw Ratio toggle                       │ g │ │
│ │    - Y-axis: 0% ~ 60%                 Lower 10%    │ e │ │
│ │                                          ─ ─ ─ ─ ─  │ n │ │
│ │                              Tech 42% ←(latest val) │ d │ │
│ │                          Financial 38%              │   │ │
│ └─────────────────────────────────────────────────────┴───┘ │
└─────────────────────────────────────────────────────────────┘
```

v2.3 revision: Display mode radio buttons, 10MA/Raw toggle, threshold dashed lines, latest value annotations, Y-axis % format, legend sorting (latest value descending).

### 5.4 Industry Detail Page (pages/3_Industry_Detail.py, v4.0)

```
┌─────────────────────────────────────────────────────────────┐
│ Industry Detail                                             │
│                                                             │
│ Filter by Sector: [All Sectors ▼]                           │
│ Select Industry: [Semiconductors ▼]                         │
│ Parent Sector: Technology                                   │
│                                                             │
│ ┌──────┐┌──────┐┌──────┐┌──────┐┌────────┐                │
│ │Ratio ││ 10MA ││Trend ││Slope ││ Status │                │
│ └──────┘└──────┘└──────┘└──────┘└────────┘                │
│                                                             │
│ Date Range: [start] ~ [end]                                 │
│                                                             │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │    [Ratio Chart — green/red/gray trend colors]          │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ ─────────────────────────────────────────────────────────── │
│ Data Download                                               │
│ ┌───────────────────────────────────┐                       │
│ │ Download {Industry} Time Series   │                       │
│ └───────────────────────────────────┘                       │
└─────────────────────────────────────────────────────────────┘
```

### 5.5 Industry Comparison Page (pages/4_Industry_Comparison.py, v4.0)

```
┌─────────────────────────────────────────────────────────────┐
│ Industry Comparison                                         │
│                                                             │
│ Compare Mode: (●) Within Sector  ( ) Cross-Sector           │
│                                                             │
│ [Within Sector mode:]                                       │
│ Select Sector: [Technology ▼]                               │
│ Select Industries: [x] Semiconductors [x] Software App ...  │
│                                                             │
│ [Cross-Sector mode:]                                        │
│ Select Industries (max 15): [ ] Tech / Semiconductors ...   │
│                                                             │
│ Date Range: [start] ~ [end]                                 │
│ Display Mode: (●) Smoothed (10MA)  ( ) Raw Ratio            │
│                                                             │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │    [Multi-line Industry Comparison Chart]                │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 5.6 Industry Heatmap Page (pages/5_Industry_Heatmap.py, v4.2)

```
┌─────────────────────────────────────────────────────────────┐
│ Industry Heatmap                                             │
│                                                             │
│ Color Mode: (●) Ratio  ( ) Trend Status     [horizontal]    │
│ Size Mode:  (●) Uniform  ( ) Stock Count    [horizontal]    │
│                                                             │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │  [Treemap: 149 cells grouped by 11 sectors]             │ │
│ │  Sector→Industry hierarchy, RdYlGn colorscale           │ │
│ │  Display only (no click navigation)                     │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ ─────────────────────────────────────────────────────────── │
│ Industry Summary                                            │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Sector | Industry | Ratio | 10MA | Trend | Slope | Stat │ │
│ │ (sorted by Sector, then Industry)                       │ │
│ │ (row click → Industry Detail page)                      │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

## 6. Non-Functional Requirements

### 6.1 Performance

| Item | v1 (Google Sheets) | v2 (SQLite) |
|------|-------------------|-------------|
| Initial load | 20–30 sec | < 1 sec (local DB) |
| Cache TTL | 1 hour | 1 hour (same) |
| Cache hit | Near-instant | Near-instant |
| API rate limit | 1 sec/worksheet | Not needed |
| Derived indicator calc | Not needed (sheet formulas) | ~few ms (even for 35,000 rows) |

### 6.2 Reliability

| Item | Specification |
|------|---------------|
| DB file corruption protection | Consider SQLite WAL mode (improved concurrent reads) |
| No data available | Display with `st.error` / `st.warning` |
| Idempotency via UPSERT | Re-inserting the same (date, worksheet) overwrites |

### 6.3 Deployment

| Environment | DB Path | Configuration |
|-------------|---------|---------------|
| Local | `data/uptrend.db` | `DB_PATH` configurable via `.env` |
| Streamlit Cloud | `/mount/data/uptrend.db` etc. | Persistent storage requires consideration |

> **Note:** Streamlit Cloud has a volatile file system, so persisting the SQLite file requires additional measures (include DB in git, external storage integration, etc.). Local operation is the primary use case.

### 6.4 UI Theme (unchanged from v1)

| Property | Value |
|----------|-------|
| primaryColor | `#1f77b4` |
| backgroundColor | `#0e1117` |
| secondaryBackgroundColor | `#262730` |
| textColor | `#fafafa` |
| font | sans serif |
| Chart template | `plotly_dark` |

---

## 7. File Structure

```
uptrend-dashboard/
├── .github/
│   └── workflows/
│       ├── collect-data.yml           # Daily data collection (cron)
│       └── test.yml                   # CI: pytest on push/PR (v3.2)
├── .streamlit/
│   └── config.toml                    # Streamlit theme settings
├── data/
│   ├── uptrend.db                     # SQLite DB
│   ├── uptrend_ratio_timeseries.csv   # All worksheets timeseries (v3.5, auto-generated)
│   ├── sector_summary.csv            # Sector summary snapshot (v3.5, auto-generated)
│   └── industry_summary.csv          # Industry summary snapshot (v4.0, auto-generated)
├── docs/
│   └── design.md                      # This design document
├── src/
│   ├── __init__.py
│   ├── constants.py                   # Constants (new in v2.2)
│   ├── db_client.py                   # SQLite read/write (formerly sheets_client.py)
│   ├── indicator_calculator.py        # Derived indicator calculation (new)
│   ├── data_processor.py             # Status aggregation
│   ├── chart_builder.py              # Plotly chart generation
│   └── data_collector.py             # Finviz data collection (Phase 3)
├── tests/
│   ├── __init__.py
│   ├── conftest.py                    # Shared test fixtures
│   ├── test_db_client.py             # db_client tests
│   ├── test_indicator_calculator.py  # Derived indicator calculation tests
│   ├── test_data_processor.py        # data_processor tests
│   ├── test_export_csv.py            # export_csv tests (v3.5)
│   ├── test_chart_builder.py         # chart_builder tests
│   ├── test_integration.py          # Integration tests (new in v2.2)
│   └── test_data_collector.py        # data_collector tests (Phase 3)
├── pages/
│   ├── 1_Sector_Detail.py            # Sector detail page (+ industry drilldown v4.0)
│   ├── 2_Sector_Comparison.py        # Sector comparison page
│   ├── 3_Industry_Detail.py          # Industry detail page (v4.0)
│   ├── 4_Industry_Comparison.py      # Industry comparison page (v4.0)
│   └── 5_Industry_Heatmap.py        # Industry treemap heatmap page (v4.2)
├── app.py                            # Main page
├── import_excel.py                   # Excel import CLI tool (Phase 1)
├── collect.py                        # Finviz data collection CLI tool (Phase 3)
├── export_csv.py                     # CSV export CLI tool (v3.5)
├── requirements.txt
├── .env.sample
├── .gitignore
└── README.md
```

### v1 → v2 File Change Summary

| Change Type | File | Description |
|-------------|------|-------------|
| Deleted | `src/sheets_client.py` | Removed Google Sheets dependency |
| New | `src/db_client.py` | SQLite data access |
| New | `src/indicator_calculator.py` | Derived indicator calculation logic |
| New | `import_excel.py` | Excel → SQLite import tool (Phase 1) |
| New | `src/data_collector.py` | Finviz data collection → SQLite write (Phase 3) |
| New | `collect.py` | Finviz data collection CLI entry point (Phase 3) |
| New | `tests/test_data_collector.py` | data_collector tests (Phase 3) |
| New | `data/` directory | SQLite DB storage location |
| Modified | `src/data_processor.py` | Removed type conversion logic, updated column names |
| Modified | `src/chart_builder.py` | Updated column names to v2 |
| Modified | `app.py`, `pages/*.py` | Changed data source to db_client |
| Deleted | `tests/test_sheets_client.py` | Removed with sheets_client |
| New | `tests/test_db_client.py` | db_client tests |
| New | `tests/test_indicator_calculator.py` | Derived indicator calculation tests |
| Modified | `tests/conftest.py` | Updated fixtures to v2 column names |
| New | `src/constants.py` | Centralized constants (v2.2) |
| New | `tests/test_integration.py` | Integration tests (v2.2) |

---

## 8. Dependencies

| Package | Version | Purpose | v1→v2 |
|---------|---------|---------|-------|
| streamlit | >= 1.35.0 | Web framework (`on_select` requires >=1.35.0, v3.3) | Retained |
| plotly | >= 5.18.0 | Interactive charts | Retained |
| pandas | >= 2.0.0 | Data manipulation | Retained |
| openpyxl | >= 3.1.0 | Excel file reading | **New** |
| requests | >= 2.31.0 | Finviz API HTTP requests (Phase 3) | **New** |
| python-dateutil | >= 2.8.0 | Accurate year arithmetic via `relativedelta` (v4.3) | **New** |
| python-dotenv | >= 1.0.0 | Environment variable loading | Retained |
| pytest | >= 8.0.0 | Test framework | Retained |
| pytest-mock | >= 3.12.0 | Mock library | Retained |
| ~~gspread~~ | — | — | **Removed** |
| ~~oauth2client~~ | — | — | **Removed** |

> `sqlite3` is not listed as a dependency since it is part of the Python standard library.

---

## 9. Test Design

### 9.1 Test Strategy

Implemented with TDD. Tests are written first, and implementation is written to pass the tests.

### 9.2 Test List

**test_db_client.py:**

| Test | Description |
|------|-------------|
| test_init_creates_table | Automatic table creation |
| test_upsert_inserts_new_row | Insert new row |
| test_upsert_replaces_existing | Overwrite with same key |
| test_upsert_bulk | DataFrame bulk insert |
| test_fetch_raw_data | Fetch single category |
| test_fetch_raw_data_empty | Category with no data |
| test_fetch_all_raw_data | Fetch all categories at once |
| test_get_worksheets | List of registered categories |
| test_get_date_range | Get date range |
| test_context_manager_closes_connection | Context manager closes connection |
| test_context_manager_commits_on_success | Commit on success |
| test_context_manager_rollbacks_on_error | Rollback on exception |
| test_bulk_upsert_executemany | Bulk insert via executemany |
| test_bulk_upsert_atomicity | Transaction atomicity (rollback on invalid row) |
| test_upsert_rejects_invalid_worksheet | Reject invalid worksheet |
| test_upsert_accepts_valid_worksheet | Accept valid worksheet |
| test_bulk_upsert_rejects_invalid_worksheet | Reject invalid worksheet in bulk insert |
| test_upsert_rejects_negative_count | Negative count → ValueError (v3.2) |
| test_upsert_rejects_count_exceeding_total | count > total → ValueError (v3.2) |
| test_bulk_upsert_rejects_non_integer_values | Non-integer float → ValueError (v3.2) |
| test_upsert_rejects_bool_value | bool → ValueError (v3.2) |
| test_upsert_accepts_float_whole_number | 150.0 coerced to int 150 (v3.2) |
| test_bulk_upsert_rejects_missing_columns | Missing required columns → ValueError (v3.2) |
| test_bulk_upsert_rejects_negative_values | Negative values in bulk → ValueError (v3.2) |
| test_bulk_upsert_rejects_count_exceeding_total | count > total in bulk → ValueError (v3.2) |
| test_upsert_accepts_industry_worksheet | `ind_semiconductors` accepted (v4.0) |
| test_bulk_upsert_accepts_industry_worksheets | Bulk insert with `ind_*` (v4.0) |
| test_fetch_all_raw_data_with_worksheets_filter | Worksheets subset filter (v4.0) |
| test_fetch_all_raw_data_none_returns_all | worksheets=None returns all (v4.0) |
| test_load_sector_data | Loads 12 sector worksheets (v4.0) |
| test_load_industry_data_all | Loads all industries (v4.0) |
| test_load_industry_data_sector_filter | Loads industries for specific sector (v4.0) |

**test_indicator_calculator.py:**

| Test | Description |
|------|-------------|
| test_ratio_values | count/total calculation (via public API) |
| test_ratio_zero_total | Division by zero handling when total=0 |
| test_ma_10_leading_nans | Leading NaN in 10MA |
| test_ma_10_value | 10MA calculation value |
| test_ma_insufficient_data | Data with fewer than 10 rows (NaN period) |
| test_slope_is_ma_diff | Slope is MA diff |
| test_trend_up_matches_positive_slope | slope > 0 → value in trend_up |
| test_trend_down_matches_nonpositive_slope | slope <= 0 → value in trend_down |
| test_calculate_indicators_full | Full indicator integration test |
| test_custom_config | Parameter change via IndicatorConfig |
| test_peaks_detected_in_sine_wave | Peak detection on sine wave data |
| test_troughs_detected_in_sine_wave | Trough detection on sine wave data |
| test_peaks_troughs_boolean_columns | is_peak/is_trough boolean columns |
| test_strict_config_fewer_detections | Fewer detections with strict settings |
| test_calculate_indicators_empty_df | Empty DataFrame handling |
| test_ratio_with_nan_count | NaN count fillna(0) handling |
| test_ratio_with_nan_total | NaN total fillna(0) handling |
| test_short_blip_absorbed | Short regime run absorbed (v5.1) |
| test_confirmation_only_on_min_days | Transition emitted on min_days-th day (v5.1) |
| test_two_day_candidate_not_confirmed_then_revert | 2-day candidate reverts without confirming (v5.1) |
| test_blip_then_revert_to_previous | Candidate returns to confirmed regime (v5.1) |
| test_retransition_to_previously_seen_regime | Same regime re-confirmed later (v5.1) |
| test_initial_baseline_is_first_observation | First observation is the baseline (v5.1) |
| test_missing_observation_resets_candidate | NaN resets candidate run (v5.1) |
| test_min_days_le_one_passthrough | min_days<=1 passthrough (v5.1) |
| test_empty_series_passthrough | Empty series passthrough (v5.1) |
| test_all_nan_passthrough | All-NaN series passthrough (v5.1) |
| test_prefix_invariance | Deterministic prefix-invariance (v5.1) |
| test_prefix_invariance_randomized | Randomized prefix-invariance (v5.1) |
| test_prefix_invariance_with_nan_randomized | Randomized prefix-invariance incl. NaN (v5.1) |
| test_leading_nan_then_baseline | Leading NaN then baseline (v5.1) |
| test_regime_prefix_invariant_across_truncation | calculate_sector_dispersion regime prefix-invariance (v5.1) |
| test_no_event_on_blip_start | Short blip yields no forward-stat event (v5.1) |
| test_event_date_is_confirmation_date | Forward-stat event date = confirmation date (v5.1) |

**test_data_processor.py:**

| Test | Description |
|------|-------------|
| test_get_current_status_uptrend | Status during uptrend |
| test_get_current_status_downtrend | Status during downtrend |
| test_get_current_status_overbought | Overbought determination |
| test_get_current_status_oversold | Oversold determination |
| test_build_sector_summary | Sector summary generation |
| test_build_sector_summary_excludes_all | Excludes "all" |
| test_sector_display_name | Category name conversion |
| test_get_current_status_empty_df | Default value return for empty DataFrame |
| test_build_sector_summary_empty | Empty DF with columns for empty data |
| test_filter_by_date_range | Date range filter |
| test_prepare_timeseries_csv_columns | Output columns: date, count, total, ratio, ma_10, slope, trend (v3.4) |
| test_prepare_timeseries_csv_trend_column | slope > 0 → "up", <= 0 → "down" (v3.4) |
| test_prepare_timeseries_csv_excludes_chart_columns | Excludes trend_up/trend_down/upper/lower/is_peak/is_trough (v3.4) |
| test_columns | Output columns: worksheet, date, count, total, ratio, ma_10, slope, trend (v3.5) |
| test_includes_all_worksheets | All 12 worksheets from input dict appear in output (v3.5) |
| test_sorted_by_worksheet | "all" first, then sec_* alphabetical (v3.5) |
| test_row_count | Total rows = sum of rows in each worksheet (v3.5) |
| test_empty_data | Empty dict → 0-row DataFrame with correct columns (v3.5) |
| test_skips_empty_dataframes | Empty DataFrame worksheets are skipped (v3.5) |
| test_date_format | date column is YYYY-MM-DD string (v3.5) |
| test_get_industry_display_name | Industry key → display name (v4.0) |
| test_get_industry_display_name_unknown | Unknown key fallback (v4.0) |
| test_build_industry_summary | Industry summary generation (v4.0) |
| test_build_industry_summary_sector_filter | Filter by sector_key (v4.0) |
| test_build_industry_summary_no_filter | All industries when sector_key=None (v4.0) |
| test_build_industry_summary_empty | Empty data handling (v4.0) |
| test_get_sector_for_industry | Industry → sector lookup (v4.0) |
| test_get_sector_for_industry_unknown | Unknown key → None (v4.0) |
| test_build_sector_summary_excludes_industries | ind_* excluded from sector summary (v4.0) |
| test_style_status_row_overbought | Overbought row styling (v4.0) |
| test_style_status_row_normal_up | Normal/Up row styling (v4.0) |
| test_build_industry_summary_with_sector_columns | Output columns include Sector, Total (v4.2) |
| test_build_industry_summary_with_sector_sector_values | Sector matches parent sector display name (v4.2) |
| test_build_industry_summary_with_sector_all_industries | All ind_* keys in output (v4.2) |
| test_build_industry_summary_with_sector_empty | Empty data → correct columns (v4.2) |
| test_build_industry_summary_with_sector_total_values | Total = latest total, 0 → 1 (v4.2) |
| test_data_less_than_2_years | Data < 2 years → returns min_date (v4.3) |
| test_data_exactly_2_years | Data exactly 2 years → returns min_date (v4.3) |
| test_data_more_than_2_years | Data > 2 years → returns max_date - 2 years (v4.3) |
| test_leap_year | Leap year handling: 2028-02-29 - 2y = 2026-02-28 (v4.3) |
| test_same_date | min == max → returns that date (v4.3) |

**test_export_csv.py (v3.5, extended v4.0):**

| Test | Description |
|------|-------------|
| test_creates_timeseries_file | CSV timeseries file is created (v3.5) |
| test_creates_summary_file | CSV summary file is created (v3.5) |
| test_timeseries_has_worksheet_column | Generated CSV has worksheet column (v3.5) |
| test_summary_excludes_key_column | Generated CSV excludes _key column (v3.5) |
| test_returns_results | Return value has timeseries/summary with path and rows (v3.5) |
| test_empty_db | Empty DB returns empty dict (v3.5) |
| test_cli_db_not_found | Non-existent DB → exit code 1 (v3.5) |
| test_creates_industry_summary_file | Industry summary CSV is created (v4.0) |
| test_industry_summary_excludes_key_column | Industry summary excludes _key column (v4.0) |
| test_cli_output_dir_not_found | Non-existent output dir → exit code 1 (v3.5) |

**test_chart_builder.py (continued from v1, extended v4.0):**

| Test | Description |
|------|-------------|
| test_ratio_chart_returns_figure | Verify Figure type |
| test_ratio_chart_title | Title setting |
| test_ratio_chart_traces | Trace structure |
| test_ratio_chart_color_segments | Trend color segments (green/red/gray) |
| test_sector_summary_chart | Summary chart |
| test_sector_summary_chart_customdata | Bar trace has customdata with sector keys (v3.3) |
| test_sector_comparison_chart | Comparison chart (11 sectors + 2 thresholds = 13 traces) |
| test_sector_comparison_selected | Filtered comparison (selected sectors + 2 thresholds) |
| test_sector_comparison_uses_ma_by_default | Default 10MA display |
| test_sector_comparison_raw_ratio_mode | Raw Ratio mode toggle |
| test_sector_comparison_has_threshold_traces | Upper/Lower threshold legend display |
| test_sector_comparison_y_axis_percent | Y-axis percentage format |
| test_sector_comparison_annotations | Latest value annotations (one per sector) |
| test_sector_comparison_legend_sorted_by_latest_value | Legend sorted by latest value descending |
| test_sector_comparison_custom_colors | Custom palette usage verification |
| test_industry_summary_chart | Industry summary chart returns go.Figure (v4.0) |
| test_industry_summary_chart_customdata | customdata has ind_* keys (v4.0) |
| test_industry_summary_chart_dynamic_height | Dynamic height based on bar count (v4.0) |
| test_industry_summary_chart_title_with_sector | Title includes sector name (v4.0) |
| test_industry_summary_chart_title_without_sector | Title without sector name (v4.0) |
| test_industry_comparison_chart | Industry comparison trace count (v4.0) |
| test_industry_comparison_selected | Selection filter (v4.0) |
| test_industry_comparison_palette | Industry palette used (v4.0) |
| test_industry_comparison_title | Chart title (v4.0) |
| test_sector_comparison_excludes_industries | ind_* excluded from sector comparison (v4.0) |
| test_industry_heatmap_returns_figure | Returns go.Figure (v4.2) |
| test_industry_heatmap_has_treemap_trace | Contains go.Treemap trace (v4.2) |
| test_industry_heatmap_sector_parents | Sector display names in labels (v4.2) |
| test_industry_heatmap_color_ratio_mode | RdYlGn colorscale in ratio mode (v4.2) |
| test_industry_heatmap_color_status_mode | Categorical STATUS_COLORS in status mode (v4.2) |
| test_industry_heatmap_uniform_size | All values = 1 in uniform mode (v4.2) |
| test_industry_heatmap_customdata | customdata contains _key (v4.2) |
| test_industry_heatmap_empty_data | Empty data no error (v4.2) |

**test_import_excel.py (extended v4.0):**

| Test | Description |
|------|-------------|
| test_import_single_sheet | Import a single specified sheet |
| test_import_all_sheets | Import all valid sheets |
| test_skip_unknown_sheet | Skip sheets with unrecognized names |
| test_skip_empty_date_rows | Skip rows where Date is empty |
| test_date_format_conversion | Dates stored as YYYY-MM-DD |
| test_dry_run | Dry run does not write to DB |
| test_invalid_count_total_rows_are_dropped | Non-integer/negative/count>total rows excluded (v3.2) |
| test_import_industry_sheet | ind_semiconductors sheet accepted (v4.0) |

**test_integration.py (new in v2.2):**

| Test | Description |
|------|-------------|
| test_full_pipeline | End-to-end: Excel → DB → calculation → status → chart |
| test_multi_sector_pipeline | Multiple sectors → DB → calculation → summary → summary chart |
| test_empty_db_pipeline | Graceful handling of full pipeline with empty DB |

**test_data_collector.py (Phase 3 + v3.1 code review fixes + v3.2 secret masking):**

| Test | Description |
|------|-------------|
| test_mask_secrets_hides_auth_query_value | auth= param masked in URL (v3.2) |
| test_mask_secrets_empty_string | Empty string passthrough (v3.2) |
| test_mask_secrets_none | None passthrough (v3.2) |
| test_mask_secrets_no_auth | String without auth unchanged (v3.2) |
| test_build_uptrend_url | Uptrend screener URL construction |
| test_build_uptrend_url_with_sector | URL construction with sector filter |
| test_build_total_url | Total screener URL construction |
| test_fetch_stock_count_success | Stock count from successful response |
| test_fetch_stock_count_retry | Retry logic |
| test_fetch_stock_count_zero | Zero-count response |
| test_make_request_empty_csv_body | 200 + empty body → empty DataFrame (v3.1) |
| test_make_request_retries_on_500 | Retry on 5xx error (v3.1) |
| test_make_request_jitter_applied | Jitter included in retry delay (v3.1) |
| test_session_closed | close() calls Session.close() (v3.1) |
| test_collect_worksheet | Single category fetch → DB write |
| test_collect_all | All 12 categories bulk fetch |
| test_collect_skip_zero_total | Skip UPSERT when total=0 |
| test_validate_counts_negative | Negative value → ValueError (v3.1) |
| test_validate_counts_count_exceeds_total | count > total → ValueError (v3.1) |
| test_collect_worksheet_dry_run | dry_run=True skips DB write (v3.1) |
| test_collect_all_dry_run | collect_all dry_run=True (v3.1) |
| test_cli_exit_code_complete_failure | All failures → exit 1 (v3.1) |
| test_cli_exit_code_partial_failure | Partial failure → exit 2 (v3.1) |
| test_cli_worksheet_error_exit_code | --worksheet failure → exit 1 (v3.1) |
| test_cli_invalid_date_format | Invalid date → exit 1 (v3.1) |
| test_collect_worksheet_industry | ind_semiconductors collection (v4.0) |
| test_collect_all_scope_sectors | scope=SECTORS collects 12 worksheets (v4.0) |
| test_collect_all_scope_industries | scope=INDUSTRIES collects 149 worksheets (v4.0) |
| test_collect_all_returns_collect_result | Return type is CollectResult (v4.0) |
| test_collect_result_sector_industry_split | Sector/industry property split (v4.0) |
| test_build_url_with_industry | ind_semiconductors in URL (v4.0) |
| test_cli_scope_argument | --scope sectors passes CollectScope.SECTORS (v4.0) |
| test_cli_scope_worksheet_simultaneous_error | --worksheet + --scope (any value) → exit 1 (v4.0) |
| test_cli_scope_all_sector_partial_fail_exit2 | Sector partial fail → exit 2 (v4.0) |
| test_cli_scope_all_industry_partial_fail_exit0 | Industry fail + sectors OK → exit 0 (v4.0) |
| test_cli_scope_all_industry_all_fail_exit2 | All sectors OK + all industries failed → exit 2 (v4.0) |

**test_constants.py (v4.0):**

| Test | Description |
|------|-------------|
| test_industries_count | INDUSTRIES has 149 entries |
| test_valid_worksheets_count | VALID_WORKSHEETS has 161 entries |
| test_all_industries_have_display_names | All INDUSTRIES have INDUSTRY_DISPLAY_NAMES |
| test_all_industries_in_exactly_one_sector | Each industry belongs to exactly one sector |
| test_industry_to_sector_matches_industries | INDUSTRY_TO_SECTOR keys match INDUSTRIES |
| test_no_duplicate_industries | No duplicates in INDUSTRIES |
| test_sector_industries_keys_are_valid_sectors | SECTOR_INDUSTRIES keys are valid SECTORS |
| test_is_sector | is_sector() helper function |
| test_is_industry | is_industry() helper function |
| test_default_display_years | DEFAULT_DISPLAY_YEARS == 2 (v4.3) |

### 9.3 Test Fixtures (conftest.py)

| Fixture | Type | Description |
|---------|------|-------------|
| `tmp_db` | `str` | Temporary DB path using `tmp_path` |
| `sample_raw_df` | `DataFrame` | 20-row sample with date, count, total |
| `sample_calculated_df` | `DataFrame` | DataFrame with calculate_indicators applied (no signals) |
| `sample_all_data` | `Dict[str, DataFrame]` | Data for all 12 categories |
| `sample_industry_data` | `Dict[str, DataFrame]` | Data for 3 industry worksheets (v4.0) |
| `sample_all_data_with_industries` | `Dict[str, DataFrame]` | sample_all_data + 3 industry entries (v4.0) |

### 9.4 Mock Targets

| Mock Target | Reason |
|-------------|--------|
| `sqlite3.connect` | Direct mocking not needed since test uses `tmp_path` temporary DB |
| `streamlit` (st) | Testing `st.cache_data` |
| `requests.Session.get` | Mocking Finviz API responses (Phase 3: data_collector tests) |

---

## 10. Relationship with Existing Systems

### 10.1 Final System Architecture (after Phase 4 completion)

```
uptrend-dashboard (self-contained)
┌──────────────────────────────────────────────┐
│                                              │
│  [Finviz Elite API]                          │
│        │                                     │
│        │ Scrape (collect.py / cron)           │
│        ▼                                     │
│  ┌──────────────────────┐                    │
│  │  data/uptrend.db     │  ← SQLite          │
│  │  (local file)        │                    │
│  └─────────┬────────────┘                    │
│            │ Read                             │
│            ▼                                  │
│  ┌──────────────────────┐                    │
│  │  app.py              │  ← Streamlit App    │
│  │  (dashboard display) │                    │
│  └──────────────────────┘                    │
└──────────────────────────────────────────────┘

stocktrading (existing, no changes)
┌──────────────────────────┐
│ uptrend_stocks.py        │  ← Only stop scheduled execution
│ uptrend_count_sector.py  │    Code remains as-is
└──────────────────────────┘
```

### 10.2 Migration Roadmap

| Phase | Description | Target | Priority |
|-------|-------------|--------|----------|
| Phase 1 | Import historical data from Excel to SQLite | uptrend-dashboard | **Implemented** |
| Phase 2 | Switch dashboard to SQLite reads | uptrend-dashboard | **Implemented** |
| Phase 3 | Change stocktrading write destination to SQLite | stocktrading | Next |
| Phase 4 | Fully remove Google Sheets dependency | Both projects | After Phase 3 |

### 10.3 Phase 1–2 (Current Scope)

**Phase 1: Excel Import**
- Implement `import_excel.py`
- Google Sheets → Excel download → SQLite bulk import
- Migrate historical data (all: from 2023-08-11, sectors: from 2024-07-21)

**Phase 2: Dashboard SQLite Migration**
- Implement `db_client.py`, `indicator_calculator.py`
- Delete `sheets_client.py` and switch all pages' data source to SQLite
- Remove `gspread`, `oauth2client` dependencies

**Operations during Phase 1–2:**

Until Phase 3 is complete, stocktrading continues writing to Google Sheets.
Dashboard data is updated in SQLite by one of the following methods:

1. **Manual**: Periodically export Google Sheets → Excel → `import_excel.py`
2. **Automated (optional)**: Add SQLite writes to stocktrading side (early start on Phase 3)

### 10.4 Phase 3: Add Data Collection to uptrend-dashboard

**Purpose:** Implement functionality for uptrend-dashboard to fetch data from Finviz and write to SQLite. Eliminates manual Excel import and makes uptrend-dashboard a self-contained application.

**Approach:** No changes to stocktrading code. Stop scheduled execution (cron, etc.) of stocktrading's `uptrend_stocks.py` / `uptrend_count_sector.py`, transferring data collection responsibility to uptrend-dashboard.

**New Modules:**

| File | Description |
|------|-------------|
| `src/data_collector.py` | Fetch Count/Total from Finviz + write to SQLite |
| `collect.py` | CLI entry point (called from cron) |

#### data_collector.py Design

```python
def mask_secrets(text: str) -> str:
    """Mask known secrets (auth= query params) from URLs and exception messages (v3.2)"""
    ...

class DataCollector:
    """Fetches uptrend stock counts from Finviz screener and saves to SQLite"""

    def __init__(self, db_client: DBClient, config: CollectorConfig):
        ...

    def collect_all(self, date=None, dry_run=False) -> Dict[str, Tuple[int, int]]:
        """Fetch data for full market + all 11 sectors and save to DB
        dry_run=True skips DB writes (validation still runs)"""
        ...

    def collect_worksheet(self, worksheet, date=None, dry_run=False) -> Tuple[int, int]:
        """Fetch Count/Total for a single category and UPSERT to DB
        dry_run=True skips DB writes (validation still runs)"""
        ...

    def close(self) -> None:
        """Close the HTTP Session"""
        ...

    @staticmethod
    def _safe_http_error(exc) -> requests.HTTPError:
        """Create HTTPError with sanitized message (no URL leakage) (v3.2)"""
        ...

    def _validate_counts(self, worksheet, count, total) -> None:
        """Validate count/total integrity (negative values, count > total)"""
        ...

    def _fetch_stock_count(self, sector: str = None) -> Tuple[int, int]:
        """Fetch (uptrend_count, total_count) from Finviz API"""
        ...

    def _build_uptrend_url(self, sector: str = None) -> str:
        """Build uptrend screener URL"""
        ...

    def _build_total_url(self, sector: str = None) -> str:
        """Build total screener URL"""
        ...
```

**CollectorConfig:**

```python
@dataclass
class CollectorConfig:
    finviz_api_key: str           # From FINVIZ_API_KEY environment variable
    base_url: str = "https://elite.finviz.com"
    max_retries: int = 5          # Maximum retry count
    retry_delay: float = 2.0      # Initial retry delay (sec), exponential backoff with jitter
    request_interval: float = 2.0 # API request interval (sec, for rate limiting)
    http_timeout: float = 30.0    # HTTP timeout (sec)
```

**Finviz Screener Filters (ported from stocktrading's existing logic):**

Uptrend criteria:
```
cap=microover, sh_avgvol=o100, sh_price=o10,
ta_highlow52w=a30h, ta_perf2=4wup, ta_sma20=pa,
ta_sma200=pa, ta_sma50=sa200
```

Total criteria:
```
cap=microover, sh_avgvol=o100, sh_price=o10
```

Sector filter: Each worksheet name is added directly as a filter key (e.g., `sec_technology`).

**Fetch Flow:**

```
collect.py (CLI)
  │
  │ DataCollector.collect_all()
  │
  ├── _fetch_stock_count(sector=None)        → all count, total
  │     ├── GET uptrend URL → len(CSV) = uptrend_count
  │     └── GET total URL   → len(CSV) = total_count
  │
  ├── _fetch_stock_count(sector="sec_basicmaterials") → count, total
  │     :  (API calls at 1-sec intervals)
  ├── _fetch_stock_count(sector="sec_utilities")      → count, total
  │
  └── db_client.upsert_raw_data(date, worksheet, count, total) × 12
```

#### collect.py CLI Design

```bash
# Fetch all categories (default: --scope all = 161 worksheets)
python collect.py

# Scope: sectors only (12 worksheets)
python collect.py --scope sectors

# Scope: industries only (149 worksheets)
python collect.py --scope industries

# Specific category only
python collect.py --worksheet ind_semiconductors

# Specify date (for past data correction) — validates YYYY-MM-DD format
python collect.py --date 2026-02-07

# Dry run (runs collect_all/collect_worksheet with dry_run=True)
python collect.py --dry-run

# With debug logging
python collect.py --verbose
```

**`--worksheet` and `--scope` are mutually exclusive.** Specifying both causes exit 1.

**CollectScope enum (v4.0):**

| Value | Worksheets |
|-------|-----------|
| `SECTORS` | `["all"] + SECTORS` (12) |
| `INDUSTRIES` | `INDUSTRIES` (149) |
| `ALL` | `VALID_WORKSHEETS` (161) |

**CollectResult dataclass (v4.0):** Return value of `collect_all()`. Contains `succeeded` dict and `failed` list, with properties for sector/industry split (`sector_succeeded`, `industry_succeeded`, `sector_failed`, `industry_failed`).

**Exit codes (v4.0):**

| Scope | Code 0 | Code 1 | Code 2 |
|-------|--------|--------|--------|
| `--scope all` | All sectors succeeded (industry failures = warning) | All sectors failed | Partial sector failure, or all industries failed (sectors OK) |
| `--scope sectors` | All 12 succeeded | All failed | Partial failure |
| `--scope industries` | Any succeeded | All failed | — |
| `--worksheet` | Success | Failure | — |

**Scheduled execution (cron example):**

```bash
# Run every business day at 16:05 ET (after market close)
# ※ Business day detection is handled within the script (Alpaca calendar API or date-based)
5 16 * * 1-5 cd /path/to/uptrend-dashboard && /path/to/python collect.py >> logs/collect.log 2>&1
```

> Log format: `%(asctime)s %(levelname)s: %(message)s`. RotatingFileHandler is not needed (cron's redirection is sufficient).

**Business Day Detection:**

stocktrading uses Alpaca API's calendar, but to avoid Alpaca dependency in uptrend-dashboard, one of the following approaches is used:

| Approach | Pros | Cons |
|----------|------|------|
| A: Simple weekday check | No dependencies | Holidays trigger fetch attempts → possible 0 results |
| B: `exchange_calendars` package | Accurate NYSE holiday detection | Additional dependency |
| C: Run daily, skip UPSERT when data is 0 | Simplest | Unnecessary API calls |

→ **Recommended: C** (simplicity first. Finviz API calls are lightweight; skip UPSERT when result is 0)

**Additional Dependencies:**

| Package | Purpose |
|---------|---------|
| `requests` | HTTP requests to Finviz API |

> Only `requests` is added. Advanced features like circuit breakers from stocktrading's `FinvizClient` are not needed. Exponential backoff + jitter retry is sufficient.

**Retry/Error Handling Specification (v3.1):**

| Specification | Details |
|---------------|---------|
| Retry targets | 429, 500, 502, 503, 504, ConnectionError, Timeout |
| Backoff | Exponential backoff (2s → 4s → 8s …) + jitter (`delay * 0~25%`) |
| EmptyDataError | 200 + empty body → return empty DataFrame (prevent crash) |
| Data validation | `_validate_counts()`: validates negative values, count > total |
| Exception scope | `collect_all()` catches only `RequestException`, `ValueError`, `EmptyDataError` |
| Secret masking | `mask_secrets()` sanitizes `auth=` params in all logged exceptions (v3.2) |
| HTTP error sanitization | `_safe_http_error()` replaces HTTPError with URL-free message (v3.2) |
| Session management | `close()` method ensures `requests.Session` is properly closed |

**Test Plan (36 tests: Phase 3 initial 20 + v3.1 additional 12 + v3.2 additional 4):**

See test_data_collector.py section in "9.2 Test List" above.

### 10.5 Phase 4: Stop stocktrading Scheduled Execution / Archive Google Sheets

**Purpose:** Confirm that data collection responsibility has been fully transferred to uptrend-dashboard, and stop Uptrend-related scheduled execution on the stocktrading side.

**Prerequisites:** After Phase 3 completion, verify that uptrend-dashboard's `collect.py` has been running stably for a sufficient period (minimum 2 weeks recommended). Specifically:

- Daily trading day data is correctly recorded in SQLite
- stocktrading's Google Sheets data and uptrend-dashboard's SQLite data match on the same days

**Tasks:**

| # | Task | Target |
|---|------|--------|
| 1 | Stop scheduled execution (cron) of stocktrading's `uptrend_stocks.py` / `uptrend_count_sector.py` | stocktrading scheduler config |
| 2 | Change Google Sheets "US Market - Uptrend Stocks" to read-only (archive) | Google Sheets |
| 3 | **Leave stocktrading code as-is** (for future reference / fallback) | — |

> **Note:** stocktrading's `uptrend_stocks.py` functions `is_uptrend()` / `is_downtrend()` / `is_overbought()` are called from other trading scripts (e.g., `orb.py:187`). The Google Sheets dependency of these functions will be addressed separately as needed. Phase 4 scope is limited to stopping scheduled execution only; no modifications to existing trading logic.

**Architecture After Phase 4 Completion:**

```
                    ┌─────────────────────────────┐
                    │     uptrend-dashboard        │
                    │                              │
[Finviz] ─Scrape─→ │  collect.py (cron)           │
                    │     │                        │
                    │     ▼ Write                   │
                    │  data/uptrend.db (SQLite)    │
                    │     │                        │
                    │     ▼ Read                    │
                    │  app.py (Streamlit)          │
                    └─────────────────────────────┘

stocktrading: Uptrend scheduled execution stopped (code remains)
Google Sheets: Read-only archive
```

uptrend-dashboard becomes a self-contained application that handles "data collection → storage → visualization" independently.

---

## 11. Excel Import Specification

### 11.1 Supported Format

| Item | Specification |
|------|---------------|
| File format | `.xlsx` (downloaded from Google Sheets) |
| Sheet structure | Same as Google Sheets (sheet names correspond to category names) |
| Required columns | Date, Count, Total |
| Date format | `M/D/YYYY`, `YYYY-MM-DD`, Excel serial values, etc. (any format parseable by pandas) |
| Character encoding | UTF-8 |

### 11.2 Sheet Name Mapping

Conversion from Excel sheet names to worksheet values:

| Excel Sheet Name | worksheet Value |
|-----------------|----------------|
| `all` | `all` |
| `sec_basicmaterials` | `sec_basicmaterials` |
| ... | ... |

Sheets whose names don't match a worksheet value are skipped (warning logged).

### 11.3 Error Handling

| Case | Behavior |
|------|----------|
| Row with empty Date | Skip (warning logged) |
| Non-numeric Count/Total | Skip (warning logged) |
| Non-integer Count/Total (e.g., 1.5) | Drop row with warning (v3.2) |
| Negative Count/Total | Drop row with warning (v3.2) |
| Count > Total | Drop row with warning (v3.2) |
| Unknown sheet name | Skip (warning logged) |
| File not found | Exit with error |
| DB write failure | Transaction ROLLBACK, display error |

---

## 12. Startup and Operations Guide

### 12.1 Initial Setup

```bash
cd uptrend-dashboard
pip install -r requirements.txt

# Import historical data
# 1. Download Excel from Google Sheets
# 2. Load into SQLite with import_excel.py
python import_excel.py path/to/export.xlsx
```

### 12.2 Start Dashboard

```bash
streamlit run app.py
```

### 12.3 Run Tests

```bash
pytest tests/ -v
```

### 12.4 Add Data (Manual)

```bash
# Import new Excel file (existing data is overwritten via UPSERT)
python import_excel.py path/to/new_export.xlsx
```
