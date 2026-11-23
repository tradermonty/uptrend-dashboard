"""Integration tests for the uptrend dashboard pipeline.

Tests the end-to-end flow: Excel -> DB -> Calculation -> Chart.
"""

import sqlite3

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import pytest

from src.db_client import DBClient
from src.indicator_calculator import calculate_indicators
from src.data_processor import get_current_status, build_sector_summary
from src.chart_builder import build_ratio_chart, build_sector_summary_chart


class TestExcelToChartPipeline:
    """End-to-end test: Excel -> DB -> Calculation -> Chart."""

    def test_full_pipeline(self, tmp_path):
        """Full pipeline from Excel to chart should produce valid output."""
        from import_excel import import_excel

        # 1. Create a test Excel file
        filepath = tmp_path / "test_export.xlsx"
        dates = pd.bdate_range("2024-01-02", periods=20, freq="B")
        counts = [
            150, 170, 190, 200, 210,
            220, 230, 240, 250, 245,
            230, 210, 195, 180, 170,
            175, 185, 195, 210, 220,
        ]
        with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
            df = pd.DataFrame({
                "Date": dates.strftime("%m/%d/%Y"),
                "Count": counts,
                "Total": [500] * 20,
            })
            df.to_excel(writer, sheet_name="all", index=False)
            df_tech = pd.DataFrame({
                "Date": dates.strftime("%m/%d/%Y"),
                "Count": [int(c * 0.3) for c in counts],
                "Total": [100] * 20,
            })
            df_tech.to_excel(writer, sheet_name="sec_technology", index=False)

        # 2. Import to DB
        db_path = str(tmp_path / "test.db")
        result = import_excel(str(filepath), db_path=db_path)
        assert result["all"] == 20
        assert result["sec_technology"] == 20

        # 3. Read from DB and calculate indicators
        client = DBClient(db_path)
        raw_all = client.fetch_raw_data("all")
        assert len(raw_all) == 20

        calculated = calculate_indicators(raw_all)
        assert "ratio" in calculated.columns
        assert "ma_10" in calculated.columns
        assert "slope" in calculated.columns
        assert len(calculated) == 20

        # 4. Generate status and chart
        status = get_current_status(calculated)
        assert "ratio" in status
        assert "trend" in status

        fig = build_ratio_chart(calculated, title="Integration Test")
        assert isinstance(fig, go.Figure)
        assert fig.layout.title.text == "Integration Test"

    def test_multi_sector_pipeline(self, tmp_path):
        """Multi-sector pipeline should produce valid summary and comparison."""
        from import_excel import import_excel

        filepath = tmp_path / "multi_sector.xlsx"
        dates = pd.bdate_range("2024-01-02", periods=20, freq="B")
        base_counts = [
            150, 170, 190, 200, 210,
            220, 230, 240, 250, 245,
            230, 210, 195, 180, 170,
            175, 185, 195, 210, 220,
        ]

        sectors = ["all", "sec_technology", "sec_healthcare", "sec_financial"]
        with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
            for i, sector in enumerate(sectors):
                factor = 0.8 + i * 0.1
                df = pd.DataFrame({
                    "Date": dates.strftime("%m/%d/%Y"),
                    "Count": [int(c * factor) for c in base_counts],
                    "Total": [500] * 20,
                })
                df.to_excel(writer, sheet_name=sector, index=False)

        db_path = str(tmp_path / "multi.db")
        import_excel(str(filepath), db_path=db_path)

        client = DBClient(db_path)
        all_data = {}
        for sector in sectors:
            raw = client.fetch_raw_data(sector)
            all_data[sector] = calculate_indicators(raw)

        # Build sector summary
        summary = build_sector_summary(all_data)
        assert len(summary) == 3  # Excludes "all"
        assert set(summary.columns) == {"Sector", "Ratio", "10MA", "Trend", "Slope", "Status", "_key", "As Of", "Stale"}

        # Build summary chart
        fig = build_sector_summary_chart(summary)
        assert isinstance(fig, go.Figure)

    def test_empty_db_pipeline(self, tmp_path):
        """Pipeline with empty DB should handle gracefully."""
        db_path = str(tmp_path / "empty.db")
        client = DBClient(db_path)

        raw = client.fetch_raw_data("all")
        assert raw.empty

        calculated = calculate_indicators(raw)
        assert calculated.empty
        assert "ratio" in calculated.columns

        status = get_current_status(calculated)
        assert status["ratio"] == 0.0

        summary = build_sector_summary({})
        assert len(summary) == 0
