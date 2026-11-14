"""Offline dry-run contracts: do not even initialize the target database."""
from datetime import datetime, timezone
import importlib.util
import sqlite3

import pandas as pd
import pytest
import requests

import collect
import import_excel as excel
from src.constants import INDUSTRIES
from src.data_collector import CollectResult


@pytest.fixture(autouse=True)
def offline(mocker):
    mocker.patch('collect.load_dotenv')
    mocker.patch.dict('os.environ', {'FINVIZ_API_KEY': 'synthetic'})
    mocker.patch('src.data_collector.time.sleep')
    # Also runs against the session-policy PR without depending on wall time.
    if importlib.util.find_spec('src.collection_session'):
        mocker.patch('src.collection_session.utc_now', return_value=datetime(2026, 11, 13, 22, tzinfo=timezone.utc))
    response = requests.Response()
    response.status_code = 200
    response._content = b'Ticker,Company\nAAPL,Apple\n'
    get = mocker.patch('requests.Session.get', return_value=response)
    close = mocker.spy(requests.Session, 'close')
    return get, close


def snapshot(root):
    files = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    directories = sorted(str(p.relative_to(root)) for p in root.rglob('*') if p.is_dir())
    return files, directories


@pytest.fixture(params=['absent', 'nested', 'legacy', 'not_sqlite'])
def target(tmp_path, request):
    path = tmp_path / ('missing/nested/preview.db' if request.param == 'nested' else 'preview.db')
    if request.param == 'legacy':
        with sqlite3.connect(path) as conn:
            conn.execute('CREATE TABLE uptrend_raw (date TEXT, worksheet TEXT, count INTEGER, total INTEGER)')
            conn.execute("INSERT INTO uptrend_raw VALUES ('2026-01-01','all',2,5)")
    elif request.param == 'not_sqlite':
        path.write_bytes(b'not a database; previews should not inspect this')
    return path


def run_collect(mocker, target, *options):
    mocker.patch('sys.argv', ['collect.py', '--db', str(target), *options])
    try:
        collect.main()
    except SystemExit as exc:
        return exc.code
    return 0


@pytest.mark.parametrize('failed', [False, True])
def test_collection_single_preview_preserves_target(target, tmp_path, mocker, offline, failed):
    get, close = offline
    if failed:
        get.side_effect = requests.ConnectionError('offline synthetic failure')
    before = snapshot(tmp_path)
    assert run_collect(mocker, target, '--dry-run', '--worksheet', 'all') == int(failed)
    assert snapshot(tmp_path) == before
    close.assert_called_once()


@pytest.mark.parametrize('scope', ['sectors', 'industries', 'all'])
@pytest.mark.parametrize('outcome,expected', [('success', 0), ('partial', 2), ('failure', 1)])
def test_bulk_preview_status_and_no_mutation(target, tmp_path, mocker, offline, scope, outcome, expected):
    get, close = offline
    valid = get.return_value
    bad = requests.Response()
    bad.status_code = 200
    bad._content = b'<html>invalid export</html>'
    if outcome == 'failure':
        get.return_value = bad
    elif outcome == 'partial':
        # Fail one worksheet, then allow all remaining requests to succeed.
        get.side_effect = lambda *a, **kw: bad if get.call_count == 1 else valid
    before = snapshot(tmp_path)
    assert run_collect(mocker, target, '--dry-run', '--scope', scope) == expected
    assert snapshot(tmp_path) == before
    close.assert_called_once()


@pytest.fixture
def workbook(mocker):
    sheets = {'all': pd.DataFrame({'Date': ['2026-11-13', 'bad-date', None, '2026-11-12'],
                                  'Count': [1, 2, 3, 1.5], 'Total': [5, 5, 5, 5]})}
    mocker.patch('import_excel.pd.read_excel', return_value=sheets)
    return sheets


def test_excel_preview_preserves_target_and_valid_counts(target, tmp_path, workbook):
    before = snapshot(tmp_path)
    assert excel.import_excel('synthetic.xlsx', db_path=str(target), dry_run=True) == {'all': 1}
    assert snapshot(tmp_path) == before


def test_excel_parsing_failure_preserves_target(target, tmp_path, mocker):
    before = snapshot(tmp_path)
    mocker.patch('import_excel.pd.read_excel', side_effect=ValueError('invalid workbook'))
    with pytest.raises(ValueError, match='invalid workbook'):
        excel.import_excel('synthetic.xlsx', db_path=str(target), dry_run=True)
    assert snapshot(tmp_path) == before


def test_previews_never_construct_dbclient(tmp_path, mocker, offline, workbook):
    collection_db = mocker.patch('collect.DBClient', side_effect=AssertionError('DB opened'))
    excel_db = mocker.patch('import_excel.DBClient', side_effect=AssertionError('DB opened'))
    assert run_collect(mocker, tmp_path / 'unused.db', '--dry-run', '--worksheet', 'all') == 0
    assert excel.import_excel('synthetic.xlsx', db_path=str(tmp_path / 'unused.db'), dry_run=True) == {'all': 1}
    collection_db.assert_not_called()
    excel_db.assert_not_called()


def test_real_collection_still_writes(tmp_path, mocker, offline):
    path = tmp_path / 'real.db'
    assert run_collect(mocker, path, '--worksheet', 'all') == 0
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT worksheet,count,total FROM uptrend_raw').fetchall() == [('all', 1, 1)]


def test_real_excel_still_writes(tmp_path, workbook):
    path = tmp_path / 'real.db'
    assert excel.import_excel('synthetic.xlsx', db_path=str(path)) == {'all': 1}
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT worksheet,count,total FROM uptrend_raw').fetchall() == [('all', 1, 5)]


def test_real_industry_tolerance_is_preserved(tmp_path, mocker, offline):
    result = CollectResult(succeeded={key: (1, 2) for key in INDUSTRIES[1:]}, failed=[INDUSTRIES[0]])
    mocker.patch('src.data_collector.DataCollector.collect_all', return_value=result)
    assert run_collect(mocker, tmp_path / 'real.db', '--scope', 'industries') == 0
    assert run_collect(mocker, tmp_path / 'preview.db', '--scope', 'industries', '--dry-run') == 2


def test_preview_write_boundary_fails_closed(tmp_path, mocker, offline):
    def accidental_write(self, *args, **kwargs):
        self._db.upsert_raw_data('2026-11-13', 'all', 1, 2)
    mocker.patch('src.data_collector.DataCollector.collect_worksheet', accidental_write)
    assert run_collect(mocker, tmp_path / 'unused.db', '--dry-run', '--worksheet', 'all') == 1
    assert snapshot(tmp_path) == ({}, [])
    offline[1].assert_called_once()


def test_setup_failure_leaves_target_untouched(target, tmp_path, mocker, offline):
    before = snapshot(tmp_path)
    mocker.patch.dict('os.environ', {}, clear=True)
    assert run_collect(mocker, target, '--dry-run') == 1
    assert snapshot(tmp_path) == before
    offline[0].assert_not_called()
