# US Market Uptrend Stock Ratio Dashboard

Streamlit + Plotly dashboard for visualizing US market uptrend stock ratios. Data is collected from Finviz Elite and stored in SQLite.

**Live App**: https://uptrend-dashboard.streamlit.app/

## Features

- **Full Market Overview**: Ratio time series with 10MA, Upper/Lower thresholds, peak/trough markers
- **Sector Detail**: Individual sector analysis with trend signals + industry drilldown
- **Sector Comparison**: Overlay multiple sector ratios (10MA smoothed) with threshold annotations
- **Industry Detail**: Individual industry analysis with parent sector context
- **Industry Comparison**: Compare industries within a sector or across sectors (max 15)
- **Auto-refresh**: 1-hour cache with manual refresh button
- **Self-Contained Data Collection**: Finviz Elite CSV scraper with cron-ready CLI (161 worksheets)
- **CSV Export for LLM Access**: Automated CSV generation via GitHub Actions, accessible via raw URL

## Setup

### Prerequisites

- Python 3.9+
- Finviz Elite API key (for data collection)

### Installation

```bash
git clone https://github.com/tradermonty/uptrend-dashboard.git
cd uptrend-dashboard
pip install -r requirements.txt
```

### Configuration

```bash
cp .env.sample .env
# Edit .env and set FINVIZ_API_KEY
```

### Data Collection

```bash
# Collect all worksheets (161: market + sectors + industries)
python collect.py

# Collect sectors only (12 worksheets)
python collect.py --scope sectors

# Collect industries only (149 worksheets)
python collect.py --scope industries

# Dry run (fetch without writing to DB)
python collect.py --dry-run

# Specific date
python collect.py --date 2026-02-07

# Single worksheet
python collect.py --worksheet ind_semiconductors

# Import from Excel (legacy data migration)
python import_excel.py path/to/export.xlsx

# Export CSV files (auto-runs in GitHub Actions after collection)
python export_csv.py --verbose
```

### Run Dashboard

```bash
streamlit run app.py
```

Development containers launch with CORS and XSRF protections enabled. Keep forwarded port 8501 private and use the [protected-preview setup and verification guide](docs/operations/protected-preview.md) if a preview connection needs diagnosis.

### Run Tests

```bash
pytest tests/ -v
```

## Project Structure

```
uptrend-dashboard/
├── .streamlit/config.toml          # Theme settings
├── src/
│   ├── constants.py                # Sectors, thresholds, shared constants
│   ├── db_client.py                # SQLite CRUD (UPSERT via INSERT OR REPLACE)
│   ├── data_loader.py              # Data loading, caching, CSV→DB bootstrap
│   ├── indicator_calculator.py     # Ratio, 10MA, slope, trend, peak/trough
│   ├── data_processor.py           # Status aggregation, sector summaries
│   ├── data_collector.py           # Finviz Elite CSV scraper
│   └── chart_builder.py            # Plotly chart generation
├── tests/
│   ├── conftest.py                 # Shared fixtures (tmp_db, sample data)
│   ├── test_db_client.py
│   ├── test_indicator_calculator.py
│   ├── test_data_processor.py
│   ├── test_chart_builder.py
│   ├── test_data_collector.py
│   ├── test_export_csv.py
│   ├── test_import_excel.py
│   └── test_integration.py
├── pages/
│   ├── 1_Sector_Detail.py          # Sector detail + industry drilldown
│   ├── 2_Sector_Comparison.py      # Sector comparison page
│   ├── 3_Industry_Detail.py        # Industry detail page
│   └── 4_Industry_Comparison.py    # Industry comparison page
├── app.py                          # Main page
├── collect.py                      # Data collection CLI (cron-ready)
├── export_csv.py                   # CSV export CLI (auto-runs in CI)
├── import_excel.py                 # Excel import tool
├── data/
│   ├── uptrend.db                  # SQLite database
│   ├── uptrend_ratio_timeseries.csv # All worksheets timeseries (auto-generated)
│   ├── sector_summary.csv          # Sector summary snapshot (auto-generated)
│   └── industry_summary.csv        # Industry summary snapshot (auto-generated)
└── docs/design.md                  # Design document
```

## Uptrend Definition

A stock is classified as "uptrend" when it meets **all** of the following conditions on Finviz screener:

| Condition | Description |
|-----------|-------------|
| Price > $10 | Penny stocks excluded |
| Avg Volume > 100K | Sufficient liquidity |
| Market Cap > $50M | Micro-cap and above |
| Price > SMA20 | Short-term uptrend |
| Price > SMA200 | Long-term uptrend |
| SMA50 > SMA200 | Golden cross (bullish structure) |
| 52W High/Low > 30% above Low | Recovering from bottom |
| 4-Week Performance: Up | Recent momentum positive |

The **uptrend ratio** = (stocks meeting all conditions) / (stocks meeting base filters only: price, volume, market cap). This ratio is tracked daily per sector to gauge market breadth.

## Data Source

Finviz Elite CSV export API. Collects uptrend count and total count for:
- `all` -- Full market aggregate
- `sec_*` -- 11 sector worksheets (Basic Materials, Technology, Financial, etc.)
- `ind_*` -- 149 industry worksheets (Semiconductors, Software Application, Banks Regional, etc.)

Data is stored in SQLite (`data/uptrend.db`) with raw counts (count, total). Indicators (ratio, 10MA, slope, trend) are calculated on-the-fly at read time. Total: 161 worksheets collected daily.

## CSV Access (for LLM / Programmatic Use)

After each data collection, CSV files are auto-generated and committed to git. Access via GitHub raw URL:

| File | URL | Description |
|------|-----|-------------|
| Timeseries | `https://raw.githubusercontent.com/tradermonty/uptrend-dashboard/main/data/uptrend_ratio_timeseries.csv` | All 161 worksheets with `worksheet, date, count, total, ratio, ma_10, slope, trend` |
| Sector Summary | `https://raw.githubusercontent.com/tradermonty/uptrend-dashboard/main/data/sector_summary.csv` | Latest snapshot: `Sector, Ratio, 10MA, Trend, Slope, Status` |
| Industry Summary | `https://raw.githubusercontent.com/tradermonty/uptrend-dashboard/main/data/industry_summary.csv` | Latest snapshot: `Industry, Ratio, 10MA, Trend, Slope, Status` |

- Values are raw decimals (0.29, not 29%)
- Dates formatted as `YYYY-MM-DD`
- NaN exported as empty string
