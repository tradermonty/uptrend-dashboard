"""Issue #5: incomplete sector observations cannot become market signals."""

import numpy as np
import pandas as pd
import pytest

from src.constants import SECTORS
from src.indicator_calculator import calculate_sector_dispersion, detect_dispersion_signals
from src.data_processor import prepare_dispersion_csv
from src.chart_builder import build_dispersion_chart, build_regime_timeline_chart

METRICS = [
    "dispersion", "mean_ratio", "range", "dispersion_ma10",
    "dispersion_velocity", "regime", "level_regime", "p25", "p75",
    "velocity_p90", "dispersion_median",
]
COVERAGE = ["sector_count", "expected_sector_count", "coverage_complete"]


def sector_history(n=90):
    dates = pd.bdate_range("2026-01-05", periods=n)
    sigma = .08 + np.arange(n) * .0005
    z = np.linspace(-1, 1, len(SECTORS))
    z /= z.std()
    return {key: pd.DataFrame({"date": dates, "ma_10": .4 + sigma * z[i]})
            for i, key in enumerate(SECTORS)}


@pytest.mark.parametrize("n_sectors", [1, 2, 10])
def test_sparse_sector_sets_have_coverage_but_no_metrics(n_sectors):
    data = dict(list(sector_history().items())[:n_sectors])
    result = calculate_sector_dispersion(data)
    assert result["sector_count"].eq(n_sectors).all()
    assert result["expected_sector_count"].eq(len(SECTORS)).all()
    assert not result["coverage_complete"].any()
    assert result[METRICS].isna().all().all()
    assert detect_dispersion_signals(result) == []


@pytest.mark.parametrize("valid_count", [0, 1, 2, 10])
@pytest.mark.parametrize("row", [35, 89])
def test_incomplete_interior_and_latest_rows_are_invalid(valid_count, row):
    data = sector_history()
    for key in SECTORS[valid_count:]:
        data[key].loc[row, "ma_10"] = np.nan
    result = calculate_sector_dispersion(data)
    assert len(result) == 90
    assert result.iloc[row]["sector_count"] == valid_count
    assert not result.iloc[row]["coverage_complete"]
    assert result.iloc[row][METRICS].isna().all()
    if row == 89:
        assert detect_dispersion_signals(result) == []


def test_unknown_sector_cannot_replace_missing_expected_sector():
    data = sector_history()
    data["sec_unknown"] = data.pop(SECTORS[-1])
    result = calculate_sector_dispersion(data)
    assert result["sector_count"].eq(10).all()
    assert result[METRICS].isna().all().all()


def test_missing_ma_column_retains_later_observed_date():
    data = sector_history(10)
    later = pd.Timestamp("2026-04-01")
    data[SECTORS[-1]] = pd.DataFrame({"date": [later]})
    result = calculate_sector_dispersion(data)
    assert result.iloc[-1]["date"] == later
    assert result.iloc[-1]["sector_count"] == 0
    assert result.iloc[-1][METRICS].isna().all()
    assert detect_dispersion_signals(result) == []


@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
def test_nonfinite_observed_history_retains_dates_without_metrics(value):
    data = sector_history(5)
    for frame in data.values():
        frame["ma_10"] = value
    result = calculate_sector_dispersion(data)
    assert len(result) == 5
    assert result["sector_count"].eq(0).all()
    assert result[METRICS].isna().all().all()


def test_consecutive_partial_tail_does_not_reuse_old_signals():
    data = sector_history()
    data[SECTORS[-1]].loc[87:, "ma_10"] = np.nan
    result = calculate_sector_dispersion(data)
    assert len(result) == 90
    assert result.iloc[-3:][METRICS].isna().all().all()
    assert result.loc[result.coverage_complete, "date"].iloc[-1] == data[SECTORS[0]].date.iloc[86]
    assert detect_dispersion_signals(result) == []


def test_gap_is_excluded_before_statistics_and_velocity_windows():
    data = sector_history()
    for key in SECTORS[2:]:
        data[key].loc[65, "ma_10"] = np.nan
    # Values remaining on the incomplete date must have no influence.
    a = calculate_sector_dispersion(data)
    for key in SECTORS[:2]:
        data[key].loc[65, "ma_10"] = 10000
    b = calculate_sector_dispersion(data)
    pd.testing.assert_frame_equal(a, b)
    expected = a.dispersion.dropna()
    assert a.loc[66, "p25"] == pytest.approx(expected.loc[:66].quantile(.25))
    assert a.loc[66, "p75"] == pytest.approx(expected.loc[:66].quantile(.75))
    assert a.loc[65:74, "dispersion_ma10"].isna().all()
    assert a.loc[75, "dispersion_ma10"] == pytest.approx(a.dispersion.loc[66:75].mean())
    assert a.loc[65:68, "dispersion_velocity"].isna().all()
    assert a.loc[69, "dispersion_velocity"] == pytest.approx(abs(a.loc[69, "dispersion"] - a.loc[66, "dispersion"]))
    valid_vel = a.dispersion_velocity.dropna()
    assert a.loc[80, "velocity_p90"] == pytest.approx(valid_vel.loc[:80].quantile(.9))


def test_complete_data_preserves_reference_statistics():
    data = sector_history()
    result = calculate_sector_dispersion(data)
    matrix = pd.DataFrame({k: v.ma_10 for k, v in data.items()})
    std = matrix.std(axis=1, ddof=0)
    np.testing.assert_allclose(result.dispersion, std)
    np.testing.assert_allclose(result.mean_ratio, matrix.mean(axis=1))
    np.testing.assert_allclose(result.range, matrix.max(axis=1) - matrix.min(axis=1))
    np.testing.assert_allclose(result.dispersion_ma10, std.rolling(10).mean(), equal_nan=True)
    np.testing.assert_allclose(result.dispersion_velocity, std.diff(3).abs(), equal_nan=True)
    np.testing.assert_allclose(result.p25, std.expanding(min_periods=60).quantile(.25), equal_nan=True)
    assert result.coverage_complete.all()
    assert len(detect_dispersion_signals(result)) == 3


def test_missing_coverage_metadata_cannot_generate_signals():
    result = calculate_sector_dispersion(sector_history())
    assert detect_dispersion_signals(result.drop(columns=COVERAGE, errors="ignore")) == []


def test_partial_day_resets_confirmation_and_is_prefix_invariant():
    data = sector_history(10)
    z = np.linspace(-1, 1, len(SECTORS))
    z /= z.std()
    sigma = np.array([.08, .14, .14, .14, .14, .14, .14, .14, .14, .14])
    for i, key in enumerate(SECTORS):
        data[key]["ma_10"] = .4 + sigma * z[i]
    data[SECTORS[-1]].loc[2, "ma_10"] = np.nan
    full = calculate_sector_dispersion(data)
    assert pd.isna(full.loc[2, "regime"])
    assert full.loc[3:4, "regime"].eq("normal").all()
    assert full.loc[5, "regime"] == "diverged"
    for n in [2, 3, 4, 6, 9]:
        prefix = calculate_sector_dispersion({k: v.iloc[:n] for k, v in data.items()})
        pd.testing.assert_frame_equal(prefix, full.iloc[:n])


def test_csv_exposes_coverage_and_retains_invalid_tail():
    data = sector_history(5)
    data[SECTORS[-1]].loc[4, "ma_10"] = np.nan
    result = prepare_dispersion_csv(calculate_sector_dispersion(data))
    assert list(result.columns) == ["date", "dispersion", "mean_ratio", "range", "regime", "level_regime", *COVERAGE]
    assert len(result) == 5
    assert result.iloc[-1]["sector_count"] == 10
    assert not result.iloc[-1]["coverage_complete"]
    assert result.iloc[-1][["dispersion", "regime"]].isna().all()


def test_chart_bands_do_not_bridge_missing_observation():
    result = calculate_sector_dispersion(sector_history(30))
    gap_date = result.loc[15, "date"]
    result.loc[15, METRICS] = np.nan
    result.loc[15, "coverage_complete"] = False
    # Force the same regime on both sides, making dropna-induced bridging observable.
    result.loc[result.coverage_complete, "regime"] = "converged"
    fig = build_dispersion_chart(result)
    assert len(fig.layout.shapes) == 2
    assert pd.Timestamp(fig.layout.shapes[0].x1) < gap_date
    assert pd.Timestamp(fig.layout.shapes[1].x0) > gap_date
    for shape in fig.layout.shapes:
        assert not (pd.Timestamp(shape.x0) < gap_date < pd.Timestamp(shape.x1))
    timeline = build_regime_timeline_chart(result)
    assert len(timeline.data) == 2
    for trace in timeline.data:
        start = pd.Timestamp(trace.base[0])
        end = start + pd.Timedelta(milliseconds=trace.x[0])
        assert not (start <= gap_date < end)


def test_real_db_export_retains_incomplete_latest_observation(tmp_path):
    from export_csv import export_csv
    from src.db_client import DBClient

    db = DBClient(str(tmp_path / "source.db"))
    dates = pd.bdate_range("2026-01-05", periods=30)
    for key in SECTORS:
        observed = dates[:-1] if key == SECTORS[-1] else dates
        db.upsert_bulk(pd.DataFrame({
            "date": observed.strftime("%Y-%m-%d"), "worksheet": key,
            "count": [50] * len(observed), "total": [500] * len(observed),
        }))
    output = tmp_path / "output"
    output.mkdir()
    metadata = export_csv(db.db_path, str(output))
    result = pd.read_csv(metadata["dispersion"]["path"])
    assert metadata["dispersion"]["rows"] == len(dates)
    assert result.iloc[-1]["date"] == "2026-02-13"
    assert result.iloc[-1]["sector_count"] == 10
    assert not result.iloc[-1]["coverage_complete"]
    assert result.iloc[-1][["dispersion", "regime", "level_regime"]].isna().all()
    assert result.iloc[-2]["coverage_complete"]


@pytest.mark.parametrize("missing,dtype", [(pd.NA, "object"), (None, "object"), (pd.NA, "Float64")])
def test_object_and_nullable_missing_values_retain_diagnostic_dates(missing, dtype):
    data = sector_history(5)
    data[SECTORS[-1]]["ma_10"] = pd.Series([missing] * 5, dtype=dtype)
    result = calculate_sector_dispersion(data)
    assert result.date.tolist() == data[SECTORS[0]].date.tolist()
    assert result.sector_count.eq(10).all()
    assert not result.coverage_complete.any()
    assert result[METRICS].isna().all().all()
    assert detect_dispersion_signals(result) == []
