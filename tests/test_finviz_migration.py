"""Read-only migration comparison and publication prerequisites (#35)."""

import json
from datetime import UTC
from urllib.parse import parse_qs, urlsplit

import pytest

from src.finviz_universe import (
    REQUIRED_SAMPLES,
    MigrationEvidenceError,
    build_export_url,
    comparison_report,
    universes_for,
    validate_evidence,
)

START = "2026-11-17T22:00:00+00:00"
END = "2026-11-17T22:10:00+00:00"


def samples():
    out = {}
    for ws in REQUIRED_SAMPLES:
        halves = {}
        for half in ("uptrend", "total"):
            stock = (
                ["AAA"] if ws in ("all", "sec_financial", "ind_semiconductors") else []
            )
            fund = (
                ["CEF"]
                if ws in ("all", "sec_financial", "ind_closedendfunddebt")
                and half == "total"
                else []
            )
            halves[half] = {
                role: {"tickers": values, "http_status": 200, "fetched_at": START}
                for role, values in [
                    ("legacy", stock + fund),
                    ("stocks", stock),
                    ("etf", fund),
                ]
            }
        out[ws] = halves
    return out


def evidence():
    return comparison_report(samples(), START, END)


@pytest.mark.parametrize(
    "ws,routes",
    [
        ("all", ("stocks", "etf")),
        ("sec_financial", ("stocks", "etf")),
        ("sec_technology", ("stocks",)),
        ("ind_semiconductors", ("stocks",)),
        ("ind_exchangetradedfund", ("etf",)),
        ("ind_closedendfunddebt", ("etf",)),
        ("ind_closedendfundequity", ("etf",)),
        ("ind_closedendfundforeign", ("etf",)),
    ],
)
def test_stock_and_fund_routing(ws, routes):
    assert universes_for(ws) == routes
    for uptrend in (False, True):
        url = build_export_url(
            "https://elite.finviz.com", "marker-key", uptrend, ws, routes[0]
        )
        assert urlsplit(url).path == "/export/screener"
        query = parse_qs(urlsplit(url).query)
        assert query["type"] == [routes[0]] and query["c"] == ["1"]
        assert query["v"] == ["151"] and query["ft"] == ["4"]
        filters = query["f"][0].split(",")
        assert filters[:3] == ["cap_microover", "sh_avgvol_o100", "sh_price_o10"]
        assert ("ta_sma50_sa200" in filters) is uptrend
        assert (ws in filters) is (ws != "all")


def test_unknown_filter_cannot_be_silently_ignored():
    with pytest.raises(MigrationEvidenceError):
        universes_for("ind_unknown")


def test_comparison_matches_sets_not_only_counts():
    raw = samples()
    raw["all"]["total"]["stocks"]["tickers"] = ["BBB"]
    report = comparison_report(raw, START, END)
    assert not report["ready"]
    assert report["worksheets"]["all"]["total"]["missing"] == ["AAA"]
    assert report["worksheets"]["all"]["total"]["extra"] == ["BBB"]


def test_union_preserves_denominator_and_ratio():
    report = evidence()
    assert report["ready"]
    row = report["worksheets"]["all"]
    assert row["total"]["legacy_count"] == row["total"]["candidate_count"] == 2
    assert row["legacy_ratio"] == row["candidate_ratio"] == 0.5
    validate_evidence(report)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r["worksheets"].pop("sec_financial"),
        lambda r: r.update(ready=False),
        lambda r: r.update(policy_fingerprint="changed-filter"),
        lambda r: r["worksheets"]["all"]["total"].update(candidate_hash="different"),
        lambda r: r["worksheets"]["all"]["total"].update(candidate_count=99),
        lambda r: r["worksheets"]["all"]["total"].update(missing=["AAA"]),
    ],
)
def test_incomplete_changed_or_failed_evidence_is_not_approval(mutate):
    report = evidence()
    mutate(report)
    with pytest.raises(MigrationEvidenceError):
        validate_evidence(report)


def test_invalid_or_missing_sample_does_not_look_like_zero():
    for entry in ({"error": "InvalidFinvizResponse"}, {"http_status": 403}, {}):
        raw = samples()
        raw["ind_closedendfunddebt"]["total"]["etf"] = entry
        report = comparison_report(raw, START, END)
        assert not report["ready"]
        with pytest.raises(MigrationEvidenceError):
            validate_evidence(report)


def test_overlapping_routes_and_non_subset_numerator_are_rejected():
    raw = samples()
    raw["all"]["total"]["etf"]["tickers"] = ["AAA"]
    assert not comparison_report(raw, START, END)["ready"]
    raw = samples()
    raw["all"]["uptrend"]["stocks"]["tickers"] = ["OUTSIDE"]
    raw["all"]["uptrend"]["legacy"]["tickers"] = ["OUTSIDE"]
    assert not comparison_report(raw, START, END)["ready"]


def test_empty_fund_is_valid_but_empty_market_is_not():
    assert evidence()["worksheets"]["ind_exchangetradedfund"]["legacy_ratio"] is None
    raw = samples()
    for entry in raw["all"]["total"].values():
        entry["tickers"] = []
    assert not comparison_report(raw, START, END)["ready"]


@pytest.fixture
def closed_session(monkeypatch):
    from datetime import datetime

    monkeypatch.setattr(
        "src.collection_session.utc_now", lambda: datetime(2026, 11, 13, 22, tzinfo=UTC)
    )


def response(text):
    from unittest.mock import Mock

    obj = Mock()
    obj.status_code = 200
    obj.content = text.encode()
    return obj


def test_real_collector_preserves_union_and_past_history(
    db_client, monkeypatch, closed_session
):
    from src.data_collector import CollectorConfig, DataCollector

    db_client.upsert_raw_data("2026-11-12", "all", 2, 5)
    collector = DataCollector(
        db_client, CollectorConfig("marker-key", request_interval=0)
    )
    calls = []

    def get(url, **kwargs):
        q = parse_qs(urlsplit(url).query)
        calls.append(q)
        if q["type"] == ["stocks"]:
            return response("Ticker\nAAA\n")
        return response("Ticker\n" if "ta_sma20_pa" in q["f"][0] else "Ticker\nCEF\n")

    monkeypatch.setattr(collector._session, "get", get)
    assert collector.collect_worksheet("all", "2026-11-13") == (1, 2)
    frame = db_client.fetch_raw_data("all")
    assert frame["count"].tolist() == [2, 1]
    assert frame["total"].tolist() == [5, 2]
    assert [q["type"][0] for q in calls] == ["stocks", "etf", "stocks", "etf"]
    collector.close()


def test_failed_fund_half_cannot_update_worksheet(
    db_client, tmp_db, monkeypatch, closed_session
):
    import hashlib

    from src.data_collector import CollectorConfig, DataCollector, InvalidFinvizResponse

    db_client.upsert_raw_data("2026-11-12", "all", 2, 5)
    before = hashlib.sha256(__import__("pathlib").Path(tmp_db).read_bytes()).hexdigest()
    collector = DataCollector(
        db_client, CollectorConfig("marker-key", request_interval=0)
    )

    def get(url, **kwargs):
        q = parse_qs(urlsplit(url).query)
        return response(
            "<html>unsupported</html>" if q["type"] == ["etf"] else "Ticker\nAAA\n"
        )

    monkeypatch.setattr(collector._session, "get", get)
    with pytest.raises(InvalidFinvizResponse):
        collector.collect_worksheet("all", "2026-11-13")
    assert (
        hashlib.sha256(__import__("pathlib").Path(tmp_db).read_bytes()).hexdigest()
        == before
    )
    collector.close()


def test_changed_filter_receipt_stops_before_http(db_client, monkeypatch):
    import src.finviz_universe as policy
    from src.data_collector import CollectorConfig, DataCollector

    monkeypatch.setattr(
        policy, "BASE_FILTERS", [*policy.BASE_FILTERS, "unsupported_filter"]
    )
    with pytest.raises(MigrationEvidenceError):
        DataCollector(db_client, CollectorConfig("marker-key"))


def test_failed_receipt_cli_never_opens_db(tmp_path, monkeypatch, closed_session):
    from unittest.mock import Mock

    import collect

    monkeypatch.setenv("FINVIZ_API_KEY", "marker-key")
    monkeypatch.setattr(
        "sys.argv", ["collect.py", "--db", str(tmp_path / "new" / "history.db")]
    )
    monkeypatch.setattr(
        collect,
        "load_evidence",
        Mock(side_effect=MigrationEvidenceError("unverified comparison")),
    )
    opening = Mock(side_effect=AssertionError("must not open DB"))
    monkeypatch.setattr(collect, "DBClient", opening)
    with pytest.raises(SystemExit) as exc:
        collect.main()
    assert exc.value.code == 1
    opening.assert_not_called()
    assert not (tmp_path / "new").exists()


def test_comparison_errors_are_not_saved_as_zero_or_leaked():
    from unittest.mock import Mock

    import requests

    import compare_finviz_exports as command

    session = Mock()
    session.get.side_effect = requests.ConnectionError(
        "https://example.test/?auth=marker-key"
    )
    report = command.collect_comparison(
        "marker-key", session=session, request_interval=0
    )
    assert not report["ready"]
    assert "marker-key" not in json.dumps(report)
    assert "example.test" not in json.dumps(report)


def test_comparison_refuses_overwrite_before_network(tmp_path, monkeypatch):
    from unittest.mock import Mock

    import compare_finviz_exports as command

    target = tmp_path / "old.json"
    target.write_text("preserved")
    fetch = Mock(side_effect=AssertionError("must not fetch"))
    monkeypatch.setattr(command, "collect_comparison", fetch)
    assert command.main(["--output", str(target)]) == 1
    assert target.read_text() == "preserved"
    fetch.assert_not_called()


@pytest.mark.parametrize("encoded", [False, True])
def test_reflected_key_in_csv_is_rejected_not_written_to_comparison(encoded):
    from unittest.mock import Mock
    from urllib.parse import quote

    import compare_finviz_exports as command

    key = "synthetic-migration+key"
    session = Mock()
    session.get.return_value = response(
        "Ticker\n" + (quote(key, safe="") if encoded else key) + "\n"
    )
    report = command.collect_comparison(key, session=session, request_interval=0)
    rendered = json.dumps(report)
    assert not report["ready"]
    assert key not in rendered and quote(key, safe="") not in rendered


def test_evidence_rejects_relabelled_session_and_cross_date_window():
    report = evidence()
    report["latest_closed_session"] = "2026-11-13"
    with pytest.raises(MigrationEvidenceError):
        validate_evidence(report)
    with pytest.raises(MigrationEvidenceError):
        comparison_report(samples(), START, "2026-11-18T22:00:00+00:00")


@pytest.mark.parametrize("problem", ["overlap", "outside"])
def test_runtime_identity_failure_preserves_history(
    db_client, tmp_db, monkeypatch, closed_session, problem
):
    from pathlib import Path

    from src.data_collector import CollectorConfig, DataCollector, InvalidFinvizResponse

    db_client.upsert_raw_data("2026-11-12", "all", 2, 5)
    before = Path(tmp_db).read_bytes()
    collector = DataCollector(
        db_client, CollectorConfig("marker-key", request_interval=0)
    )

    def get(url, **kwargs):
        q = parse_qs(urlsplit(url).query)
        if q["type"] == ["etf"]:
            return response("Ticker\nAAA\n" if problem == "overlap" else "Ticker\n")
        uptrend = "ta_sma20_pa" in q["f"][0]
        return response(
            "Ticker\nOUTSIDE\n" if uptrend and problem == "outside" else "Ticker\nAAA\n"
        )

    monkeypatch.setattr(collector._session, "get", get)
    with pytest.raises(InvalidFinvizResponse):
        collector.collect_worksheet("all", "2026-11-13")
    assert Path(tmp_db).read_bytes() == before
    collector.close()


def test_fund_collection_uses_etf_for_both_halves(
    db_client, monkeypatch, closed_session
):
    from src.data_collector import CollectorConfig, DataCollector

    collector = DataCollector(
        db_client, CollectorConfig("marker-key", request_interval=0)
    )
    queries = []

    def get(url, **kwargs):
        q = parse_qs(urlsplit(url).query)
        queries.append(q)
        return response("Ticker\n" if "ta_sma20_pa" in q["f"][0] else "Ticker\nCEF\n")

    monkeypatch.setattr(collector._session, "get", get)
    assert collector.collect_worksheet("ind_closedendfunddebt", "2026-11-13") == (0, 1)
    assert [q["type"] for q in queries] == [["etf"], ["etf"]]
    assert db_client.fetch_raw_data("ind_closedendfunddebt")["total"].tolist() == [1]
    collector.close()


def test_failed_comparison_cli_writes_only_diagnostic(tmp_path, monkeypatch):
    import compare_finviz_exports as command

    failed = evidence()
    failed["ready"] = False
    monkeypatch.setattr(command, "load_dotenv", lambda: None)
    monkeypatch.setenv("FINVIZ_API_KEY", "marker-key")
    monkeypatch.setattr(command, "collect_comparison", lambda *args: failed)
    target = tmp_path / "diagnostic.json"
    assert command.main(["--output", str(target)]) == 2
    assert json.loads(target.read_text())["ready"] is False
    assert sorted(p.name for p in tmp_path.iterdir()) == ["diagnostic.json"]
