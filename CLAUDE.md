# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

US Market Uptrend Dashboard — A Streamlit-based sector and industry-level uptrend analysis dashboard. Tracks 161 worksheets (1 market + 11 sectors + 149 industries). Uses SQLite (not DuckDB) as the backend, computing indicators on-the-fly from raw data (count, total).

## Commands

```bash
# Run dashboard
streamlit run app.py

# Run all tests
pytest tests/ -v

# Run single test file
pytest tests/test_indicator_calculator.py -v

# Run single test
pytest tests/test_indicator_calculator.py::TestCalculateIndicators::test_calculate_indicators_full -v

# Import data from Excel
python import_excel.py path/to/export.xlsx
python import_excel.py path/to/export.xlsx --dry-run    # preview only
python import_excel.py path/to/export.xlsx --sheet all   # specific sheets
```

## Architecture

```
Presentation (app.py, pages/)
    ↓
Chart Layer (src/chart_builder.py) — Plotly figures with color-coded trends
    ↓
Processing (src/data_processor.py) — status aggregation, sector summaries
    ↓
Calculation (src/indicator_calculator.py) — ratio, 10MA, slope, trend, peak/trough
    ↓
Loading (src/data_loader.py) — load + cache + CSV→DB bootstrap
    ↓
Data Access (src/db_client.py) — SQLite CRUD, UPSERT via INSERT OR REPLACE
    ↓
Storage (data/uptrend.db) — uptrend_raw table, PK: (date, worksheet)
```

### Key Design Decisions

- **Single Source of Truth**: Only raw data (count, total) is stored in the DB. ratio, MA, slope, and trend are all computed at read time by `calculate_indicators()`
- **Caching**: `@st.cache_data(ttl=3600)` caches data for 1 hour. Manual clear via the sidebar Refresh button
- **UPSERT**: Idempotent data import via `INSERT OR REPLACE`

### DB Schema

```sql
uptrend_raw (date TEXT, worksheet TEXT, count INTEGER, total INTEGER)
-- PK: (date, worksheet)
-- worksheets: 'all' + 11 sectors (sec_*) + 149 industries (ind_*)
-- 161 rows/day
```

### Indicator Thresholds

- Upper (Overbought): 0.37
- Lower (Oversold): 0.097
- MA period: 10
- Peak detection: scipy.signal.find_peaks (distance=20, prominence=0.015)

### Multi-Page Structure

`app.py` is a router: pages are registered explicitly via `st.navigation()` from `src/navigation.py` (`PAGE_SPECS`). A new page must be added there (a test checks every `pages/*.py` is registered). Each page calls `inject_mobile_css()` and renders charts via `show_chart()` from `src/mobile_ui.py`.
- `pages/0_Uptrend_Ratio.py` — Full market overview (default page, menu "Uptrend Ratio")
- `pages/1_Sector_Detail.py` — Individual sector deep dive + industry drilldown
- `pages/2_Sector_Comparison.py` — Multi-sector overlay comparison
- `pages/3_Industry_Detail.py` — Individual industry analysis
- `pages/4_Industry_Comparison.py` — Multi-industry overlay (within/cross-sector)

## Testing

pytest + pytest-mock. Tests use `tmp_path`-based temporary DBs instead of the real DB. Shared fixtures are defined in `tests/conftest.py`:
- `tmp_db` / `db_client` — temporary DB
- `sample_raw_df` — 20-row synthetic data
- `sample_calculated_df` — DataFrame with indicators pre-calculated
- `sample_all_data` — data for all 12 worksheets

## Development Rules

- **TDD**: Use the `/tdd-developer` skill when implementing code, following the Red→Green→Refactor cycle
- **Design Doc Sync (MANDATORY)**: Every code change must be reflected in `docs/design.md` within the same commit or session. This includes revision history, module signatures, column definitions, screen layouts, test lists, and dependency versions. Never leave design docs out of sync with code

## Adding New Features

**New indicator**: Add calculation to `indicator_calculator.py` → add column to `calculate_indicators()` → visualize in `chart_builder.py` → add tests

**New page**: Create `pages/N_Name.py`, following existing page patterns (`load_data` cache, `inject_mobile_css()`, `show_chart()`), and register it in `src/navigation.py`
