"""Issue #12: real-page selectors must honor pending drilldown intent."""

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from src.constants import SECTORS
from src.indicator_calculator import calculate_indicators

ROOT = Path(__file__).resolve().parents[1]
PAGES = ["1_Sector_Detail.py", "3_Industry_Detail.py", "5_Industry_Heatmap.py"]


@pytest.fixture
def loaded_data(mocker):
    dates = pd.bdate_range("2024-01-02", periods=30)
    def calculated(count):
        return calculate_indicators(pd.DataFrame({"date": dates, "count": count, "total": 500}))
    data = {key: calculated(100) for key in ["all", *SECTORS]}
    data.update({"sec_healthcare": calculated(150), "sec_technology": calculated(250),
                 "ind_biotechnology": calculated(50), "ind_semiconductors": calculated(200),
                 "ind_banksregional": calculated(100)})
    mocker.patch("src.data_loader.cached_load_all_data", return_value=data)
    return data


def detail_app(default="3_Industry_Detail.py"):
    # Start from the actual multipage entrypoint so registration and page
    # revisits use the production context across supported AppTest versions.
    app = AppTest.from_file(ROOT / "app.py", default_timeout=20).run()
    return app.switch_page(f"pages/{default}")


def selector(app, label):
    return next(item for item in app.selectbox if item.label == label)


def selected_label(app, label):
    box = selector(app, label)
    return box.format_func(box.value)


def select_label(app, label, value):
    box = selector(app, label)
    return box.select_index(box.options.index(value)).run()


def visit(app, number):
    path = "app.py" if number == "0" else next(f"pages/{p}" for p in PAGES if p.startswith(number))
    return app.switch_page(path).run()


def assert_industry(app, sector, industry, ratio):
    assert not app.exception
    assert selected_label(app, "Filter by Sector") == sector
    assert selected_label(app, "Select Industry") == industry
    assert f"Parent Sector: {sector}" in [x.value for x in app.caption]
    assert next(m.value for m in app.metric if m.label == "Ratio") == ratio
    chart = json.loads(app.get("plotly_chart")[0].proto.spec)
    assert chart["layout"]["title"]["text"] == f"{industry} Uptrend Ratio"
    assert any(x.proto.label == f"Download {industry} Time Series" for x in app.get("download_button"))
    assert "selected_industry" not in app.session_state


def test_healthcare_filter_cannot_swallow_semiconductor_target(loaded_data, mocker):
    download = mocker.spy(st, "download_button")
    app = detail_app().run()
    select_label(app, "Filter by Sector", "Healthcare")
    app.session_state["selected_industry"] = "ind_semiconductors"
    app.run()
    assert_industry(app, "Technology", "Semiconductors", "40.0%")
    assert download.call_args.args[2] == "ind_semiconductors_timeseries.csv"
    assert "0.4" in download.call_args.args[1]


def test_repeated_cross_sector_intents_and_manual_filters(loaded_data):
    app = detail_app().run()
    for target, parent, label, ratio in [
        ("ind_semiconductors", "Technology", "Semiconductors", "40.0%"),
        ("ind_biotechnology", "Healthcare", "Biotechnology", "10.0%"),
        ("ind_semiconductors", "Technology", "Semiconductors", "40.0%"),
        ("ind_semiconductors", "Technology", "Semiconductors", "40.0%"),
    ]:
        app.session_state["selected_industry"] = target
        app.run()
        assert_industry(app, parent, label, ratio)
    select_label(app, "Filter by Sector", "Healthcare")
    select_label(app, "Select Industry", "Biotechnology")
    app.run()
    assert_industry(app, "Healthcare", "Biotechnology", "10.0%")
    select_label(app, "Filter by Sector", "All Sectors")
    select_label(app, "Select Industry", "Semiconductors")
    app.run()
    assert selected_label(app, "Filter by Sector") == "All Sectors"
    assert selected_label(app, "Select Industry") == "Semiconductors"


def test_sector_intent_overrides_existing_manual_widget(loaded_data):
    app = detail_app("1_Sector_Detail.py").run()
    select_label(app, "Select Sector", "Healthcare")
    for target, label, ratio in [("sec_technology", "Technology", "50.0%"),
                                  ("sec_healthcare", "Healthcare", "30.0%"),
                                  ("sec_technology", "Technology", "50.0%")]:
        app.session_state["selected_sector"] = target
        app.run()
        assert not app.exception
        assert selected_label(app, "Select Sector") == label
        assert next(m.value for m in app.metric if m.label == "Ratio") == ratio
        assert "selected_sector" not in app.session_state
    select_label(app, "Select Sector", "Healthcare")
    app.run()
    assert selected_label(app, "Select Sector") == "Healthcare"


@pytest.mark.parametrize("invalid", ["ind_unknown", ["ind_semiconductors"]])
def test_invalid_target_warns_and_preserves_valid_manual_choice(loaded_data, invalid):
    app = detail_app().run()
    select_label(app, "Filter by Sector", "Healthcare")
    select_label(app, "Select Industry", "Biotechnology")
    app.session_state["selected_industry"] = invalid
    app.run()
    assert not app.exception
    assert selected_label(app, "Select Industry") == "Biotechnology"
    assert "selected_industry" not in app.session_state
    assert any("Invalid industry navigation target" in x.value for x in app.warning)


def test_configured_target_without_data_is_selected_explicitly(loaded_data):
    loaded_data.pop("ind_semiconductors")
    app = detail_app().run()
    select_label(app, "Filter by Sector", "Healthcare")
    app.session_state["selected_industry"] = "ind_semiconductors"
    app.run()
    assert not app.exception
    assert selected_label(app, "Filter by Sector") == "Technology"
    assert selected_label(app, "Select Industry") == "Semiconductors"
    assert any("No data available for Semiconductors" in x.value for x in app.warning)
    assert not app.metric


def test_stale_widget_values_recover_before_construction(loaded_data):
    app = detail_app()
    app.session_state["industry_detail_sector_filter"] = "sec_removed"
    app.session_state["industry_detail_industry"] = "ind_removed"
    app.run()
    assert not app.exception
    assert app.session_state["industry_detail_sector_filter"] is None
    assert app.session_state["industry_detail_industry"] != "ind_removed"


@pytest.mark.parametrize("route", ["chart", "table", "heatmap"])
def test_real_producer_navigation_to_already_visited_industry(loaded_data, mocker, route):
    app = detail_app().run()
    select_label(app, "Filter by Sector", "Healthcare")
    original_plot = st.plotly_chart
    original_table = st.dataframe
    trigger = {"armed": False}
    def plot(*args, **kwargs):
        if route == "chart" and kwargs.get("key") == "industry_summary_chart" and trigger["armed"]:
            trigger["armed"] = False
            return SimpleNamespace(selection=SimpleNamespace(points=[{"customdata": "ind_semiconductors"}]))
        return original_plot(*args, **kwargs)
    def table(*args, **kwargs):
        expected = "heatmap_industry_table" if route == "heatmap" else "industry_table"
        if route in ("table", "heatmap") and kwargs.get("key") == expected and trigger["armed"]:
            trigger["armed"] = False
            shown = args[0].data  # Styler's actual rendered source table
            position = shown["Industry"].tolist().index("Semiconductors")
            return SimpleNamespace(selection=SimpleNamespace(rows=[position]))
        return original_table(*args, **kwargs)
    mocker.patch("streamlit.plotly_chart", side_effect=plot)
    mocker.patch("streamlit.dataframe", side_effect=table)
    for _ in range(2):
        select_label(app, "Filter by Sector", "Healthcare")
        app.session_state["selected_sector"] = "sec_technology"
        trigger["armed"] = True
        visit(app, "5" if route == "heatmap" else "1")
        assert not trigger["armed"]
        assert_industry(app, "Technology", "Semiconductors", "40.0%")


def test_empty_data_names_requested_target_without_showing_other_metrics(loaded_data):
    loaded_data.clear()
    app = detail_app()
    app.session_state["selected_industry"] = "ind_semiconductors"
    app.run()
    assert not app.exception
    assert selected_label(app, "Filter by Sector") == "Technology"
    assert selected_label(app, "Select Industry") == "Semiconductors"
    assert any("No data available for Semiconductors" in x.value for x in app.warning)
    assert not app.metric
    assert "selected_industry" not in app.session_state


@pytest.mark.parametrize("invalid", ["sec_unknown", ["sec_technology"]])
def test_invalid_sector_intent_preserves_valid_manual_choice(loaded_data, invalid):
    app = detail_app("1_Sector_Detail.py").run()
    select_label(app, "Select Sector", "Healthcare")
    app.session_state["selected_sector"] = invalid
    app.run()
    assert not app.exception
    assert selected_label(app, "Select Sector") == "Healthcare"
    assert any("Invalid sector navigation target" in x.value for x in app.warning)
    assert "selected_sector" not in app.session_state


def test_stale_sector_widget_recovers(loaded_data):
    app = detail_app("1_Sector_Detail.py")
    app.session_state["sector_detail_sector"] = "sec_removed"
    app.run()
    assert not app.exception
    assert app.session_state["sector_detail_sector"] == SECTORS[0]


def test_sector_without_data_is_selected_instead_of_another_sector(loaded_data):
    loaded_data.pop("sec_technology")
    app = detail_app("1_Sector_Detail.py")
    app.session_state["selected_sector"] = "sec_technology"
    app.run()
    assert not app.exception
    assert selected_label(app, "Select Sector") == "Technology"
    assert any("No data available for Technology" in x.value for x in app.warning)
    assert not app.metric


@pytest.mark.parametrize("route", ["chart", "table"])
def test_overview_producers_navigate_to_visited_sector(loaded_data, mocker, route):
    app = detail_app("1_Sector_Detail.py").run()
    original_plot = st.plotly_chart
    original_table = st.dataframe
    trigger = {"armed": False}
    def plot(*args, **kwargs):
        if route == "chart" and kwargs.get("key") == "sector_summary" and trigger["armed"]:
            trigger["armed"] = False
            return SimpleNamespace(selection=SimpleNamespace(points=[{"customdata": "sec_technology"}]))
        return original_plot(*args, **kwargs)
    def table(*args, **kwargs):
        if route == "table" and kwargs.get("key") == "sector_table" and trigger["armed"]:
            trigger["armed"] = False
            position = args[0].data["Sector"].tolist().index("Technology")
            return SimpleNamespace(selection=SimpleNamespace(rows=[position]))
        return original_table(*args, **kwargs)
    mocker.patch("streamlit.plotly_chart", side_effect=plot)
    mocker.patch("streamlit.dataframe", side_effect=table)
    for _ in range(2):
        select_label(app, "Select Sector", "Healthcare")
        trigger["armed"] = True
        visit(app, "0")
        assert not trigger["armed"]
        assert not app.exception
        assert selected_label(app, "Select Sector") == "Technology"
        assert next(m.value for m in app.metric if m.label == "Ratio") == "50.0%"
        assert "selected_sector" not in app.session_state
