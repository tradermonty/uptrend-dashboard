"""Tests for mobile UI helpers."""

import plotly.graph_objects as go
import pytest

from src.mobile_ui import (
    PLOTLY_CONFIG,
    apply_mobile_layout,
    build_mobile_css,
    display_years,
    is_mobile_user_agent,
    mobile_columns,
    treemap_html,
    MOBILE_CONSTITUENT_COLUMNS,
)


class TestIsMobileUserAgent:
    @pytest.mark.parametrize(
        "ua",
        [
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148",
            "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/120.0 Mobile Safari/537.36",
            "Mozilla/5.0 (iPod touch; CPU iPhone OS 17_0 like Mac OS X)",
        ],
    )
    def test_phone_user_agents_are_mobile(self, ua):
        assert is_mobile_user_agent(ua) is True

    @pytest.mark.parametrize(
        "ua",
        [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Gecko/20100101 Firefox/121.0",
            "",
            None,
        ],
    )
    def test_desktop_or_missing_user_agents_are_not_mobile(self, ua):
        assert is_mobile_user_agent(ua) is False


class TestBuildMobileCss:
    def test_css_is_scoped_to_small_screens(self):
        css = build_mobile_css()
        assert "@media (max-width: 640px)" in css

    def test_css_keeps_metrics_in_two_columns(self):
        css = build_mobile_css()
        assert 'stHorizontalBlock"]:has([data-testid="stMetric"])' in css
        assert "calc(50% - 0.5rem)" in css

    def test_css_is_wrapped_in_style_tag(self):
        css = build_mobile_css()
        assert css.strip().startswith("<style>")
        assert css.strip().endswith("</style>")


class TestPlotlyConfig:
    def test_hides_plotly_logo(self):
        assert PLOTLY_CONFIG["displaylogo"] is False

    def test_removes_rarely_used_buttons(self):
        removed = PLOTLY_CONFIG["modeBarButtonsToRemove"]
        for button in ("lasso2d", "select2d", "zoomIn2d", "zoomOut2d"):
            assert button in removed


class TestApplyMobileLayout:
    def _fig(self):
        fig = go.Figure(go.Scatter(x=[1, 2], y=[1, 2]))
        fig.update_layout(height=500, title="T")
        return fig

    def test_disables_drag_so_page_can_scroll(self):
        fig = apply_mobile_layout(self._fig())
        assert fig.layout.dragmode is False

    def test_tightens_margins(self):
        fig = apply_mobile_layout(self._fig())
        assert fig.layout.margin.l <= 10
        assert fig.layout.margin.r <= 10

    def test_shrinks_fonts(self):
        fig = apply_mobile_layout(self._fig())
        assert fig.layout.font.size <= 11

    def test_keeps_height_when_not_given(self):
        fig = apply_mobile_layout(self._fig())
        assert fig.layout.height == 500

    def test_overrides_height_when_given(self):
        fig = apply_mobile_layout(self._fig(), height=380)
        assert fig.layout.height == 380

    def test_returns_same_figure(self):
        fig = self._fig()
        assert apply_mobile_layout(fig) is fig

    def test_untitled_figure_stays_untitled(self):
        """Setting only a title font made Plotly render the text 'undefined'."""
        fig = go.Figure(go.Scatter(x=[1], y=[1]))
        apply_mobile_layout(fig)
        assert fig.layout.title.text is None
        assert fig.layout.title.font.size is None

    def test_legend_is_horizontal(self):
        fig = apply_mobile_layout(self._fig())
        assert fig.layout.legend.orientation == "h"

    def test_axes_use_automargin_so_tick_labels_are_not_clipped(self):
        fig = apply_mobile_layout(self._fig())
        assert fig.layout.xaxis.automargin is True
        assert fig.layout.yaxis.automargin is True

    def test_axis_titles_are_removed_to_widen_plot(self):
        fig = self._fig()
        fig.update_layout(xaxis_title="Date", yaxis_title="Ratio")
        apply_mobile_layout(fig)
        assert fig.layout.xaxis.title.text is None
        assert fig.layout.yaxis.title.text is None

    def test_x_tick_labels_stay_horizontal(self):
        fig = apply_mobile_layout(self._fig())
        assert fig.layout.xaxis.tickangle == 0

    def test_keeps_annotations_by_default(self):
        fig = self._fig()
        fig.add_annotation(x=1, y=1, text="A")
        apply_mobile_layout(fig)
        assert len(fig.layout.annotations) == 1

    def test_hides_annotations_when_requested(self):
        fig = self._fig()
        fig.add_annotation(x=1, y=1, text="A")
        apply_mobile_layout(fig, hide_annotations=True)
        assert len(fig.layout.annotations) == 0

    def test_treemap_without_scale_gets_no_colorbar(self):
        """Explicit-color treemaps (stock level) drew an empty 0-6 colorbar box."""
        fig = go.Figure(go.Treemap(labels=["a"], parents=[""], values=[1],
                                   marker=dict(colors=["#ff0000"])))
        apply_mobile_layout(fig)
        assert fig.data[0].marker.colorbar.orientation is None

    def test_treemap_only_figure_gets_no_stray_axes(self):
        """Axis settings on a treemap-only figure made Plotly draw an empty 0-6 axis."""
        fig = go.Figure(go.Treemap(labels=["a"], parents=[""], values=[1]))
        apply_mobile_layout(fig)
        assert fig.layout.xaxis.nticks is None
        assert fig.layout.yaxis.automargin is None

    def test_treemap_text_is_readable_size(self):
        fig = go.Figure(go.Treemap(labels=["a"], parents=[""], values=[1]))
        apply_mobile_layout(fig)
        assert fig.data[0].textfont.size >= 12

    def test_treemap_colorbar_becomes_horizontal(self):
        fig = go.Figure(
            go.Treemap(labels=["a"], parents=[""], values=[1],
                       marker=dict(colors=[0.5], colorscale="RdYlGn", showscale=True))
        )
        apply_mobile_layout(fig)
        assert fig.data[0].marker.colorbar.orientation == "h"


class TestTreemapHtml:
    def _fig(self):
        return go.Figure(go.Treemap(
            ids=["root", "AAA|ind_x"], labels=["root", "AAA"], parents=["", "root"],
            values=[1, 1], customdata=["", "https://finviz.com/quote.ashx?t=AAA&p=w"],
        ))

    def test_leaf_tap_opens_url_instead_of_zooming(self):
        html = treemap_html(self._fig(), height=500)
        assert "plotly_treemapclick" in html
        assert "window.open" in html
        assert "return false" in html  # cancels Plotly's zoom into the leaf

    def test_only_finviz_urls_are_opened(self):
        html = treemap_html(self._fig(), height=500)
        assert "https://finviz.com/" in html

    def test_height_and_no_plotly_logo(self):
        html = treemap_html(self._fig(), height=480)
        assert "480" in html
        assert '"displaylogo": false' in html


class TestDisplayYears:
    def test_phone_shows_one_year(self):
        assert display_years(is_mobile=True) == 1

    def test_desktop_keeps_two_years(self):
        assert display_years(is_mobile=False) == 2


class TestMobileColumns:
    def test_keeps_only_compact_columns_on_mobile(self):
        cols = ["Sector", "Ratio", "10MA", "Trend", "Slope", "Status"]
        assert mobile_columns(cols, is_mobile=True) == ["Sector", "Ratio", "Trend", "Status"]

    def test_returns_none_on_desktop(self):
        assert mobile_columns(["Sector", "Ratio"], is_mobile=False) is None

    def test_custom_keep_set_for_constituent_table(self):
        cols = ["Ticker", "Company", "Uptrend", "Market Cap ($M)", "Change", "Perf Week", "Perf YTD"]
        assert mobile_columns(cols, is_mobile=True, keep=MOBILE_CONSTITUENT_COLUMNS) == [
            "Ticker", "Uptrend", "Change", "Perf YTD",
        ]

    def test_preserves_original_order_and_skips_missing(self):
        cols = ["Industry", "Sector", "Ratio", "Status"]
        assert mobile_columns(cols, is_mobile=True) == ["Industry", "Sector", "Ratio", "Status"]
