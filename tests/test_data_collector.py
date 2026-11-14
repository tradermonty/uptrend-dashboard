"""Tests for DataCollector — Finviz Elite CSV-based data collection."""

import io
import logging
import os
import subprocess
import sys
import traceback
from pathlib import Path
from unittest.mock import MagicMock, call

import pandas as pd
import pytest
import requests

import src.data_collector as dc_module
from src.data_collector import (
    CollectorConfig,
    CollectResult,
    CollectScope,
    DataCollector,
    RedactingFilter,
    configure_logging,
    mask_secrets,
    redact,
)


@pytest.fixture(autouse=True)
def after_close_observation_clock(mocker):
    """Freeze actual session policy for synthetic requests; do not bypass it."""
    from datetime import datetime, timezone
    mocker.patch("src.collection_session.utc_now", return_value=datetime(2026, 11, 13, 22, tzinfo=timezone.utc))


class TestCollectorConfig:
    """Test CollectorConfig defaults."""

    def test_default_values(self):
        config = CollectorConfig(finviz_api_key="test_key")
        assert config.base_url == "https://elite.finviz.com"
        assert config.max_retries == 5
        assert config.retry_delay == 2.0
        assert config.request_interval == 2.0
        assert config.http_timeout == 30.0


class TestSecretMasking:
    """Tests for secret masking utility."""

    def test_mask_secrets_hides_auth_query_value(self):
        message = "401 for url: https://elite.finviz.com/export.ashx?v=151&auth=abc123&ft=4"
        assert "auth=abc123" not in mask_secrets(message)
        assert "auth=***" in mask_secrets(message)

    def test_mask_secrets_empty_string(self):
        assert mask_secrets("") == ""

    def test_mask_secrets_none(self):
        assert mask_secrets(None) is None

    def test_mask_secrets_no_auth(self):
        message = "Connection refused: https://elite.finviz.com/export.ashx"
        assert mask_secrets(message) == message


class TestBuildUrl:
    """Test URL construction for Finviz CSV export API."""

    @pytest.fixture
    def collector(self, db_client):
        config = CollectorConfig(finviz_api_key="test_key_123")
        return DataCollector(db_client=db_client, config=config)

    def test_build_uptrend_url_no_sector(self, collector):
        url = collector._build_uptrend_url()
        assert "/export.ashx" in url
        assert "cap_microover" in url
        assert "sh_avgvol_o100" in url
        assert "sh_price_o10" in url
        assert "ta_highlow52w_a30h" in url
        assert "ta_perf2_4wup" in url
        assert "ta_sma20_pa" in url
        assert "ta_sma200_pa" in url
        assert "ta_sma50_sa200" in url
        # No sector filter
        assert "sec_" not in url

    def test_build_uptrend_url_with_sector(self, collector):
        url = collector._build_uptrend_url(sector="sec_technology")
        assert "sec_technology" in url
        # All uptrend filters still present
        assert "ta_sma50_sa200" in url

    def test_build_total_url_no_sector(self, collector):
        url = collector._build_total_url()
        assert "cap_microover" in url
        assert "sh_avgvol_o100" in url
        assert "sh_price_o10" in url
        # No technical filters
        assert "ta_highlow52w_a30h" not in url
        assert "ta_sma50_sa200" not in url

    def test_build_total_url_with_sector(self, collector):
        url = collector._build_total_url(sector="sec_financial")
        assert "sec_financial" in url
        assert "cap_microover" in url
        # No technical filters
        assert "ta_sma50_sa200" not in url

    def test_url_contains_auth_key(self, collector):
        url = collector._build_uptrend_url()
        assert "auth=test_key_123" in url

    def test_url_uses_export_endpoint(self, collector):
        url = collector._build_uptrend_url()
        assert url.startswith("https://elite.finviz.com/export.ashx?")
        assert "v=151" in url
        assert "ft=4" in url

    def test_build_url_with_industry(self, collector):
        """Industry filter should be included in the URL."""
        url = collector._build_uptrend_url(sector="ind_semiconductors")
        assert "ind_semiconductors" in url
        assert "ta_sma50_sa200" in url


def _csv_response(csv_text, status_code=200):
    """Helper to create a mock response with CSV content."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.content = csv_text.encode("utf-8")
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
    return resp


SAMPLE_CSV = "No.,Ticker,Company,Sector\n1,AAPL,Apple Inc.,Technology\n2,MSFT,Microsoft,Technology\n3,GOOGL,Alphabet,Technology\n"
EMPTY_CSV = "No.,Ticker,Company,Sector\n"


class TestFetchStockCount:
    """Test HTTP fetching and CSV parsing."""

    @pytest.fixture
    def collector(self, db_client):
        config = CollectorConfig(
            finviz_api_key="test_key",
            max_retries=3,
            retry_delay=0.01,
            request_interval=0.0,
        )
        return DataCollector(db_client=db_client, config=config)

    def test_fetch_stock_count_success(self, collector, mocker):
        mock_get = mocker.patch.object(
            collector._session, "get",
            side_effect=[_csv_response(SAMPLE_CSV), _csv_response(SAMPLE_CSV)],
        )
        count, total = collector._fetch_stock_count()
        assert count == 3
        assert total == 3
        assert mock_get.call_count == 2

    def test_fetch_stock_count_retry_on_429(self, collector, mocker):
        resp_429 = _csv_response("", status_code=429)
        resp_ok = _csv_response(SAMPLE_CSV)
        mocker.patch.object(
            collector._session, "get",
            side_effect=[resp_429, resp_ok, resp_ok],
        )
        count, total = collector._fetch_stock_count()
        assert count == 3
        assert total == 3

    def test_fetch_stock_count_zero_results(self, collector, mocker):
        mocker.patch.object(
            collector._session, "get",
            side_effect=[_csv_response(EMPTY_CSV), _csv_response(SAMPLE_CSV)],
        )
        count, total = collector._fetch_stock_count()
        assert count == 0
        assert total == 3

    def test_fetch_stock_count_max_retries(self, collector, mocker):
        resp_429 = _csv_response("", status_code=429)
        mocker.patch.object(
            collector._session, "get",
            return_value=resp_429,
        )
        with pytest.raises(requests.HTTPError):
            collector._fetch_stock_count()

    def test_fetch_stock_count_network_error(self, collector, mocker):
        mocker.patch.object(
            collector._session, "get",
            side_effect=[
                requests.ConnectionError("network down"),
                _csv_response(SAMPLE_CSV),
                _csv_response(SAMPLE_CSV),
            ],
        )
        count, total = collector._fetch_stock_count()
        assert count == 3
        assert total == 3

    def test_make_request_empty_csv_body_rejected(self, collector, mocker):
        """v5.5: 200 + empty body is not a zero-result export (that is header-only)."""
        resp = MagicMock(spec=requests.Response)
        resp.status_code = 200
        resp.content = b""
        resp.raise_for_status = MagicMock()
        mocker.patch.object(collector._session, "get", return_value=resp)
        with pytest.raises(dc_module.InvalidFinvizResponse):
            collector._make_request("http://example.com")

    def test_make_request_retries_on_500(self, collector, mocker):
        """Fix 3: 5xx errors should trigger retry."""
        resp_500 = _csv_response("", status_code=500)
        resp_ok = _csv_response(SAMPLE_CSV)
        mocker.patch.object(
            collector._session, "get",
            side_effect=[resp_500, resp_ok],
        )
        mocker.patch("time.sleep")
        result = collector._make_request("http://example.com")
        assert len(result) == 3

    def test_make_request_jitter_applied(self, collector, mocker):
        """Fix 3: Sleep delay should include jitter (not exact delay)."""
        resp_429 = _csv_response("", status_code=429)
        resp_ok = _csv_response(SAMPLE_CSV)
        mocker.patch.object(
            collector._session, "get",
            side_effect=[resp_429, resp_ok],
        )
        mock_sleep = mocker.patch("time.sleep")
        mocker.patch("random.uniform", return_value=0.001)
        collector._make_request("http://example.com")
        # With jitter, sleep value should be delay + jitter, not exact delay
        actual_sleep = mock_sleep.call_args[0][0]
        assert actual_sleep != collector._config.retry_delay
        assert actual_sleep > collector._config.retry_delay

    def test_session_closed(self, db_client):
        """Fix 8: close() should close the underlying Session."""
        config = CollectorConfig(finviz_api_key="test_key")
        collector = DataCollector(db_client=db_client, config=config)
        mock_session = MagicMock()
        collector._session = mock_session
        collector.close()
        mock_session.close.assert_called_once()


class TestCollectWorkflow:
    """Test collection workflow with DB integration."""

    @pytest.fixture
    def collector(self, db_client):
        config = CollectorConfig(
            finviz_api_key="test_key",
            max_retries=3,
            retry_delay=0.01,
            request_interval=0.0,
        )
        return DataCollector(db_client=db_client, config=config)

    def test_collect_worksheet(self, collector, db_client, mocker):
        mocker.patch.object(
            collector._session, "get",
            side_effect=[_csv_response(SAMPLE_CSV), _csv_response(SAMPLE_CSV)],
        )
        count, total = collector.collect_worksheet("all", date="2026-11-13")
        assert count == 3
        assert total == 3
        # Verify data was written to DB
        df = db_client.fetch_raw_data("all")
        assert len(df) == 1
        assert df.iloc[0]["count"] == 3
        assert df.iloc[0]["total"] == 3

    def test_collect_worksheet_empty_raises(self, collector, db_client, mocker):
        """total=0 for 'all' or sec_* should raise ValueError (API failure indicator)."""
        mocker.patch.object(
            collector._session, "get",
            side_effect=[_csv_response(EMPTY_CSV), _csv_response(EMPTY_CSV)],
        )
        with pytest.raises(ValueError, match="Empty data"):
            collector.collect_worksheet("all", date="2026-11-13")
        # No data written
        df = db_client.fetch_raw_data("all")
        assert len(df) == 0

    def test_collect_worksheet_industry_total_zero_skips_without_raise(
        self, collector, db_client, mocker
    ):
        """total=0 for ind_* is legitimate (base filters may exclude all stocks in
        small industries like ind_pharmaceuticalretailers). Should log warning, skip
        DB write, and return (0, 0) without raising."""
        mocker.patch.object(
            collector._session, "get",
            side_effect=[_csv_response(EMPTY_CSV), _csv_response(EMPTY_CSV)],
        )
        count, total = collector.collect_worksheet(
            "ind_pharmaceuticalretailers", date="2026-11-13"
        )
        assert count == 0
        assert total == 0
        # No data written
        df = db_client.fetch_raw_data("ind_pharmaceuticalretailers")
        assert len(df) == 0

    def test_collect_worksheet_dry_run_total_zero(self, collector, db_client, mocker):
        """dry_run + total=0 should succeed (no raise, no DB write)."""
        mocker.patch.object(
            collector._session, "get",
            side_effect=[_csv_response(EMPTY_CSV), _csv_response(EMPTY_CSV)],
        )
        count, total = collector.collect_worksheet("all", date="2026-11-13", dry_run=True)
        assert count == 0
        assert total == 0

    def test_collect_all(self, collector, mocker):
        mocker.patch.object(
            collector._session, "get",
            return_value=_csv_response(SAMPLE_CSV),
        )
        result = collector.collect_all(date="2026-11-13")
        assert isinstance(result, CollectResult)
        # 161 worksheets: 'all' + 11 sectors + 149 industries
        assert len(result.succeeded) == 161
        assert len(result.failed) == 0
        for ws, (count, total) in result.succeeded.items():
            assert count == 3
            assert total == 3

    def test_collect_all_continue_on_error(self, collector, mocker):
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # Fail on the first call only (first worksheet's uptrend request)
            if call_count == 1:
                raise requests.ConnectionError("network down")
            return _csv_response(SAMPLE_CSV)

        mocker.patch.object(collector._session, "get", side_effect=side_effect)
        mocker.patch.object(collector._config, "max_retries", 1)
        result = collector.collect_all(date="2026-11-13")
        # First worksheet ("all") failed, remaining 160 should succeed
        assert len(result.succeeded) == 160
        assert len(result.failed) == 1

    def test_collect_worksheet_invalid(self, collector):
        with pytest.raises(ValueError, match="Invalid worksheet"):
            collector.collect_worksheet("invalid_sheet")

    def test_validate_counts_negative(self, collector, mocker):
        """Fix 4: Negative count/total should raise ValueError."""
        mocker.patch.object(
            collector, "_fetch_stock_count", return_value=(-1, 100),
        )
        with pytest.raises(ValueError, match="negative"):
            collector.collect_worksheet("all", date="2026-11-13")

    def test_validate_counts_count_exceeds_total(self, collector, mocker):
        """Fix 4: count > total should raise ValueError."""
        mocker.patch.object(
            collector, "_fetch_stock_count", return_value=(200, 100),
        )
        with pytest.raises(ValueError, match="exceeds total"):
            collector.collect_worksheet("all", date="2026-11-13")

    def test_collect_worksheet_dry_run(self, collector, db_client, mocker):
        """Fix 7: dry_run=True should skip DB write but run validation."""
        mocker.patch.object(
            collector._session, "get",
            side_effect=[_csv_response(SAMPLE_CSV), _csv_response(SAMPLE_CSV)],
        )
        count, total = collector.collect_worksheet("all", date="2026-11-13", dry_run=True)
        assert count == 3
        assert total == 3
        # No data written to DB
        df = db_client.fetch_raw_data("all")
        assert len(df) == 0

    def test_collect_all_dry_run(self, collector, mocker):
        """Fix 7: collect_all dry_run=True should skip DB writes."""
        mocker.patch.object(
            collector._session, "get",
            return_value=_csv_response(SAMPLE_CSV),
        )
        mock_upsert = mocker.patch.object(collector._db, "upsert_raw_data")
        result = collector.collect_all(date="2026-11-13", dry_run=True)
        assert len(result.succeeded) == 161
        mock_upsert.assert_not_called()

    def test_collect_worksheet_industry(self, collector, db_client, mocker):
        """collect_worksheet should accept ind_* worksheets."""
        mocker.patch.object(
            collector._session, "get",
            side_effect=[_csv_response(SAMPLE_CSV), _csv_response(SAMPLE_CSV)],
        )
        count, total = collector.collect_worksheet("ind_semiconductors", date="2026-11-13")
        assert count == 3
        assert total == 3
        df = db_client.fetch_raw_data("ind_semiconductors")
        assert len(df) == 1

    def test_collect_all_scope_sectors(self, collector, mocker):
        """scope=SECTORS should collect only 'all' + 11 sectors (12 worksheets)."""
        mocker.patch.object(
            collector._session, "get",
            return_value=_csv_response(SAMPLE_CSV),
        )
        result = collector.collect_all(date="2026-11-13", scope=CollectScope.SECTORS)
        assert len(result.succeeded) == 12
        assert all(
            k == "all" or k.startswith("sec_") for k in result.succeeded
        )

    def test_collect_all_scope_industries(self, collector, mocker):
        """scope=INDUSTRIES should collect only 149 industry worksheets."""
        mocker.patch.object(
            collector._session, "get",
            return_value=_csv_response(SAMPLE_CSV),
        )
        result = collector.collect_all(date="2026-11-13", scope=CollectScope.INDUSTRIES)
        assert len(result.succeeded) == 149
        assert all(k.startswith("ind_") for k in result.succeeded)

    def test_collect_all_returns_collect_result(self, collector, mocker):
        """collect_all should return a CollectResult with succeeded/failed."""
        mocker.patch.object(
            collector._session, "get",
            return_value=_csv_response(SAMPLE_CSV),
        )
        result = collector.collect_all(date="2026-11-13", scope=CollectScope.SECTORS)
        assert isinstance(result, CollectResult)
        assert hasattr(result, "succeeded")
        assert hasattr(result, "failed")

    def test_collect_result_sector_industry_split(self):
        """CollectResult should separate sector/industry in its properties."""
        result = CollectResult(
            succeeded={
                "all": (100, 500),
                "sec_technology": (50, 200),
                "ind_semiconductors": (30, 60),
            },
            failed=["sec_financial", "ind_banksregional"],
        )
        assert set(result.sector_succeeded.keys()) == {"all", "sec_technology"}
        assert set(result.industry_succeeded.keys()) == {"ind_semiconductors"}
        assert result.sector_failed == ["sec_financial"]
        assert result.industry_failed == ["ind_banksregional"]


class TestCLI:
    """Test collect.py CLI entrypoint."""

    def test_cli_default_collect_all(self, tmp_db, mocker):
        from src.constants import VALID_WORKSHEETS as ws_list
        mocker.patch("sys.argv", ["collect.py", "--db", tmp_db])
        mocker.patch.dict("os.environ", {"FINVIZ_API_KEY": "test_key"})
        mock_collect_all = mocker.patch(
            "src.data_collector.DataCollector.collect_all",
            return_value=CollectResult(
                succeeded={ws: (100, 500) for ws in ws_list},
                failed=[],
            ),
        )
        from collect import main
        main()
        mock_collect_all.assert_called_once()

    def test_cli_missing_api_key(self, tmp_db, mocker):
        mocker.patch("sys.argv", ["collect.py", "--db", tmp_db])
        mocker.patch.dict("os.environ", {}, clear=True)
        # Also ensure dotenv doesn't load a real key
        mocker.patch("collect.load_dotenv")
        from collect import main
        with pytest.raises(SystemExit):
            main()

    def test_cli_dry_run(self, tmp_db, mocker):
        mocker.patch("sys.argv", ["collect.py", "--db", tmp_db, "--dry-run"])
        mocker.patch.dict("os.environ", {"FINVIZ_API_KEY": "test_key"})
        mock_collect_all = mocker.patch(
            "src.data_collector.DataCollector.collect_all",
            return_value=CollectResult(
                succeeded={"all": (100, 500)},
                failed=[],
            ),
        )
        mock_upsert = mocker.patch("src.db_client.DBClient.upsert_raw_data")
        from collect import main
        main()
        # collect_all called with dry_run=True and scope
        mock_collect_all.assert_called_once_with(
            date="2026-11-13", dry_run=True, scope=CollectScope.ALL,
        )
        mock_upsert.assert_not_called()

    def test_cli_exit_code_complete_failure(self, tmp_db, mocker):
        mocker.patch("sys.argv", ["collect.py", "--db", tmp_db])
        mocker.patch.dict("os.environ", {"FINVIZ_API_KEY": "test_key"})
        mocker.patch(
            "src.data_collector.DataCollector.collect_all",
            return_value=CollectResult(succeeded={}, failed=["all"] + list(__import__("src.constants", fromlist=["SECTORS"]).SECTORS)),
        )
        from collect import main
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    def test_cli_exit_code_partial_failure(self, tmp_db, mocker):
        """Sector partial failure should exit 2."""
        mocker.patch("sys.argv", ["collect.py", "--db", tmp_db])
        mocker.patch.dict("os.environ", {"FINVIZ_API_KEY": "test_key"})
        mocker.patch(
            "src.data_collector.DataCollector.collect_all",
            return_value=CollectResult(
                succeeded={"all": (100, 500), "sec_technology": (50, 200)},
                failed=["sec_financial"],
            ),
        )
        from collect import main
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 2

    def test_cli_worksheet_error_exit_code(self, tmp_db, mocker):
        mocker.patch("sys.argv", [
            "collect.py", "--db", tmp_db, "--worksheet", "all",
        ])
        mocker.patch.dict("os.environ", {"FINVIZ_API_KEY": "test_key"})
        mocker.patch(
            "src.data_collector.DataCollector.collect_worksheet",
            side_effect=requests.ConnectionError("network down"),
        )
        from collect import main
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    def test_cli_invalid_date_format(self, tmp_db, mocker):
        """Fix 5: Invalid date format should exit 1."""
        mocker.patch("sys.argv", [
            "collect.py", "--db", tmp_db, "--date", "2026-99-99",
        ])
        mocker.patch.dict("os.environ", {"FINVIZ_API_KEY": "test_key"})
        from collect import main
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    def test_cli_scope_argument(self, tmp_db, mocker):
        """--scope sectors should pass CollectScope.SECTORS to collect_all."""
        from src.constants import SECTORS
        mocker.patch("sys.argv", ["collect.py", "--db", tmp_db, "--scope", "sectors"])
        mocker.patch.dict("os.environ", {"FINVIZ_API_KEY": "test_key"})
        sector_results = {"all": (100, 500)}
        for sec in SECTORS:
            sector_results[sec] = (50, 200)
        mock_collect_all = mocker.patch(
            "src.data_collector.DataCollector.collect_all",
            return_value=CollectResult(succeeded=sector_results, failed=[]),
        )
        from collect import main
        main()
        mock_collect_all.assert_called_once_with(
            date="2026-11-13", dry_run=False, scope=CollectScope.SECTORS,
        )

    def test_cli_scope_worksheet_simultaneous_error(self, tmp_db, mocker):
        """--worksheet and --scope cannot be used together (any scope value)."""
        mocker.patch.dict("os.environ", {"FINVIZ_API_KEY": "test_key"})
        from collect import main

        # --scope sectors (non-default)
        mocker.patch("sys.argv", [
            "collect.py", "--db", tmp_db,
            "--worksheet", "all", "--scope", "sectors",
        ])
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

        # --scope all (previously allowed, now also rejected)
        mocker.patch("sys.argv", [
            "collect.py", "--db", tmp_db,
            "--worksheet", "all", "--scope", "all",
        ])
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    def test_cli_scope_all_sector_partial_fail_exit2(self, tmp_db, mocker):
        """Default scope: sector partial failure should exit 2."""
        mocker.patch("sys.argv", ["collect.py", "--db", tmp_db])
        mocker.patch.dict("os.environ", {"FINVIZ_API_KEY": "test_key"})
        mocker.patch(
            "src.data_collector.DataCollector.collect_all",
            return_value=CollectResult(
                succeeded={"all": (100, 500)},
                failed=["sec_technology"],
            ),
        )
        from collect import main
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 2

    def test_cli_scope_all_industry_partial_fail_exit2(self, tmp_db, mocker):
        """Default scope: partial industry failure with all sectors OK should exit 2."""
        from src.constants import SECTORS
        mocker.patch("sys.argv", ["collect.py", "--db", tmp_db])
        mocker.patch.dict("os.environ", {"FINVIZ_API_KEY": "test_key"})
        sector_results = {"all": (100, 500)}
        for sec in SECTORS:
            sector_results[sec] = (50, 200)
        # Some industries succeeded, some failed → partial failure → exit 2
        sector_results["ind_softwareapplication"] = (30, 100)
        mocker.patch(
            "src.data_collector.DataCollector.collect_all",
            return_value=CollectResult(
                succeeded=sector_results,
                failed=["ind_semiconductors", "ind_banksregional"],
            ),
        )
        from collect import main
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 2

    def test_cli_scope_all_industry_all_fail_exit2(self, tmp_db, mocker):
        """Default scope: all sectors OK but ALL industries failed should exit 2."""
        from src.constants import SECTORS, INDUSTRIES
        mocker.patch("sys.argv", ["collect.py", "--db", tmp_db])
        mocker.patch.dict("os.environ", {"FINVIZ_API_KEY": "test_key"})
        sector_results = {"all": (100, 500)}
        for sec in SECTORS:
            sector_results[sec] = (50, 200)
        mocker.patch(
            "src.data_collector.DataCollector.collect_all",
            return_value=CollectResult(
                succeeded=sector_results,
                failed=list(INDUSTRIES),
            ),
        )
        from collect import main
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 2

    def test_cli_scope_industries_partial_fail_exit2(self, tmp_db, mocker):
        """--scope industries: partial failure should exit 2."""
        mocker.patch("sys.argv", ["collect.py", "--db", tmp_db, "--scope", "industries"])
        mocker.patch.dict("os.environ", {"FINVIZ_API_KEY": "test_key"})
        mocker.patch(
            "src.data_collector.DataCollector.collect_all",
            return_value=CollectResult(
                succeeded={"ind_semiconductors": (30, 60)},
                failed=["ind_banksregional"],
            ),
        )
        from collect import main
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 2


class TestRedact:
    """Tests for the redact() helper."""

    KEY = "SYNTHETIC_TEST_KEY"

    def test_redact_literal_secret(self):
        out = redact(f"auth={self.KEY}", [self.KEY])
        assert self.KEY not in out
        assert "***" in out

    def test_redact_auth_token(self):
        out = redact("https://host/export.ashx?v=1&auth=abc123&ft=4")
        assert "abc123" not in out
        assert "auth=***" in out

    def test_redact_keeps_plain_text(self):
        assert redact("connection refused") == "connection refused"

    def test_redact_type_safe_for_non_string(self):
        assert redact(42, [self.KEY]) == 42
        assert redact(None, [self.KEY]) is None


class TestRedactingFilter:
    """Tests for the handler-level RedactingFilter."""

    KEY = "SYNTHETIC_TEST_KEY"

    def _capture(self, filter_):
        stream = io.StringIO()
        hdlr = logging.StreamHandler(stream)
        hdlr.setLevel(logging.DEBUG)
        hdlr.addFilter(filter_)
        return stream, hdlr

    def test_filter_scrubs_msg_and_args_tuple(self):
        stream, hdlr = self._capture(RedactingFilter([self.KEY]))
        rec = logging.LogRecord(
            "test", logging.DEBUG, __file__, 1,
            "https://elite.finviz.com%s",
            (f"/export.ashx?v=151&auth={self.KEY}&ft=4",),
            None,
        )
        hdlr.handle(rec)
        assert self.KEY not in stream.getvalue()
        assert "auth=***" in stream.getvalue()

    def test_filter_scrubs_dict_args(self):
        stream, hdlr = self._capture(RedactingFilter([self.KEY]))
        rec = logging.LogRecord(
            "test", logging.DEBUG, __file__, 1,
            "%(url)s",
            ({"url": f"auth={self.KEY}"},),
            None,
        )
        hdlr.handle(rec)
        assert self.KEY not in stream.getvalue()

    def test_filter_on_handler_catches_child_logger(self):
        stream, hdlr = self._capture(RedactingFilter([self.KEY]))
        root = logging.getLogger()
        old_handlers = list(root.handlers)
        old_level = root.level
        child = logging.getLogger("urllib3.connectionpool")
        old_child_level = child.level
        try:
            root.handlers = [hdlr]
            root.setLevel(logging.DEBUG)
            child.setLevel(logging.DEBUG)
            child.propagate = True
            child.debug(
                "HTTPSConnectionPool: %s",
                f"/export.ashx?v=151&auth={self.KEY}&ft=4",
            )
        finally:
            root.handlers = old_handlers
            root.setLevel(old_level)
            child.setLevel(old_child_level)
        assert self.KEY not in stream.getvalue()
        assert "auth=***" in stream.getvalue()


class TestConfigureLogging:
    """Tests for configure_logging secret wiring."""

    KEY = "SYNTHETIC_TEST_KEY"

    def test_attaches_filter_to_existing_root_handlers(self):
        root = logging.getLogger()
        old_handlers = list(root.handlers)
        old_filters = list(root.filters)
        tmp = logging.StreamHandler(io.StringIO())
        root.handlers = [tmp]
        try:
            configure_logging(True, [self.KEY])
            assert any(
                isinstance(f, RedactingFilter) and self.KEY in f.secrets
                for f in tmp.filters
            )
        finally:
            root.handlers = old_handlers
            root.filters = old_filters


def _http_error_resp(url, status_code=401, reason="Unauthorized", body=""):
    """Build a mock response whose raise_for_status raises an HTTPError whose
    message carries the given URL (used to exercise secret sanitization)."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.reason = reason
    resp.url = url
    resp.content = body.encode("utf-8")

    def _raise():
        raise requests.HTTPError(f"{status_code} {reason} for url: {url}", response=resp)

    resp.raise_for_status = _raise
    return resp


class TestVerboseSecretLeak:
    """Issue #1 A01: the synthetic key must never appear in logs or tracebacks
    under verbose collection across all failure scenarios (non-vacuous)."""

    KEY = "SYNTHETIC_TEST_KEY"

    @pytest.fixture
    def collector(self, db_client):
        config = CollectorConfig(
            finviz_api_key=self.KEY,
            max_retries=2,
            retry_delay=0.01,
            request_interval=0.0,
        )
        return DataCollector(db_client=db_client, config=config)

    def _assert_no_key(self, exc, caplog):
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        assert self.KEY not in tb, "secret leaked into exception traceback"
        assert self.KEY not in caplog.text, "secret leaked into log records"
        assert exc.__cause__ is None and exc.__suppress_context__, (
            "secret-bearing exception chain not suppressed"
        )

    def test_connection_error_leak(self, collector, caplog, mocker):
        caplog.set_level(logging.DEBUG)
        caplog.handler.addFilter(RedactingFilter([self.KEY]))
        mocker.patch.object(collector._config, "max_retries", 1)
        mocker.patch.object(
            collector._session, "get",
            side_effect=requests.ConnectionError(
                f"Max retries exceeded with url: /export.ashx?v=151&auth={self.KEY}&ft=4"
            ),
        )
        with pytest.raises(requests.ConnectionError) as excinfo:
            collector.collect_worksheet("all", date="2026-11-13")
        self._assert_no_key(excinfo.value, caplog)

    def test_timeout_leak(self, collector, caplog, mocker):
        caplog.set_level(logging.DEBUG)
        caplog.handler.addFilter(RedactingFilter([self.KEY]))
        mocker.patch.object(collector._config, "max_retries", 1)
        mocker.patch.object(
            collector._session, "get",
            side_effect=requests.Timeout(
                f"Max retries exceeded with url: /export.ashx?v=151&auth={self.KEY}&ft=4"
            ),
        )
        with pytest.raises(requests.Timeout) as excinfo:
            collector.collect_worksheet("all", date="2026-11-13")
        self._assert_no_key(excinfo.value, caplog)

    def test_401_leak(self, collector, caplog, mocker):
        caplog.set_level(logging.DEBUG)
        caplog.handler.addFilter(RedactingFilter([self.KEY]))
        url = f"https://elite.finviz.com/export.ashx?v=151&auth={self.KEY}&ft=4"
        mocker.patch.object(
            collector._session, "get",
            return_value=_http_error_resp(url, status_code=401, reason="Unauthorized"),
        )
        with pytest.raises(requests.RequestException) as excinfo:
            collector.collect_worksheet("all", date="2026-11-13")
        self._assert_no_key(excinfo.value, caplog)
        assert "HTTP 401" in str(excinfo.value)

    def test_exhausted_5xx_leak(self, collector, caplog, mocker):
        caplog.set_level(logging.DEBUG)
        caplog.handler.addFilter(RedactingFilter([self.KEY]))
        url = f"https://elite.finviz.com/export.ashx?v=151&auth={self.KEY}&ft=4"
        mocker.patch.object(
            collector._session, "get",
            return_value=_http_error_resp(url, status_code=502, reason="Bad Gateway"),
        )
        with pytest.raises(requests.RequestException) as excinfo:
            collector.collect_worksheet("all", date="2026-11-13")
        self._assert_no_key(excinfo.value, caplog)
        assert "HTTP 502" in str(excinfo.value)

    def test_uncaught_request_exception_leak(self, collector, caplog, mocker):
        caplog.set_level(logging.DEBUG)
        caplog.handler.addFilter(RedactingFilter([self.KEY]))
        mocker.patch.object(collector._config, "max_retries", 1)
        mocker.patch.object(
            collector._session, "get",
            side_effect=requests.TooManyRedirects(
                f"Exceeded 30 redirects for url: /export.ashx?auth={self.KEY}"
            ),
        )
        with pytest.raises(requests.TooManyRedirects) as excinfo:
            collector.collect_worksheet("all", date="2026-11-13")
        self._assert_no_key(excinfo.value, caplog)

    def test_successful_verbose_run_has_no_key(self, collector, caplog, mocker):
        caplog.set_level(logging.DEBUG)
        caplog.handler.addFilter(RedactingFilter([self.KEY]))
        mocker.patch.object(
            collector._session, "get",
            side_effect=[_csv_response(SAMPLE_CSV), _csv_response(SAMPLE_CSV)],
        )
        count, total = collector.collect_worksheet("all", date="2026-11-13")
        assert (count, total) == (3, 3)
        assert self.KEY not in caplog.text

    def test_diagnostics_retained(self, collector, caplog, mocker):
        caplog.set_level(logging.DEBUG)
        caplog.handler.addFilter(RedactingFilter([self.KEY]))
        mocker.patch.object(
            collector._session, "get",
            side_effect=[
                _http_error_resp("http://x", status_code=502, reason="Bad Gateway"),
                _http_error_resp("http://x", status_code=502, reason="Bad Gateway"),
            ],
        )
        with pytest.raises(requests.RequestException):
            collector.collect_worksheet("all", date="2026-11-13")
        assert "HTTP 502" in caplog.text
        assert "attempt 1/2" in caplog.text


@pytest.fixture
def configured_log_stream():
    root = logging.getLogger()
    handlers, filters, level = list(root.handlers), list(root.filters), root.level
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.handlers = [handler]
    root.setLevel(logging.DEBUG)
    try:
        configure_logging(True, ["BOUNDARY_SYNTHETIC_KEY"])
        yield stream
    finally:
        root.handlers, root.filters = handlers, filters
        root.setLevel(level)


def test_config_repr_excludes_credential():
    assert "BOUNDARY_SYNTHETIC_KEY" not in repr(CollectorConfig("BOUNDARY_SYNTHETIC_KEY"))


def test_configured_logging_renders_objects_and_templates(configured_log_stream, capsys):
    key = "BOUNDARY_SYNTHETIC_KEY"
    log = logging.getLogger("boundary.collector")
    log.debug("config=%r", CollectorConfig(key))
    log.debug("payload=%s", {"nested": {"api_key": key}})
    log.debug({"api_key": key})
    log.debug("request auth=%s attempt=%d", key, 1)
    log.debug("request auth=%(key)s attempt=%(attempt)d", {"key": key, "attempt": 2})
    output = configured_log_stream.getvalue()
    assert key not in output
    assert "payload=" in output
    assert "attempt=1" in output and "attempt=2" in output
    assert "Logging error" not in capsys.readouterr().err


@pytest.mark.parametrize("cached", [False, True])
def test_configured_logging_sanitizes_chained_traceback(configured_log_stream, cached):
    import sys
    key = "BOUNDARY_SYNTHETIC_KEY"
    try:
        try:
            raise requests.ConnectionError("connection auth=" + key)
        except requests.ConnectionError as exc:
            raise RuntimeError("retry " + key) from exc
    except RuntimeError:
        record = logging.LogRecord("boundary.collector", logging.ERROR, __file__, 1,
                                   "request failed", (), sys.exc_info())
        if cached:
            logging.Formatter().format(record)
        logging.getLogger().handle(record)
    output = configured_log_stream.getvalue()
    assert key not in output
    assert "Traceback" in output and "ConnectionError" in output and "RuntimeError" in output
    assert "request failed" in output


class _RaisingRepr:
    def __repr__(self):
        raise ValueError("bad repr")


@pytest.mark.parametrize(
    "msg, args",
    [
        ("too many args", (1,)),
        ("value=%d auth=BOUNDARY_SYNTHETIC_KEY", ("not-a-number",)),
        ("object=%r", (_RaisingRepr(),)),
    ],
)
def test_malformed_log_call_does_not_raise_or_leak(configured_log_stream, capsys, msg, args):
    log = logging.getLogger("boundary.collector")
    log.debug(msg, *args)
    log.debug("still logging")
    output = configured_log_stream.getvalue()
    assert "BOUNDARY_SYNTHETIC_KEY" not in output
    assert "test_data_collector.py" in output
    assert "still logging" in output
    assert "BOUNDARY_SYNTHETIC_KEY" not in capsys.readouterr().err


@pytest.mark.parametrize("bad_exc_info", [("a", "b", "c"), (1, 2, 3), (ValueError, ValueError("x"), "tb")])
def test_malformed_exc_info_does_not_raise(configured_log_stream, bad_exc_info):
    log = logging.getLogger("boundary.collector")
    log.debug("message kept auth=BOUNDARY_SYNTHETIC_KEY", exc_info=bad_exc_info)
    output = configured_log_stream.getvalue()
    assert "message kept" in output
    assert "Unformattable exception info" in output
    assert "BOUNDARY_SYNTHETIC_KEY" not in output


def test_unformattable_message_object_does_not_raise(configured_log_stream):
    class RaisingStr:
        def __str__(self):
            raise ValueError("bad str")

    logging.getLogger("boundary.collector").debug(RaisingStr())
    assert "RaisingStr" in configured_log_stream.getvalue()


def test_missing_api_key_error_uses_configured_format():
    repo_root = Path(__file__).resolve().parent.parent
    env = {**os.environ, "FINVIZ_API_KEY": ""}
    result = subprocess.run(
        [sys.executable, "collect.py"],
        cwd=repo_root, env=env, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 1
    assert "ERROR: FINVIZ_API_KEY environment variable is not set" in result.stderr


# ---------------------------------------------------------------------------
# Issue #2 A02: Finviz CSV response contract (v5.5)
# ---------------------------------------------------------------------------

HEADER = "No.,Ticker,Company,Sector"
VALID_ROWS = "1,AAPL,Apple Inc.,Technology\n2,MSFT,Microsoft,Technology\n"


def _parse(body):
    if isinstance(body, str):
        body = body.encode("utf-8")
    return dc_module.parse_finviz_export(body)


def _assert_invalid(body):
    with pytest.raises(dc_module.InvalidFinvizResponse):
        _parse(body)


class TestFinvizResponseContract:
    """A body is counted only if it satisfies the documented export contract."""

    def test_invalid_response_is_value_error(self):
        # collect_all classifies ValueError as a worksheet failure.
        assert issubclass(dc_module.InvalidFinvizResponse, ValueError)

    def test_plain_error_text_rejected(self):
        _assert_invalid("error\nsubscription expired\n")

    @pytest.mark.parametrize("body", [
        "<!DOCTYPE html><html><body>Login</body></html>\n",
        "  \n<html>\n<head></head>\n</html>\n",
        "\ufeff<html><body>Please log in</body></html>",
    ])
    def test_markup_rejected(self, body):
        _assert_invalid(body)

    @pytest.mark.parametrize("body", [
        "<html>,Ticker\n1,AAPL\n",
        "  <p>No.,Ticker,Company</p>\n",
    ])
    def test_markup_with_ticker_header_rejected(self, body):
        # Rule 3 on its own: these bodies would satisfy the Ticker rule.
        _assert_invalid(body)

    def test_bom_before_ticker_column_is_stripped(self):
        df = _parse("\ufeffTicker,Company\nAAPL,Apple\n")
        assert df["Ticker"].tolist() == ["AAPL"]

    def test_header_names_are_stripped(self):
        df = _parse('"No."," Ticker ",Company\n1,AAPL,x\n')
        assert df["Ticker"].tolist() == ["AAPL"]

    @pytest.mark.parametrize("body", ["", "   \n\r\n\t"])
    def test_empty_body_rejected(self, body):
        _assert_invalid(body)

    def test_non_utf8_rejected(self):
        with pytest.raises(dc_module.InvalidFinvizResponse):
            dc_module.parse_finviz_export(
                (HEADER + "\n1,ABC,Soci\xe9t\xe9,Industrials\n").encode("latin-1")
            )

    def test_strict_quoting_failure_rejected(self):
        _assert_invalid(HEADER + '\n1,LOW,"Lowe"s,Consumer Cyclical\n')

    @pytest.mark.parametrize("rows", [
        "1,AAPL,Apple Inc.,Technology,EXTRA\n2,MSFT,Microsoft,Technology\n",
        "1,AAPL,Apple Inc.,Technology\n2,MSFT,Microsoft,Technology,EXTRA\n",
        "1,AAPL,Apple Inc.,Technology\n2,MSFT,Microsoft\n",
        "1,AAPL,Apple Inc.,Technology\n   \n",
    ])
    def test_field_count_mismatch_rejected(self, rows):
        _assert_invalid(HEADER + "\n" + rows)

    def test_two_ticker_columns_rejected(self):
        _assert_invalid("No.,Ticker,ticker\n1,AAPL,MSFT\n")

    def test_missing_ticker_column_rejected(self):
        _assert_invalid("No.,Symbol,Company\n1,AAPL,Apple\n")

    def test_other_duplicate_column_names_allowed(self):
        df = _parse("No.,Ticker,Price,Price\n1,AAPL,10,11\n")
        assert len(df) == 1

    @pytest.mark.parametrize("ticker", ["", " AAPL", "AAPL ", "AA PL", "AA\x00PL", "AA\tPL"])
    def test_bad_ticker_value_rejected(self, ticker):
        _assert_invalid(f"{HEADER}\n1,{ticker},Apple Inc.,Technology\n")

    def test_duplicate_tickers_rejected(self):
        _assert_invalid(HEADER + "\n1,AAPL,Apple,Technology\n2,AAPL,Apple,Technology\n")

    def test_header_only_is_zero_rows(self):
        df = _parse(HEADER + "\n")
        assert len(df) == 0
        assert "Ticker" in df.columns

    def test_header_only_without_trailing_newline(self):
        assert len(_parse(HEADER)) == 0

    def test_valid_export_counts_rows(self):
        assert len(_parse(HEADER + "\n" + VALID_ROWS)) == 2

    def test_quoted_header_and_bom(self):
        body = '\ufeff"No.","Ticker","Company","Sector"\n"1","AAPL","Apple Inc.","Technology"\n'
        df = _parse(body)
        assert df["Ticker"].tolist() == ["AAPL"]

    def test_na_like_tickers_kept_as_strings(self):
        body = HEADER + "\n1,NA,Nano Labs,Technology\n2,NULL,x,y\n3,None,x,y\n4,BRK-B,Berkshire,Financial\n"
        df = _parse(body)
        assert df["Ticker"].tolist() == ["NA", "NULL", "None", "BRK-B"]

    def test_crlf_and_interior_empty_line(self):
        body = HEADER + "\r\n1,AAPL,Apple,Technology\r\n\r\n2,MSFT,Microsoft,Technology\r\n"
        assert len(_parse(body)) == 2

    def test_leading_empty_lines_before_header(self):
        assert len(_parse("\n\n" + HEADER + "\n" + VALID_ROWS)) == 2

    def test_quoted_fields_with_comma_quote_and_newline(self):
        body = (
            HEADER + "\n"
            '1,LOW,"Lowe""s Companies, Inc.",Consumer Cyclical\n'
            '2,ABC,"Line1\nLine2",Industrials\n'
        )
        df = _parse(body)
        assert df["Ticker"].tolist() == ["LOW", "ABC"]

    def test_make_request_uses_contract(self, db_client, mocker):
        collector = DataCollector(db_client, CollectorConfig(
            finviz_api_key="k", max_retries=1, retry_delay=0.0, request_interval=0.0,
        ))
        mocker.patch.object(collector._session, "get",
                            return_value=_csv_response("error\nsubscription expired\n"))
        with pytest.raises(dc_module.InvalidFinvizResponse):
            collector._make_request("http://example.com")

    def test_invalid_body_is_not_retried(self, db_client, mocker):
        collector = DataCollector(db_client, CollectorConfig(
            finviz_api_key="k", max_retries=3, retry_delay=0.0, request_interval=0.0,
        ))
        get = mocker.patch.object(collector._session, "get",
                                  return_value=_csv_response("<html>maintenance</html>"))
        sleep = mocker.patch("src.data_collector.time.sleep")
        with pytest.raises(dc_module.InvalidFinvizResponse):
            collector._make_request("http://example.com")
        assert get.call_count == 1
        sleep.assert_not_called()

    def test_message_reports_reason_without_body(self):
        with pytest.raises(dc_module.InvalidFinvizResponse) as excinfo:
            _parse("error SECRETBODY auth=LEAKKEY\nsubscription expired SECRETBODY\n")
        assert "SECRETBODY" not in str(excinfo.value)
        assert "LEAKKEY" not in str(excinfo.value)
        assert "ticker" in str(excinfo.value).lower()

    @pytest.mark.parametrize("body", [
        HEADER + "\n1,SECRETBODY,auth=LEAKKEY,x\n2,SECRETBODY,auth=LEAKKEY,x\n",  # duplicate
        HEADER + "\n1,AAPL,SECRETBODY auth=LEAKKEY,x,extra\n",                  # ragged row
        HEADER + '\n1,AAPL,"SECRETBODY"auth=LEAKKEY,x\n',                        # csv.Error
        HEADER + "\n1,SECRET BODY,auth=LEAKKEY,x\n",                             # malformed ticker
        "Ticker,SECRETBODY auth=LEAKKEY,Ticker\n",                               # two ticker columns
    ])
    def test_messages_never_echo_body_text(self, body):
        with pytest.raises(dc_module.InvalidFinvizResponse) as excinfo:
            _parse(body)
        message = str(excinfo.value)
        assert "SECRET" not in message and "LEAKKEY" not in message


class TestInvalidResponseCollection:
    """Invalid bodies never become stored counts."""

    KEY = "A02_SYNTHETIC_KEY"

    @pytest.fixture
    def collector(self, db_client):
        return DataCollector(db_client, CollectorConfig(
            finviz_api_key=self.KEY, max_retries=1, retry_delay=0.0, request_interval=0.0,
        ))

    def test_issue_body_for_all_writes_nothing(self, collector, db_client, mocker):
        mocker.patch.object(collector._session, "get",
                            return_value=_csv_response("error\nsubscription expired\n"))
        result = collector.collect_all(date="2026-11-13", scope=CollectScope.SECTORS)
        assert "all" in result.failed
        assert result.succeeded == {}
        assert db_client.fetch_raw_data("all").empty

    def test_invalid_total_response_writes_nothing(self, collector, db_client, mocker):
        mocker.patch.object(collector._session, "get", side_effect=[
            _csv_response(SAMPLE_CSV), _csv_response("<html>maintenance</html>"),
        ])
        with pytest.raises(dc_module.InvalidFinvizResponse) as excinfo:
            collector.collect_worksheet("all", date="2026-11-13")
        assert "total" in str(excinfo.value)
        assert db_client.fetch_raw_data("all").empty

    def test_invalid_uptrend_response_names_request(self, collector, mocker):
        mocker.patch.object(collector._session, "get",
                            return_value=_csv_response("<html>maintenance</html>"))
        with pytest.raises(dc_module.InvalidFinvizResponse) as excinfo:
            collector.collect_worksheet("all", date="2026-11-13")
        assert "uptrend" in str(excinfo.value)

    def test_one_invalid_industry_fails_only_that_worksheet(self, collector, db_client, mocker):
        bad = "ind_aluminum"

        def fake_get(url, timeout):
            if bad in url:
                return _csv_response(HEADER + '\n1,AA,"Alcoa"x,Basic Materials\n')
            return _csv_response(SAMPLE_CSV)

        mocker.patch.object(collector._session, "get", side_effect=fake_get)
        result = collector.collect_all(date="2026-11-13", scope=CollectScope.INDUSTRIES)
        assert result.failed == [bad]
        assert len(result.succeeded) == len(dc_module.INDUSTRIES) - 1
        assert db_client.fetch_raw_data(bad).empty
        assert not db_client.fetch_raw_data("ind_copper").empty

    @pytest.mark.parametrize("body_template", [
        "<html>Session expired for /export.ashx?auth={key} BODYTEXT</html>",
        HEADER + "\n1,BODYTEXT,auth={key},x\n2,BODYTEXT,auth={key},x\n",
        HEADER + "\n1,AAPL,BODYTEXT auth={key},x,extra\n",
    ])
    def test_no_key_or_body_in_exception_or_logs(self, collector, caplog, mocker, body_template):
        # No RedactingFilter here: the raw records must already be free of body text.
        caplog.set_level(logging.DEBUG)
        body = body_template.format(key=self.KEY)
        mocker.patch.object(collector._session, "get", return_value=_csv_response(body))
        with pytest.raises(dc_module.InvalidFinvizResponse) as excinfo:
            collector.collect_worksheet("all", date="2026-11-13")
        exc = excinfo.value
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        assert self.KEY not in tb and "BODYTEXT" not in tb
        assert exc.__cause__ is None and exc.__suppress_context__

        collector.collect_all(date="2026-11-13", scope=CollectScope.SECTORS)
        assert "Failed to collect all" in caplog.text
        assert self.KEY not in caplog.text and "BODYTEXT" not in caplog.text


def test_cli_invalid_sector_body_exits_2(tmp_db, mocker):
    """An invalid body for one sector under --scope all exits 2 and keeps others."""
    mocker.patch("sys.argv", ["collect.py", "--db", tmp_db, "--scope", "all", "--date", "2026-11-13"])
    mocker.patch.dict("os.environ", {"FINVIZ_API_KEY": "test_key"})
    mocker.patch("src.data_collector.time.sleep")

    def fake_get(self, url, timeout):
        if "sec_technology" in url:
            return _csv_response("error\nsubscription expired\n")
        return _csv_response(SAMPLE_CSV)

    mocker.patch("requests.Session.get", fake_get)
    from collect import main
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 2
    from src.db_client import DBClient
    db = DBClient(tmp_db)
    assert db.fetch_raw_data("sec_technology").empty
    assert not db.fetch_raw_data("sec_energy").empty
