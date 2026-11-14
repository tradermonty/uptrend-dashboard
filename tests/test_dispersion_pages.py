"""Render the real dispersion consumers using synthetic loader data."""

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src.constants import SECTORS
from src.indicator_calculator import calculate_indicators

ROOT = Path(__file__).resolve().parents[1]


def page_data(state):
    dates = pd.bdate_range("2026-01-05", periods=30)
    raw = pd.DataFrame({"date": dates, "count": [50] * 30, "total": [500] * 30})
    data = {key: calculate_indicators(raw) for key in ["all", *SECTORS]}
    if state == "partial":
        data[SECTORS[-1]].loc[29, "ma_10"] = np.nan
    elif state == "never_complete":
        data.pop(SECTORS[-1])
    elif state == "all_missing":
        for frame in data.values():
            frame["ma_10"] = np.nan
    return data


def render_page(filename, state, tmp_path):
    # Register both real pages: standalone AppTest lacks page_link navigation
    # metadata. A temporary entrypoint keeps production scripts unmodified.
    (tmp_path / "pages").symlink_to(ROOT / "pages", target_is_directory=True)
    other = "2_Sector_Comparison.py" if filename.startswith("6_") else "6_Dispersion_Monitor.py"
    entrypoint = tmp_path / "app.py"
    entrypoint.write_text(
        "import streamlit as st\n"
        f"st.navigation([st.Page('pages/{filename}', default=True), "
        f"st.Page('pages/{other}')]).run()\n"
    )
    with patch("src.data_loader.cached_load_sector_data", return_value=page_data(state)):
        return AppTest.from_file(entrypoint, default_timeout=20).run()


@pytest.mark.parametrize("filename", ["6_Dispersion_Monitor.py", "2_Sector_Comparison.py"])
@pytest.mark.parametrize("state,count", [("partial", 10), ("never_complete", 10), ("all_missing", 0)])
def test_incomplete_latest_does_not_display_current_advice(filename, state, count, tmp_path):
    app = render_page(filename, state, tmp_path)
    assert not app.exception
    text = "\n".join(x.value for x in [*app.caption, *app.warning, *app.markdown])
    assert f"{count}/11" in text
    assert "2026-02-13" in text  # latest observed date, even if no values are usable
    assert not app.success
    assert not app.error
    assert "CAPITULATION ACTIVE" not in text
    assert "**Current:" not in text
    assert "`CURRENT`" not in text
    if state == "partial":
        assert "2026-02-12" in text  # last complete observation is explicitly historical
    if filename.startswith("6_") and state == "partial":
        assert len(app.get("plotly_chart")) == 2  # history remains available
        assert not app.metric  # no obsolete current metrics


@pytest.mark.parametrize("filename", ["6_Dispersion_Monitor.py", "2_Sector_Comparison.py"])
def test_complete_latest_displays_asof_and_current_regime(filename, tmp_path):
    app = render_page(filename, "complete", tmp_path)
    assert not app.exception
    text = "\n".join(x.value for x in [*app.caption, *app.markdown, *app.error])
    assert "11/11" in text
    assert "2026-02-13" in text
    if filename.startswith("6_"):
        assert "CAPITULATION ACTIVE" in text
        assert len(app.metric) == 4
    else:
        assert "σ=" in text
