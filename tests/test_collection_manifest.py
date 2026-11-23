"""Collection outcome manifest and coverage counters (Issue #6 part 2)."""

import json

import pytest

from src.collection_manifest import (
    MANIFEST_VERSION,
    build_manifest,
    coverage_caption,
    load_manifest,
    write_manifest,
)
from src.data_collector import CollectResult

EXPECTED = ["all", "sec_technology", "ind_semiconductors", "ind_gold",
            "ind_infrastructureoperations", "ind_solar"]


def _result():
    r = CollectResult()
    r.succeeded = {
        "all": (180, 2600),
        "sec_technology": (40, 400),
        "ind_semiconductors": (10, 60),
        "ind_infrastructureoperations": (0, 0),   # valid-empty: total=0, not written
    }
    r.failed = ["ind_gold"]
    return r                                      # ind_solar never attempted


def _manifest(**kw):
    args = dict(
        result=_result(), expected=EXPECTED, session_date="2026-11-20", scope="all",
        dry_run=False,
        stored=["all", "sec_technology", "ind_semiconductors"],
        last_stored={"ind_gold": "2026-11-19", "ind_infrastructureoperations": "2026-03-27"},
        generated_at="2026-11-20T21:15:00+00:00",
    )
    args.update(kw)
    return build_manifest(**args)


class TestOutcomes:

    def test_each_worksheet_gets_exactly_one_outcome(self):
        ws = _manifest()["worksheets"]
        assert ws["all"]["outcome"] == "persisted"
        assert ws["ind_infrastructureoperations"]["outcome"] == "empty"
        assert ws["ind_gold"]["outcome"] == "failed"
        assert ws["ind_solar"]["outcome"] == "missing"
        assert set(ws) == set(EXPECTED)

    def test_counts_and_totals_recorded_for_fetched(self):
        ws = _manifest()["worksheets"]
        assert ws["ind_semiconductors"]["count"] == 10
        assert ws["ind_semiconductors"]["total"] == 60
        assert ws["ind_infrastructureoperations"]["total"] == 0
        assert "count" not in ws["ind_gold"]

    def test_valid_empty_is_not_persisted_nor_failed(self):
        c = _manifest()["coverage"]
        assert c["empty"] == 1 and c["failed"] == 1 and c["persisted"] == 3

    def test_not_stored_rows_carry_last_stored_date(self):
        ws = _manifest()["worksheets"]
        assert ws["ind_infrastructureoperations"]["last_stored"] == "2026-03-27"
        assert ws["ind_gold"]["last_stored"] == "2026-11-19"
        assert ws["ind_solar"]["last_stored"] is None
        assert "last_stored" not in ws["all"]

    def test_dry_run_counts_would_be_writes_as_fetched_only(self):
        m = _manifest(dry_run=True, stored=None)
        assert m["worksheets"]["all"]["outcome"] == "fetched"
        assert m["coverage"]["persisted"] == 0 and m["coverage"]["stored"] is None


class TestCoverage:

    def test_counters_reconcile(self):
        c = _manifest()["coverage"]
        assert c["expected"] == 6
        assert c["fetched"] == 4                      # persisted + empty
        assert c["missing"] == 1
        assert c["expected"] == c["fetched"] + c["failed"] + c["missing"]
        assert c["stored"] == 3
        assert c["reconciled"] is True

    def test_persisted_row_absent_from_db_breaks_reconciliation(self):
        c = _manifest(stored=["all", "sec_technology"])["coverage"]
        assert c["reconciled"] is False

    def test_stored_counts_only_expected_worksheets(self):
        c = _manifest(stored=["all", "sec_technology", "ind_semiconductors", "ind_other"])["coverage"]
        assert c["stored"] == 3

    def test_header_fields(self):
        m = _manifest()
        assert m["version"] == MANIFEST_VERSION
        assert m["session_date"] == "2026-11-20"
        assert m["scope"] == "all" and m["dry_run"] is False
        assert m["generated_at"] == "2026-11-20T21:15:00+00:00"


class TestFile:

    def test_write_then_load_round_trip(self, tmp_path):
        path = tmp_path / "data" / "collection_manifest.json"
        write_manifest(_manifest(), path)
        assert load_manifest(path) == json.loads(path.read_text())
        assert not list(path.parent.glob("*.tmp"))

    def test_load_missing_or_broken_returns_none(self, tmp_path):
        assert load_manifest(tmp_path / "nope.json") is None
        bad = tmp_path / "bad.json"
        bad.write_text("{not json")
        assert load_manifest(bad) is None


class TestCaption:

    def test_caption_lists_counts(self):
        text = coverage_caption(_manifest())
        assert "2026-11-20" in text
        for part in ("3 of 6 stored", "1 empty", "1 failed", "1 not attempted"):
            assert part in text

    def test_caption_omits_zero_parts(self):
        r = CollectResult()
        r.succeeded = {k: (1, 10) for k in EXPECTED}
        m = _manifest(result=r, stored=EXPECTED)
        text = coverage_caption(m)
        assert "6 of 6 stored" in text and "failed" not in text and "empty" not in text

    @pytest.mark.parametrize("bad", [None, {}, {"coverage": {}}])
    def test_caption_empty_for_missing_manifest(self, bad):
        assert coverage_caption(bad) == ""


class TestDBQueries:

    def test_worksheets_on_and_last_dates(self, tmp_path):
        from src.db_client import DBClient
        db = DBClient(str(tmp_path / "u.db"))
        db.upsert_raw_data("2026-11-19", "all", 10, 100)
        db.upsert_raw_data("2026-11-20", "all", 11, 100)
        db.upsert_raw_data("2026-03-27", "ind_infrastructureoperations", 0, 3)
        assert db.worksheets_on("2026-11-20") == ["all"]
        assert db.last_dates() == {"all": "2026-11-20",
                                   "ind_infrastructureoperations": "2026-03-27"}


class TestCLIWritesManifest:

    @pytest.fixture(autouse=True)
    def _session_clock(self, mocker):
        """Freeze the session policy clock to a weekday after the close (2026-11-13)."""
        from datetime import datetime, timezone
        mocker.patch("src.collection_session.utc_now",
                     return_value=datetime(2026, 11, 13, 22, tzinfo=timezone.utc))

    def _run(self, tmp_path, mocker, extra=()):
        from src.constants import VALID_WORKSHEETS
        db_path = tmp_path / "uptrend.db"
        mocker.patch("sys.argv", ["collect.py", "--db", str(db_path), *extra])
        mocker.patch.dict("os.environ", {"FINVIZ_API_KEY": "test_key"})
        mocker.patch("collect.collect_constituents_safely")
        succeeded = {ws: (1, 10) for ws in VALID_WORKSHEETS if ws != "ind_gold"}
        succeeded["ind_infrastructureoperations"] = (0, 0)
        mocker.patch("src.data_collector.DataCollector.collect_all",
                     return_value=CollectResult(succeeded=succeeded, failed=["ind_gold"]))
        from collect import main
        try:
            main()
        except SystemExit as exc:
            assert exc.code in (0, 2, None)
        return tmp_path / "collection_manifest.json"

    def test_live_run_writes_manifest_next_to_db(self, tmp_path, mocker):
        m = load_manifest(self._run(tmp_path, mocker))
        assert m["scope"] == "all" and m["dry_run"] is False
        c = m["coverage"]
        assert (c["expected"], c["empty"], c["failed"], c["missing"]) == (161, 1, 1, 0)
        assert m["worksheets"]["ind_infrastructureoperations"]["outcome"] == "empty"

    def test_dry_run_writes_nothing(self, tmp_path, mocker):
        assert not self._run(tmp_path, mocker, extra=("--dry-run",)).exists()

    def test_manifest_path_option(self, tmp_path, mocker):
        target = tmp_path / "out" / "m.json"
        self._run(tmp_path, mocker, extra=("--manifest", str(target)))
        assert load_manifest(target)["coverage"]["expected"] == 161

    def test_fatal_abort_still_writes_manifest_and_exits_1(self, tmp_path, mocker):
        from src.collection_session import SessionPolicyError
        mocker.patch("sys.argv", ["collect.py", "--db", str(tmp_path / "uptrend.db")])
        mocker.patch.dict("os.environ", {"FINVIZ_API_KEY": "test_key"})
        mocker.patch("collect.collect_constituents_safely")

        def partial_then_abort(self, date=None, dry_run=False, scope=None, result=None):
            result.succeeded["all"] = (1, 10)
            raise SessionPolicyError("crossed NY midnight")

        mocker.patch("src.data_collector.DataCollector.collect_all", partial_then_abort)
        from collect import main
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1
        m = load_manifest(tmp_path / "collection_manifest.json")
        assert m["aborted"] == "SessionPolicyError"
        assert m["coverage"]["missing"] == 160


class TestReviewFixes:

    def test_aborted_run_marks_unattempted_as_missing(self):
        r = CollectResult()
        r.succeeded = {"all": (1, 10)}
        m = _manifest(result=r, stored=["all"], aborted="SessionPolicyError")
        assert m["aborted"] == "SessionPolicyError"
        assert m["coverage"]["missing"] == 5
        assert "aborted" in coverage_caption(m)

    def test_completed_run_has_no_abort_marker(self):
        assert _manifest()["aborted"] is None
        assert "aborted" not in coverage_caption(_manifest())

    def test_each_worksheet_records_whether_db_has_its_row(self):
        ws = _manifest(stored=["all", "sec_technology", "ind_semiconductors", "ind_gold"])["worksheets"]
        assert ws["ind_gold"]["outcome"] == "failed" and ws["ind_gold"]["stored"] is True
        assert ws["ind_solar"]["stored"] is False

    def test_rewrite_with_only_new_timestamp_keeps_file(self, tmp_path):
        path = tmp_path / "m.json"
        assert write_manifest(_manifest(), path) is True
        before = path.read_bytes()
        assert write_manifest(_manifest(generated_at="2026-11-20T22:15:00+00:00"), path) is False
        assert path.read_bytes() == before

    def test_rewrite_with_changed_outcome_replaces_file(self, tmp_path):
        path = tmp_path / "m.json"
        write_manifest(_manifest(), path)
        assert write_manifest(_manifest(stored=["all"]), path) is True
        assert load_manifest(path)["coverage"]["stored"] == 1

    def test_caption_names_non_all_scope(self):
        assert "(sectors only)" in coverage_caption(_manifest(scope="sectors"))
        assert "only)" not in coverage_caption(_manifest())

    def test_default_path_follows_db_path(self, tmp_path, monkeypatch):
        from src.collection_manifest import default_manifest_path
        monkeypatch.setenv("DB_PATH", str(tmp_path / "x" / "u.db"))
        assert default_manifest_path() == tmp_path / "x" / "collection_manifest.json"
        monkeypatch.delenv("DB_PATH")
        assert str(default_manifest_path()) == "data/collection_manifest.json"
