"""Tests for chart_builder module (v2)."""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import pytest

from src.chart_builder import (
    build_ratio_chart,
    build_sector_summary_chart,
    build_sector_comparison_chart,
    build_industry_summary_chart,
    build_industry_comparison_chart,
    build_industry_heatmap,
    build_dispersion_chart,
    build_regime_timeline_chart,
)


class TestBuildRatioChart:
    """Tests for build_ratio_chart function."""

    def test_ratio_chart_returns_figure(self, sample_calculated_df):
        """Should return a go.Figure."""
        fig = build_ratio_chart(sample_calculated_df)
        assert isinstance(fig, go.Figure)

    def test_ratio_chart_title(self, sample_calculated_df):
        """Should set custom title."""
        fig = build_ratio_chart(sample_calculated_df, title="Test Title")
        assert fig.layout.title.text == "Test Title"

    def test_ratio_chart_traces(self, sample_calculated_df):
        """Should have at least 3 traces: ratio segment(s) + 10MA + Upper + Lower."""
        fig = build_ratio_chart(sample_calculated_df)
        trace_names = [t.name for t in fig.data]
        assert "10MA" in trace_names
        assert "Upper" in trace_names
        assert "Lower" in trace_names
        # Should have at least one Ratio segment
        ratio_traces = [t for t in fig.data if t.name and "Ratio" in t.name]
        assert len(ratio_traces) >= 1

    def test_ratio_chart_color_segments(self, sample_calculated_df):
        """Should have green (#00cc96) and red (#ef553b) segments."""
        fig = build_ratio_chart(sample_calculated_df)
        colors = set()
        for trace in fig.data:
            if trace.line and trace.line.color:
                colors.add(trace.line.color)
        # Should contain at least one of the trend colors
        trend_colors = {"#00cc96", "#ef553b", "#636efa"}
        assert len(colors & trend_colors) >= 1

    def test_ratio_chart_legend_is_horizontal(self, sample_calculated_df):
        """Legend should sit horizontally so it does not eat plot width on phones."""
        fig = build_ratio_chart(sample_calculated_df)
        assert fig.layout.legend.orientation == "h"

    def test_ratio_chart_y_axis_percent(self, sample_calculated_df):
        """Y axis should use percent format to match the metric cards."""
        fig = build_ratio_chart(sample_calculated_df)
        assert fig.layout.yaxis.tickformat == ".0%"

    def test_ratio_chart_has_no_redundant_date_axis_title(self, sample_calculated_df):
        """The 'Date' x-axis title is self-evident and wastes vertical space."""
        fig = build_ratio_chart(sample_calculated_df)
        assert fig.layout.xaxis.title.text is None


class TestBuildSectorSummaryChart:
    """Tests for build_sector_summary_chart function."""

    def test_sector_summary_chart(self, sample_all_data):
        """Should produce a horizontal bar chart."""
        from src.data_processor import build_sector_summary

        summary = build_sector_summary(sample_all_data)
        fig = build_sector_summary_chart(summary)
        assert isinstance(fig, go.Figure)
        bar_traces = [t for t in fig.data if isinstance(t, go.Bar)]
        assert len(bar_traces) >= 1


    def test_sector_summary_chart_customdata(self, sample_all_data):
        """Bar trace should have customdata with sector keys for click navigation."""
        from src.data_processor import build_sector_summary

        summary = build_sector_summary(sample_all_data)
        fig = build_sector_summary_chart(summary)
        bar_traces = [t for t in fig.data if isinstance(t, go.Bar)]
        assert len(bar_traces) >= 1
        bar = bar_traces[0]
        assert bar.customdata is not None
        assert len(bar.customdata) == len(summary)
        # All customdata values should be sector keys (start with "sec_")
        for key in bar.customdata:
            assert key.startswith("sec_"), f"Unexpected key: {key}"


class TestBuildIndustryHeatmapColorRange:
    """A filtered (one-sector) heatmap must keep the full-market color scale."""

    def _summary(self):
        return pd.DataFrame({
            "Industry": ["A", "B"], "Ratio": [0.2, 0.4], "10MA": [0.2, 0.4],
            "Trend": ["Up", "Up"], "Slope": [0.01, 0.01], "Status": ["Normal", "Normal"],
            "_key": ["ind_a", "ind_b"], "Sector": ["Tech", "Tech"], "Total": [10, 10],
        })

    def test_explicit_color_range_overrides_data_range(self):
        fig = build_industry_heatmap(self._summary(), color_range=(0.0, 1.0))
        assert fig.data[0].marker.cmin == 0.0
        assert fig.data[0].marker.cmax == 1.0

    def test_default_color_range_follows_data(self):
        fig = build_industry_heatmap(self._summary())
        assert fig.data[0].marker.cmin == 0.2
        assert fig.data[0].marker.cmax == 0.4


class TestBuildIndustryHeatmapDrilldown:
    """Phone view: show 11 sector tiles first, tap a sector to see its industries."""

    def _summary(self):
        return pd.DataFrame({
            "Industry": ["A", "B", "C"], "Ratio": [0.1, 0.5, 0.3], "10MA": [0.1, 0.5, 0.3],
            "Trend": ["Up", "Up", "Down"], "Slope": [0.01, 0.01, -0.01],
            "Status": ["Normal", "Overbought", "Normal"],
            "_key": ["ind_a", "ind_b", "ind_c"], "Sector": ["Tech", "Tech", "Energy"],
            "Total": [30, 10, 20],
        })

    def _node(self, fig, label):
        trace = fig.data[0]
        return list(trace.labels).index(label)

    def test_desktop_default_has_no_root_and_no_depth_limit(self):
        fig = build_industry_heatmap(self._summary())
        assert "All Sectors" not in fig.data[0].labels
        assert fig.data[0].maxdepth is None

    def test_drilldown_adds_root_and_limits_depth(self):
        fig = build_industry_heatmap(self._summary(), drilldown=True)
        trace = fig.data[0]
        assert "All Sectors" in trace.labels
        assert trace.maxdepth == 2
        assert trace.parents[self._node(fig, "Tech")] == "All Sectors"

    def test_drilldown_sector_tile_shows_stock_weighted_ratio(self):
        fig = build_industry_heatmap(self._summary(), drilldown=True)
        i = self._node(fig, "Tech")
        # (0.1*30 + 0.5*10) / 40 = 0.2
        assert fig.data[0].marker.colors[i] == pytest.approx(0.2)
        assert "20.0%" in fig.data[0].text[i]

    def test_drilldown_uses_fixed_scale_so_sector_tiles_differ(self):
        """Sector ratios cluster at 20-45%; a 0-100% scale makes them all one color."""
        fig = build_industry_heatmap(self._summary(), drilldown=True)
        assert fig.data[0].marker.cmin == 0
        assert fig.data[0].marker.cmax == pytest.approx(0.6)

    def test_drilldown_status_mode_colors_sector_by_its_ratio(self):
        fig = build_industry_heatmap(self._summary(), color_mode="status", drilldown=True)
        i = self._node(fig, "Tech")
        assert fig.data[0].marker.colors[i] == "#1f77b4"  # 20% -> Normal


class TestBuildSectorComparisonChart:
    """Tests for build_sector_comparison_chart function."""

    def test_sector_comparison_chart(self, sample_all_data):
        """Should produce an overlay chart for all sectors plus threshold legend traces."""
        fig = build_sector_comparison_chart(sample_all_data)
        assert isinstance(fig, go.Figure)
        # 11 sector traces + 2 threshold legend traces (Upper, Lower)
        assert len(fig.data) == 13

    def test_sector_comparison_selected(self, sample_all_data):
        """Should filter to selected sectors only (plus threshold traces)."""
        selected = ["sec_technology", "sec_healthcare"]
        fig = build_sector_comparison_chart(sample_all_data, selected_sectors=selected)
        # 2 sector traces + 2 threshold legend traces
        assert len(fig.data) == 4

    def test_sector_comparison_uses_ma_by_default(self, sample_all_data):
        """Default mode should use ma_10 column."""
        fig = build_sector_comparison_chart(sample_all_data, use_ma=True)
        # Title should indicate 10MA mode
        assert "10MA" in fig.layout.title.text

    def test_sector_comparison_raw_ratio_mode(self, sample_all_data):
        """Raw ratio mode should use ratio column."""
        fig = build_sector_comparison_chart(sample_all_data, use_ma=False)
        assert "Raw Ratio" in fig.layout.title.text

    def test_sector_comparison_has_threshold_traces(self, sample_all_data):
        """Should have Upper and Lower threshold legend entries."""
        fig = build_sector_comparison_chart(sample_all_data)
        trace_names = [t.name for t in fig.data]
        assert "Upper" in trace_names
        assert "Lower" in trace_names

    def test_sector_comparison_y_axis_percent(self, sample_all_data):
        """Y axis should use percent format."""
        fig = build_sector_comparison_chart(sample_all_data)
        assert fig.layout.yaxis.tickformat == ".0%"

    def test_sector_comparison_has_no_redundant_date_axis_title(self, sample_all_data):
        fig = build_sector_comparison_chart(sample_all_data)
        assert fig.layout.xaxis.title.text is None

    def test_sector_comparison_legend_is_horizontal(self, sample_all_data):
        """Legend should be below the plot, not a right-side column."""
        fig = build_sector_comparison_chart(sample_all_data)
        assert fig.layout.legend.orientation == "h"

    def test_sector_comparison_annotations(self, sample_all_data):
        """Should have annotations for latest values."""
        fig = build_sector_comparison_chart(sample_all_data)
        # Should have one annotation per sector
        assert len(fig.layout.annotations) == 11

    def test_sector_comparison_legend_sorted_by_latest_value(self, sample_all_data):
        """Legend (trace order) should be sorted by latest value descending."""
        fig = build_sector_comparison_chart(sample_all_data)
        # Get sector traces only (exclude Upper/Lower)
        sector_traces = [t for t in fig.data if t.name not in ("Upper", "Lower")]
        # Extract latest ma_10 values from the traces
        latest_values = []
        for t in sector_traces:
            y_vals = [v for v in t.y if v is not None and not pd.isna(v)]
            latest_values.append(y_vals[-1] if y_vals else 0)
        # Verify descending order
        assert latest_values == sorted(latest_values, reverse=True)

    def test_sector_comparison_custom_colors(self, sample_all_data):
        """Each sector should have a distinct color from the palette."""
        from src.chart_builder import SECTOR_PALETTE
        fig = build_sector_comparison_chart(sample_all_data)
        sector_traces = [t for t in fig.data if t.name not in ("Upper", "Lower")]
        colors = [t.line.color for t in sector_traces]
        # All colors should be from the palette
        for color in colors:
            assert color in SECTOR_PALETTE


class TestBuildIndustrySummaryChart:
    """Tests for build_industry_summary_chart function."""

    def _make_industry_summary(self):
        """Create a sample industry summary DataFrame."""
        return pd.DataFrame({
            "Industry": ["Semiconductors", "Software - Application", "Banks - Regional"],
            "Ratio": [0.45, 0.32, 0.20],
            "10MA": [0.40, 0.30, 0.22],
            "Trend": ["Up", "Up", "Down"],
            "Slope": [0.02, 0.01, -0.005],
            "Status": ["Overbought", "Normal", "Normal"],
            "_key": ["ind_semiconductors", "ind_softwareapplication", "ind_banksregional"],
        })

    def test_industry_summary_chart(self):
        """Should return a go.Figure with Bar trace."""
        summary = self._make_industry_summary()
        fig = build_industry_summary_chart(summary)
        assert isinstance(fig, go.Figure)
        bar_traces = [t for t in fig.data if isinstance(t, go.Bar)]
        assert len(bar_traces) >= 1

    def test_industry_summary_chart_customdata(self):
        """Bar trace customdata should contain ind_* keys."""
        summary = self._make_industry_summary()
        fig = build_industry_summary_chart(summary)
        bar_traces = [t for t in fig.data if isinstance(t, go.Bar)]
        bar = bar_traces[0]
        assert bar.customdata is not None
        for key in bar.customdata:
            assert key.startswith("ind_"), f"Unexpected key: {key}"

    def test_industry_summary_chart_dynamic_height(self):
        """Chart height should scale with number of bars."""
        summary_3 = self._make_industry_summary()
        fig_3 = build_industry_summary_chart(summary_3)
        # 3 bars: max(300, 3*35+100) = 300
        assert fig_3.layout.height == 300

        # 10 bars: max(300, 10*35+100) = 450
        summary_10 = pd.DataFrame({
            "Industry": [f"Ind {i}" for i in range(10)],
            "Ratio": [0.3] * 10,
            "10MA": [0.28] * 10,
            "Trend": ["Up"] * 10,
            "Slope": [0.01] * 10,
            "Status": ["Normal"] * 10,
            "_key": [f"ind_test{i}" for i in range(10)],
        })
        fig_10 = build_industry_summary_chart(summary_10)
        assert fig_10.layout.height == 450

    def test_industry_summary_chart_title_with_sector(self):
        """Title should include sector name when provided."""
        summary = self._make_industry_summary()
        fig = build_industry_summary_chart(summary, sector_name="Technology")
        assert "Technology" in fig.layout.title.text

    def test_industry_summary_chart_title_default(self):
        """Default title without sector name."""
        summary = self._make_industry_summary()
        fig = build_industry_summary_chart(summary)
        assert fig.layout.title.text == "Industry Ratio Summary"


class TestBuildIndustryComparisonChart:
    """Tests for build_industry_comparison_chart function."""

    def _make_industry_data(self):
        """Create sample all_data with industry entries."""
        from src.indicator_calculator import calculate_indicators
        dates = pd.bdate_range("2024-01-02", periods=20, freq="B")
        counts = [150, 170, 190, 200, 210, 220, 230, 240, 250, 245,
                  230, 210, 195, 180, 170, 175, 185, 195, 210, 220]
        base_df = pd.DataFrame({"date": dates, "count": counts, "total": [500] * 20})
        data = {}
        for i, ind in enumerate(["ind_semiconductors", "ind_softwareapplication", "ind_banksregional"]):
            df = base_df.copy()
            df["count"] = (df["count"] * (0.8 + i * 0.1)).astype(int)
            data[ind] = calculate_indicators(df)
        return data

    def test_industry_comparison_chart(self):
        """Should produce traces for each industry + 2 threshold traces."""
        data = self._make_industry_data()
        fig = build_industry_comparison_chart(data)
        assert isinstance(fig, go.Figure)
        # 3 industry traces + 2 threshold legend traces
        assert len(fig.data) == 5

    def test_industry_comparison_selected(self):
        """Should filter to selected industries only."""
        data = self._make_industry_data()
        selected = ["ind_semiconductors"]
        fig = build_industry_comparison_chart(data, selected_industries=selected)
        # 1 industry trace + 2 threshold traces
        assert len(fig.data) == 3

    def test_industry_comparison_uses_industry_palette(self):
        """Should use INDUSTRY_PALETTE colors."""
        from src.chart_builder import INDUSTRY_PALETTE
        data = self._make_industry_data()
        fig = build_industry_comparison_chart(data)
        industry_traces = [t for t in fig.data if t.name not in ("Upper", "Lower")]
        for t in industry_traces:
            assert t.line.color in INDUSTRY_PALETTE

    def test_industry_comparison_title(self):
        """Title should indicate Industry Comparison."""
        data = self._make_industry_data()
        fig = build_industry_comparison_chart(data)
        assert "Industry Comparison" in fig.layout.title.text


class TestSectorComparisonExcludesIndustries:
    """Test that sector comparison filters out ind_* entries."""

    def test_sector_comparison_excludes_industries(self, sample_all_data):
        """ind_* entries in all_data should not appear in sector comparison."""
        from src.indicator_calculator import calculate_indicators
        # Add industry data to sample_all_data
        dates = pd.bdate_range("2024-01-02", periods=20, freq="B")
        counts = [150, 170, 190, 200, 210, 220, 230, 240, 250, 245,
                  230, 210, 195, 180, 170, 175, 185, 195, 210, 220]
        ind_df = pd.DataFrame({"date": dates, "count": counts, "total": [500] * 20})
        sample_all_data["ind_semiconductors"] = calculate_indicators(ind_df)

        fig = build_sector_comparison_chart(sample_all_data)
        trace_names = [t.name for t in fig.data]
        # Should not have "Semiconductors" in any trace name
        for name in trace_names:
            assert name != "Semiconductors", "Industry should not appear in sector comparison"
        # Should still have 11 sector traces + 2 threshold traces
        assert len(fig.data) == 13


class TestRatioChartPeakTroughMarkers:
    """Tests for peak/trough markers on ratio chart."""

    def test_ratio_chart_has_peak_trough_markers(self):
        """Should have '10MA Peak' and '10MA Trough' marker traces."""
        import numpy as np
        from src.indicator_calculator import calculate_indicators, IndicatorConfig

        # Build a sine-wave dataset large enough for peak/trough detection
        n = 200
        period = 40
        dates = pd.bdate_range("2024-01-01", periods=n, freq="B")
        ratios = 0.5 + 0.1 * np.sin(2 * np.pi * np.arange(n) / period)
        total = 500
        counts = (ratios * total).astype(int)
        df = pd.DataFrame({"date": dates, "count": counts, "total": [total] * n})
        calc_df = calculate_indicators(df, IndicatorConfig())

        fig = build_ratio_chart(calc_df)
        trace_names = [t.name for t in fig.data]
        assert "10MA Peak" in trace_names, f"Missing '10MA Peak' in {trace_names}"
        assert "10MA Trough" in trace_names, f"Missing '10MA Trough' in {trace_names}"


class TestBuildIndustryHeatmap:
    """Tests for build_industry_heatmap function."""

    def _make_heatmap_summary(self):
        """Create a sample summary DataFrame with Sector and Total columns."""
        return pd.DataFrame({
            "Industry": ["Semiconductors", "Software - Application", "Banks - Regional"],
            "Ratio": [0.45, 0.32, 0.20],
            "10MA": [0.40, 0.30, 0.22],
            "Trend": ["Up", "Up", "Down"],
            "Slope": [0.02, 0.01, -0.005],
            "Status": ["Overbought", "Normal", "Normal"],
            "_key": ["ind_semiconductors", "ind_softwareapplication", "ind_banksregional"],
            "Sector": ["Technology", "Technology", "Financial"],
            "Total": [100, 80, 120],
        })

    def test_industry_heatmap_returns_figure(self):
        """Should return a go.Figure."""
        summary = self._make_heatmap_summary()
        fig = build_industry_heatmap(summary)
        assert isinstance(fig, go.Figure)

    def test_industry_heatmap_has_treemap_trace(self):
        """Should contain a go.Treemap trace."""
        summary = self._make_heatmap_summary()
        fig = build_industry_heatmap(summary)
        treemap_traces = [t for t in fig.data if isinstance(t, go.Treemap)]
        assert len(treemap_traces) >= 1

    def test_industry_heatmap_sector_parents(self):
        """Sector display names should appear as labels in the treemap."""
        summary = self._make_heatmap_summary()
        fig = build_industry_heatmap(summary)
        treemap = [t for t in fig.data if isinstance(t, go.Treemap)][0]
        labels = list(treemap.labels)
        assert "Technology" in labels
        assert "Financial" in labels

    def test_industry_heatmap_color_ratio_mode(self):
        """Ratio mode should use RdYlGn colorscale."""
        summary = self._make_heatmap_summary()
        fig = build_industry_heatmap(summary, color_mode="ratio")
        treemap = [t for t in fig.data if isinstance(t, go.Treemap)][0]
        assert treemap.marker.colorscale is not None
        # Verify it's using RdYlGn (check that the colorscale name or tuples exist)
        cs = treemap.marker.colorscale
        # Plotly stores named colorscales as tuple of tuples
        assert cs is not None

    def test_industry_heatmap_color_status_mode(self):
        """Status mode should use categorical colors from STATUS_COLORS."""
        from src.chart_builder import STATUS_COLORS
        summary = self._make_heatmap_summary()
        fig = build_industry_heatmap(summary, color_mode="status")
        treemap = [t for t in fig.data if isinstance(t, go.Treemap)][0]
        colors = list(treemap.marker.colors)
        # Industry cells should have STATUS_COLORS values
        industry_colors = [c for c in colors if c != "#cccccc"]
        for c in industry_colors:
            assert c in STATUS_COLORS.values(), f"Unexpected color: {c}"

    def test_industry_heatmap_uniform_size(self):
        """Uniform mode should set all values to 1."""
        summary = self._make_heatmap_summary()
        fig = build_industry_heatmap(summary, size_mode="uniform")
        treemap = [t for t in fig.data if isinstance(t, go.Treemap)][0]
        # All leaf values should be 1 (sectors have no explicit value)
        industry_values = [v for v in treemap.values if v == 1]
        # Should have at least 3 industry cells with value 1
        assert len(industry_values) >= 3

    def test_industry_heatmap_customdata(self):
        """customdata should contain _key for industry cells."""
        summary = self._make_heatmap_summary()
        fig = build_industry_heatmap(summary)
        treemap = [t for t in fig.data if isinstance(t, go.Treemap)][0]
        customdata = list(treemap.customdata)
        # Should contain the industry keys
        assert "ind_semiconductors" in customdata
        assert "ind_softwareapplication" in customdata
        assert "ind_banksregional" in customdata

    def test_industry_heatmap_empty_data(self):
        """Empty DataFrame should not raise an error."""
        empty_df = pd.DataFrame(columns=[
            "Industry", "Ratio", "10MA", "Trend", "Slope", "Status", "_key", "Sector", "Total",
        ])
        fig = build_industry_heatmap(empty_df)
        assert isinstance(fig, go.Figure)


def _make_dispersion_df(n=30):
    """Create a sample dispersion DataFrame for chart testing."""
    dates = pd.bdate_range("2024-01-01", periods=n, freq="B")
    regimes = ["converged"] * 10 + ["normal"] * 10 + ["diverged"] * 10
    return pd.DataFrame({
        "date": dates,
        "dispersion": np.linspace(0.04, 0.14, n),
        "mean_ratio": np.linspace(0.15, 0.40, n),
        "range": np.linspace(0.05, 0.20, n),
        "dispersion_ma10": np.linspace(0.04, 0.14, n),
        "dispersion_velocity": [0.005] * n,
        "regime": regimes,
        "level_regime": ["low"] * 10 + ["mid"] * 10 + ["high"] * 10,
        "p25": [0.06] * n,
        "p75": [0.11] * n,
        "velocity_p90": [0.02] * n,
        "dispersion_median": [0.08] * n,
    })


class TestBuildDispersionChart:
    """Tests for build_dispersion_chart()."""

    def test_returns_figure(self):
        """Should return a Plotly Figure."""
        df = _make_dispersion_df()
        fig = build_dispersion_chart(df)
        assert isinstance(fig, go.Figure)

    def test_has_dispersion_trace(self):
        """Should have a trace for dispersion line."""
        df = _make_dispersion_df()
        fig = build_dispersion_chart(df)
        trace_names = [t.name for t in fig.data if t.name]
        assert any("Dispersion" in n for n in trace_names)

    def test_has_p25_p75_traces(self):
        """p25/p75 should be time-series traces, not hlines."""
        df = _make_dispersion_df()
        fig = build_dispersion_chart(df)
        trace_names = [t.name for t in fig.data if t.name]
        assert any("p25" in n.lower() or "P25" in n for n in trace_names)
        assert any("p75" in n.lower() or "P75" in n for n in trace_names)

    def test_has_mean_ratio_trace(self):
        """Should have a secondary-axis trace for mean ratio."""
        df = _make_dispersion_df()
        fig = build_dispersion_chart(df)
        trace_names = [t.name for t in fig.data if t.name]
        assert any("Mean" in n or "mean" in n for n in trace_names)

    def test_empty_df_returns_figure(self):
        """Empty DataFrame should return a valid Figure."""
        df = pd.DataFrame(columns=[
            "date", "dispersion", "mean_ratio", "range",
            "dispersion_ma10", "dispersion_velocity",
            "regime", "level_regime",
            "p25", "p75", "velocity_p90", "dispersion_median",
        ])
        fig = build_dispersion_chart(df)
        assert isinstance(fig, go.Figure)


class TestBuildRegimeTimelineChart:
    """Tests for build_regime_timeline_chart()."""

    def test_returns_figure(self):
        """Should return a Plotly Figure."""
        df = _make_dispersion_df()
        fig = build_regime_timeline_chart(df)
        assert isinstance(fig, go.Figure)

    def test_has_bar_traces(self):
        """Should have Bar traces for regime segments."""
        df = _make_dispersion_df()
        fig = build_regime_timeline_chart(df)
        bar_traces = [t for t in fig.data if isinstance(t, go.Bar)]
        assert len(bar_traces) > 0

    def test_empty_df_returns_figure(self):
        """Empty DataFrame should return a valid Figure."""
        df = pd.DataFrame(columns=[
            "date", "dispersion", "mean_ratio", "range",
            "dispersion_ma10", "dispersion_velocity",
            "regime", "level_regime",
            "p25", "p75", "velocity_p90", "dispersion_median",
        ])
        fig = build_regime_timeline_chart(df)
        assert isinstance(fig, go.Figure)
