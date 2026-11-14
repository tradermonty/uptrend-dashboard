"""Issue #3: session labels must reflect the live New York observation date."""

from datetime import datetime

import pytest
import requests


def instant(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


@pytest.mark.parametrize("text", [
    "2026-11-13T21:00:00Z", "2026-11-13T21:10:00Z", "2026-11-14T00:01:00Z",
    "2026-11-14T04:59:59Z", "2026-03-06T21:00:00Z", "2026-03-09T20:00:00Z",
    "2026-11-27T18:00:00Z",  # early close: 13:00 New York
])
def test_after_actual_close_uses_new_york_date(text):
    from src.collection_session import resolve_collection_date
    from zoneinfo import ZoneInfo
    now = instant(text)
    expected = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    assert resolve_collection_date(now=now) == expected
    assert resolve_collection_date(expected, now=now) == expected


@pytest.mark.parametrize("text", [
    "2026-11-13T20:59:59Z", "2026-03-06T20:59:59Z", "2026-03-09T19:59:59Z",
    "2026-11-27T17:59:59Z", "2026-11-16T05:01:00Z", # late start after NY midnight
    "2026-11-14T05:00:00Z", "2026-11-26T22:00:00Z", "2026-07-03T22:00:00Z",
])
def test_before_close_and_non_sessions_fail(text):
    from src.collection_session import resolve_collection_date, SessionPolicyError
    with pytest.raises(SessionPolicyError):
        resolve_collection_date(now=instant(text))


@pytest.mark.parametrize("requested", [
    "20261113", "2026-W46-5", "2026-11-13 ", " 2026-11-13", "２０２６-１１-１３",
    "2026-1-13", "2026-02-30", "", 20261113, "2026-11-12", "2026-11-16",
])
def test_malformed_or_past_future_assertions_fail(requested):
    from src.collection_session import resolve_collection_date, SessionPolicyError
    with pytest.raises(SessionPolicyError):
        resolve_collection_date(requested, now=instant("2026-11-13T22:00:00Z"))


def test_naive_clock_is_rejected():
    from src.collection_session import resolve_collection_date, SessionPolicyError
    with pytest.raises(SessionPolicyError):
        resolve_collection_date(now=datetime(2026, 11, 13, 22))


def test_calendar_failure_is_closed_and_does_not_echo_error(mocker):
    from src.collection_session import resolve_collection_date, SessionPolicyError
    mocker.patch("src.collection_session.session_calendar", side_effect=RuntimeError("auth=SECRET"))
    with pytest.raises(SessionPolicyError) as caught:
        resolve_collection_date(now=instant("2026-11-13T22:00:00Z"))
    assert "SECRET" not in str(caught.value)


@pytest.mark.parametrize("created,now,allowed", [
    ("2026-11-13T21:10:00Z", "2026-11-14T00:10:00Z", True),
    ("2026-11-13T21:10:00Z", "2026-11-16T22:00:00Z", False),
    ("2026-11-14T01:10:00Z", "2026-11-14T02:10:00Z", True),
    ("2026-11-13T21:10:00Z", "2026-11-14T05:10:00Z", False),
    ("", "2026-11-13T22:00:00Z", False),
    ("null", "2026-11-13T22:00:00Z", False),
    ("2026-11-13T22:00:00", "2026-11-13T22:00:00Z", False),
])
def test_workflow_origin_is_evidence_not_execution_date(created, now, allowed):
    from src.collection_session import resolve_run_session, SessionPolicyError
    if allowed:
        assert resolve_run_session(created, now=instant(now)) == "2026-11-13"
    else:
        with pytest.raises(SessionPolicyError):
            resolve_run_session(created, now=instant(now))


@pytest.fixture
def collector(db_client, mocker):
    from src.data_collector import CollectorConfig, DataCollector
    mocker.patch("src.collection_session.utc_now", return_value=instant("2026-11-13T22:00:00Z"))
    obj = DataCollector(db_client, CollectorConfig(finviz_api_key="synthetic", request_interval=0, retry_delay=0))
    yield obj
    obj.close()


def csv_response():
    r = requests.Response()
    r.status_code = 200
    r._content = b"Ticker,Company\nAAPL,Apple\n"
    return r


@pytest.mark.parametrize("bulk", [False, True])
@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("requested", ["2026-11-12", "20261113", "2026-11-16"])
def test_forbidden_label_never_requests_or_overwrites(collector, db_client, mocker, bulk, dry_run, requested):
    from src.collection_session import SessionPolicyError
    db_client.upsert_raw_data("2026-11-12", "all", 5, 10)
    get = mocker.patch.object(collector._session, "get")
    method = collector.collect_all if bulk else lambda **kwargs: collector.collect_worksheet("all", **kwargs)
    with pytest.raises(SessionPolicyError):
        method(date=requested, dry_run=dry_run)
    get.assert_not_called()
    assert db_client.fetch_raw_data("all")["count"].tolist() == [5]


@pytest.mark.parametrize("boundary", ["between_responses", "after_pair", "retry"])
def test_midnight_aborts_before_later_requests_and_writes(collector, db_client, mocker, boundary):
    from src.collection_session import SessionPolicyError
    before = instant("2026-11-14T04:59:59Z")
    after = instant("2026-11-14T05:00:00Z")
    clock = mocker.patch("src.collection_session.utc_now", return_value=before)
    calls = []
    def get(*args, **kwargs):
        calls.append(1)
        if boundary in ("between_responses", "retry") or len(calls) == 2:
            clock.return_value = after
        if boundary == "retry":
            raise requests.Timeout("synthetic timeout")
        return csv_response()
    mocker.patch.object(collector._session, "get", side_effect=get)
    mocker.patch("src.data_collector.time.sleep")
    with pytest.raises(SessionPolicyError):
        collector.collect_worksheet("all")
    assert len(calls) == (2 if boundary == "after_pair" else 1)
    assert db_client.fetch_raw_data("all").empty


def test_final_industry_session_failure_is_fatal_despite_tolerance(collector, mocker):
    from src.constants import INDUSTRIES
    from src.collection_session import SessionPolicyError
    from src.data_collector import CollectScope
    def worksheet(key, *args, **kwargs):
        if key == INDUSTRIES[-1]:
            raise SessionPolicyError("session expired")
        return (1, 2)
    mocker.patch.object(collector, "collect_worksheet", side_effect=worksheet)
    with pytest.raises(SessionPolicyError):
        collector.collect_all(scope=CollectScope.INDUSTRIES)


@pytest.mark.parametrize("requested", ["20261113", "2026-11-12", "2026-11-16"])
@pytest.mark.parametrize("single", [False, True])
def test_cli_rejects_before_db_creation_or_http(tmp_path, mocker, requested, single):
    from collect import main
    path = tmp_path / "must-not-exist.db"
    argv = ["collect.py", "--db", str(path), "--date", requested]
    if single:
        argv += ["--worksheet", "all"]
    mocker.patch("sys.argv", argv)
    mocker.patch("collect.load_dotenv")
    mocker.patch.dict("os.environ", {"FINVIZ_API_KEY": "synthetic"})
    mocker.patch("src.collection_session.utc_now", return_value=instant("2026-11-13T22:00:00Z"))
    get = mocker.patch("requests.Session.get")
    with pytest.raises(SystemExit) as caught:
        main()
    assert caught.value.code == 1
    assert not path.exists()
    get.assert_not_called()


def test_cli_policy_violation_is_nonzero_without_traceback(tmp_path, mocker, caplog):
    from collect import main
    from src.collection_session import SessionPolicyError
    mocker.patch("sys.argv", ["collect.py", "--db", str(tmp_path / "scratch.db")])
    mocker.patch("collect.load_dotenv")
    mocker.patch.dict("os.environ", {"FINVIZ_API_KEY": "synthetic"})
    mocker.patch("src.collection_session.utc_now", return_value=instant("2026-11-13T22:00:00Z"))
    mocker.patch("src.data_collector.DataCollector.collect_all", side_effect=SessionPolicyError("session expired"))
    with pytest.raises(SystemExit) as caught:
        main()
    assert caught.value.code == 1
    assert "session expired" in caplog.text


@pytest.mark.parametrize("explicit", [None, "2026-11-13"])
def test_valid_default_and_explicit_session_persist_same_date(collector, db_client, mocker, explicit):
    mocker.patch.object(collector._session, "get", side_effect=lambda *a, **k: csv_response())
    assert collector.collect_worksheet("all", date=explicit) == (1, 1)
    row = db_client.fetch_raw_data("all").iloc[0]
    assert str(row["date"].date()) == "2026-11-13"


def test_last_industry_crossing_midnight_aborts_cli_even_below_tolerance(tmp_path, mocker):
    from collect import main
    from src.constants import INDUSTRIES
    from src.db_client import DBClient
    target = tmp_path / "scratch.db"
    mocker.patch("sys.argv", ["collect.py", "--db", str(target), "--scope", "industries"])
    mocker.patch("collect.load_dotenv")
    mocker.patch.dict("os.environ", {"FINVIZ_API_KEY": "synthetic"})
    clock = mocker.patch("src.collection_session.utc_now", return_value=instant("2026-11-14T04:59:59Z"))
    mocker.patch("src.data_collector.time.sleep")
    final_calls = []
    def get(self, url, **kwargs):
        if INDUSTRIES[-1] in url:
            final_calls.append(url)
            clock.return_value = instant("2026-11-14T05:00:00Z")
        return csv_response()
    mocker.patch("requests.Session.get", get)
    with pytest.raises(SystemExit) as caught:
        main()
    assert caught.value.code == 1
    assert len(final_calls) == 1
    db = DBClient(str(target))
    assert db.fetch_raw_data(INDUSTRIES[-1]).empty
    assert not db.fetch_raw_data(INDUSTRIES[0]).empty


def test_request_boundary_also_enforces_policy(collector, mocker):
    from src.collection_session import SessionPolicyError
    get = mocker.patch.object(collector._session, "get")
    with pytest.raises(SessionPolicyError):
        collector._make_request("http://synthetic.invalid", session_date="2026-11-12")
    get.assert_not_called()


@pytest.mark.parametrize("failure", ["malformed", "timeout", "http", "request"])
def test_final_industry_error_after_midnight_is_fatal_and_secret_safe(db_client, mocker, failure):
    import traceback
    from src.collection_session import SessionPolicyError
    from src.constants import INDUSTRIES
    from src.data_collector import DataCollector, CollectorConfig, CollectScope
    key = "SYNTHETIC_BOUNDARY_SECRET"
    clock = mocker.patch("src.collection_session.utc_now", return_value=instant("2026-11-14T04:59:59Z"))
    collector = DataCollector(db_client, CollectorConfig(finviz_api_key=key, request_interval=0, max_retries=1))
    mocker.patch("src.data_collector.time.sleep")
    calls = []
    def get(url, **kwargs):
        if INDUSTRIES[-1] in url:
            calls.append(url)
            clock.return_value = instant("2026-11-14T05:00:00Z")
            if failure == "timeout":
                raise requests.Timeout(f"auth={key}")
            if failure == "request":
                raise requests.RequestException(f"auth={key}")
            response = csv_response()
            if failure == "http":
                response.status_code = 401
                response.url = f"https://synthetic.invalid?auth={key}"
            else:
                response._content = b"error\nsubscription expired\n"
            return response
        return csv_response()
    mocker.patch.object(collector._session, "get", side_effect=get)
    try:
        with pytest.raises(SessionPolicyError) as caught:
            collector.collect_all(scope=CollectScope.INDUSTRIES)
        rendered = "".join(traceback.format_exception(caught.type, caught.value, caught.tb))
        assert key not in rendered
        assert len(calls) == 1
        assert db_client.fetch_raw_data(INDUSTRIES[-1]).empty
    finally:
        collector.close()
