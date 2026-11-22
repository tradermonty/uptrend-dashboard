"""Comparison bounds and real page regressions for Issue #13."""
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src.constants import SECTORS, SECTOR_INDUSTRIES
from src.data_processor import get_sector_display_name, get_industry_display_name

ROOT = Path(__file__).resolve().parents[1]


def frame(dates):
    return pd.DataFrame({'date': pd.to_datetime(dates), 'ratio': .2, 'ma_10': .2})


@pytest.mark.parametrize('keys', [['old', 'new'], ['new', 'old'], ['missing', 'empty', 'old', 'new']])
def test_bounds_union_is_order_independent(keys):
    from src.comparison_filters import comparison_date_bounds
    data = {'old': frame(['2024-01-01', '2024-01-03']),
            'new': frame(['2024-02-01', '2024-02-05']), 'empty': frame([])}
    assert comparison_date_bounds(data, keys) == (date(2024, 1, 1), date(2024, 2, 5))


def test_no_valid_dates_has_no_bounds():
    from src.comparison_filters import comparison_date_bounds
    assert comparison_date_bounds({'bad': frame([None]), 'empty': frame([])}, ['bad', 'empty', 'missing']) is None


@pytest.fixture(params=['sector', 'industry', 'cross'])
def comparison(request, mocker):
    kind = request.param
    if kind == 'sector':
        keys, display = SECTORS[:2], get_sector_display_name
        page, chart = '2_Sector_Comparison.py', 'build_sector_comparison_chart'
    else:
        keys, display = SECTOR_INDUSTRIES[SECTORS[0]][:2], get_industry_display_name
        page, chart = '4_Industry_Comparison.py', 'build_industry_comparison_chart'
    data = {keys[0]: frame(['2024-01-01', '2024-01-03']),
            keys[1]: frame(['2024-02-01', '2024-02-05'])}
    mocker.patch('src.data_loader.cached_load_sector_data', return_value=data)
    mocker.patch('src.data_loader.cached_load_all_data', return_value=data)
    # This separate feature is outside date filtering; isolate its sidebar.
    mocker.patch('src.indicator_calculator.calculate_sector_dispersion', return_value=pd.DataFrame())
    capture = mocker.spy(__import__('src.chart_builder', fromlist=[chart]), chart)
    app = AppTest.from_file(ROOT / 'app.py', default_timeout=20).run()
    app.switch_page('pages/' + page).run()
    if kind == 'cross':
        app.radio[0].set_value('Cross-Sector').run()
        prefix = get_sector_display_name(SECTORS[0]) + ' / '
        labels = [prefix + display(k) for k in keys]
    else:
        labels = [display(k) for k in keys]
    app.multiselect[0].set_value(labels).run()
    assert not app.exception
    return app, data, keys, labels, capture


def test_pages_union_latest_and_order(comparison):
    app, _, keys, labels, capture = comparison
    assert app.date_input[0].min == date(2024, 1, 1)
    assert app.date_input[0].max == date(2024, 2, 5)
    assert capture.call_args.args[0][keys[1]]['date'].max() == pd.Timestamp('2024-02-05')
    assert any('union' in x.value.lower() for x in app.caption)
    assert any('no common observation date' in x.value.lower() for x in app.info)
    app.multiselect[0].set_value(labels[::-1]).run()
    assert not app.exception
    assert app.date_input[0].value == (date(2024, 1, 1), date(2024, 2, 5))


def test_pages_manual_range_and_empty_partial_input(comparison):
    app, _, keys, _, capture = comparison
    app.date_input[0].set_value((date(2024, 2, 1), date(2024, 2, 5))).run()
    app.run()
    assert app.date_input[0].value == (date(2024, 2, 1), date(2024, 2, 5))
    assert keys[0] not in capture.call_args.args[0]
    assert any('No observations' in x.value for x in app.warning)
    capture.reset_mock()
    app.date_input[0].set_value((date(2024, 1, 10), date(2024, 1, 15))).run()
    assert not app.exception
    assert any('No observations in the selected date range' in x.value for x in app.warning)
    assert not capture.called
    app.date_input[0].set_value((date(2024, 1, 10),)).run()
    assert any('Select both' in x.value for x in app.info)
    assert not capture.called
    app.date_input[0].set_value(()).run()
    assert any('Select both' in x.value for x in app.info)


def test_pages_selection_reset_and_unavailable(comparison):
    app, data, keys, labels, capture = comparison
    app.date_input[0].set_value((date(2024, 1, 2), date(2024, 2, 1))).run()
    app.multiselect[0].set_value([labels[1]]).run()
    assert not app.exception
    assert app.date_input[0].value == (date(2024, 2, 1), date(2024, 2, 5))
    app.multiselect[0].set_value(labels).run()
    data.pop(keys[0])
    app.run()
    assert not app.exception
    assert any('No observations' in x.value for x in app.warning)
    capture.reset_mock()
    data.clear()
    app.run()
    assert not app.exception
    assert any('No dated observations' in x.value for x in app.warning)
    assert not app.date_input
    assert not capture.called
    app.multiselect[0].set_value([]).run()
    assert any('Please select at least one' in x.value for x in app.warning)


def test_pages_nat_empty_and_refresh_bounds(comparison):
    app, data, keys, labels, capture = comparison
    data[keys[0]] = frame([None, '2024-01-01'])
    data[keys[1]] = frame(['2024-02-05', '2024-03-01'])
    app.run()
    assert not app.exception
    assert app.date_input[0].max == date(2024, 3, 1)
    assert app.date_input[0].value[-1] == date(2024, 3, 1)
    assert not capture.call_args.args[0][keys[0]]['date'].isna().any()
    app.date_input[0].set_value((date(2024, 2, 1), date(2024, 2, 10))).run()
    app.multiselect[0].set_value(labels[::-1]).run()
    assert app.date_input[0].value == (date(2024, 2, 1), date(2024, 2, 10))
    data[keys[0]] = frame([])
    app.run()
    assert not app.exception
    assert any('No observations' in x.value for x in app.warning)
    assert len(app.dataframe[0].value) == 2


def test_pages_keep_configured_default_and_recover_after_revisit(comparison):
    app, data, keys, _, _ = comparison
    data[keys[0]] = frame(['2020-01-01', '2024-01-01'])
    app.run()
    assert not app.exception
    assert app.date_input[0].min == date(2020, 1, 1)
    assert app.date_input[0].value == (date(2022, 2, 5), date(2024, 2, 5))
    page = 'pages/2_Sector_Comparison.py' if keys[0].startswith('sec_') else 'pages/4_Industry_Comparison.py'
    app.switch_page('app.py').run()
    app.switch_page(page).run()
    # Cross-sector mode may reset to Within Sector on revisit; either mode must
    # recover valid range state instead of defaulting to an out-of-bound today.
    assert not app.exception
    if app.date_input:
        assert app.date_input[0].value[-1] <= date(2024, 2, 5)
