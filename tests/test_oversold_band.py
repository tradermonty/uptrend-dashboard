"""Deeper pink where the market ratio is below the Oversold level (v6.7)."""

import pandas as pd

from src.chart_builder import DOWNTREND_BAND_NAME, OVERSOLD_BAND_NAME, build_market_chart


def _df(ratios, slopes=None, lower=0.097):
    dates = pd.bdate_range("2024-01-02", periods=len(ratios))
    return pd.DataFrame({
        "date": dates, "ratio": ratios, "ma_10": ratios,
        "slope": slopes if slopes is not None else [0.1] * len(ratios),
        "upper": 0.37, "lower": lower, "is_peak": False, "is_trough": False,
    })


def _prices(dates):
    return pd.DataFrame({"date": pd.to_datetime(dates), "close": [100.0 + i for i in range(len(dates))]})


def _bands(df, name=OVERSOLD_BAND_NAME):
    fig = build_market_chart(df, _prices(df["date"]), title="T")
    return fig, [s for s in fig.layout.shapes if s.name == name]


def test_one_band_per_oversold_run_in_each_panel():
    _, bands = _bands(_df([0.2, 0.09, 0.08, 0.2, 0.05, 0.2]))
    assert len(bands) == 4
    assert sorted(b.yref for b in bands) == ["y domain", "y domain", "y2 domain", "y2 domain"]


def test_band_runs_from_first_oversold_day_to_the_next_day():
    df = _df([0.2, 0.09, 0.08, 0.2])
    _, bands = _bands(df)
    assert pd.Timestamp(bands[0].x0) == df["date"][1]
    assert pd.Timestamp(bands[0].x1) == df["date"][3]


def test_at_the_level_is_not_oversold():
    """Same rule as the Status card: oversold means ratio < lower."""
    _, bands = _bands(_df([0.2, 0.097, 0.2]))
    assert bands == []


def test_oversold_is_shaded_even_while_the_10ma_rises():
    _, bands = _bands(_df([0.2, 0.05, 0.2], slopes=[0.1, 0.1, 0.1]))
    assert len(bands) == 2


def test_oversold_band_is_deeper_than_the_downtrend_band():
    df = _df([0.2, 0.15, 0.05, 0.2], slopes=[0.1, -0.1, -0.1, 0.1])
    fig, oversold = _bands(df)
    down = [s for s in fig.layout.shapes if s.name == DOWNTREND_BAND_NAME]
    alpha = lambda c: float(c.rstrip(")").split(",")[-1])  # noqa: E731
    assert alpha(oversold[0].fillcolor) > alpha(down[0].fillcolor)
    assert oversold[0].layer == "below" and oversold[0].line.width == 0


def test_the_bands_never_overlap_so_the_deep_pink_is_one_shade():
    """Oversold sessions get only the deep band, even inside a downtrend."""
    df = _df([0.2, 0.15, 0.05, 0.08, 0.15, 0.2], slopes=[0.1, -0.1, -0.1, -0.1, -0.1, 0.1])
    fig, oversold = _bands(df)
    down = [s for s in fig.layout.shapes if s.name == DOWNTREND_BAND_NAME]
    spans = lambda bands: sorted({(pd.Timestamp(b.x0), pd.Timestamp(b.x1)) for b in bands})  # noqa: E731
    d = df["date"]
    assert spans(down) == [(d[1], d[2]), (d[4], d[5])]
    assert spans(oversold) == [(d[2], d[4])]


def test_blank_lower_uses_the_default_level():
    df = _df([0.2, 0.05, 0.2])
    df.loc[1, "lower"] = float("nan")
    _, bands = _bands(df)
    assert len(bands) == 2


def test_blank_ratio_is_not_oversold():
    _, bands = _bands(_df([0.2, float("nan"), 0.2]))
    assert bands == []


def test_a_single_oversold_last_day_is_still_visible():
    """The day the Status card turns Oversold, the chart shows it too."""
    df = _df([0.2, 0.2, 0.05])
    _, bands = _bands(df)
    assert len(bands) == 2
    assert all(pd.Timestamp(b.x1) > pd.Timestamp(b.x0) == df["date"][2] for b in bands)


def test_run_at_the_end_stops_at_the_last_day():
    df = _df([0.2, 0.05, 0.05])
    _, bands = _bands(df)
    assert pd.Timestamp(bands[0].x0) == df["date"][1] and pd.Timestamp(bands[0].x1) == df["date"][2]


def test_blank_ratio_splits_a_run():
    _, bands = _bands(_df([0.05, float("nan"), 0.05, 0.2]))
    assert len(bands) == 4


def test_all_blank_lower_uses_the_default_level():
    df = _df([0.2, 0.05, 0.2, 0.096, 0.2])
    df["lower"] = float("nan")
    _, bands = _bands(df)
    assert len(bands) == 4
