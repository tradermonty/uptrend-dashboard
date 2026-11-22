"""Tests for DataCollector — Finviz Elite CSV-based data collection."""

from unittest.mock import MagicMock, call

import pandas as pd
import pytest
import requests

from src.data_collector import CollectorConfig, CollectResult, CollectScope, DataCollector, mask_secrets


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

    def test_make_request_empty_csv_body(self, collector, mocker):
        """Fix 2: 200 + empty body should return empty DataFrame."""
        resp = MagicMock(spec=requests.Response)
        resp.status_code = 200
        resp.content = b""
        resp.raise_for_status = MagicMock()
        mocker.patch.object(collector._session, "get", return_value=resp)
        result = collector._make_request("http://example.com")
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0

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
        count, total = collector.collect_worksheet("all", date="2026-02-07")
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
            collector.collect_worksheet("all", date="2026-02-07")
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
            "ind_pharmaceuticalretailers", date="2026-02-07"
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
        count, total = collector.collect_worksheet("all", date="2026-02-07", dry_run=True)
        assert count == 0
        assert total == 0

    def test_collect_all(self, collector, mocker):
        mocker.patch.object(
            collector._session, "get",
            return_value=_csv_response(SAMPLE_CSV),
        )
        result = collector.collect_all(date="2026-02-07")
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
        result = collector.collect_all(date="2026-02-07")
        # First worksheet ("all") failed, remaining 160 should succeed
        assert len(result.succeeded) == 160
        assert len(result.failed) == 1

    def test_collect_worksheet_invalid(self, collector):
        with pytest.raises(ValueError, match="Invalid worksheet"):
            collector.collect_worksheet("invalid_sheet")

    def test_validate_counts_negative(self, collector, mocker):
        """Fix 4: Negative count/total should raise ValueError."""
        # Counts come from len(DataFrame) since v5.2, so they cannot be mocked
        # negative through the fetch path; exercise the guard directly.
        with pytest.raises(ValueError, match="negative"):
            collector._validate_counts("all", -1, 100)

    def test_validate_counts_count_exceeds_total(self, collector, mocker):
        """Fix 4: count > total should raise ValueError."""
        with pytest.raises(ValueError, match="exceeds total"):
            collector._validate_counts("all", 200, 100)

    def test_collect_worksheet_dry_run(self, collector, db_client, mocker):
        """Fix 7: dry_run=True should skip DB write but run validation."""
        mocker.patch.object(
            collector._session, "get",
            side_effect=[_csv_response(SAMPLE_CSV), _csv_response(SAMPLE_CSV)],
        )
        count, total = collector.collect_worksheet("all", date="2026-02-07", dry_run=True)
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
        result = collector.collect_all(date="2026-02-07", dry_run=True)
        assert len(result.succeeded) == 161
        mock_upsert.assert_not_called()

    def test_collect_worksheet_industry(self, collector, db_client, mocker):
        """collect_worksheet should accept ind_* worksheets."""
        mocker.patch.object(
            collector._session, "get",
            side_effect=[_csv_response(SAMPLE_CSV), _csv_response(SAMPLE_CSV)],
        )
        count, total = collector.collect_worksheet("ind_semiconductors", date="2026-02-07")
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
        result = collector.collect_all(date="2026-02-07", scope=CollectScope.SECTORS)
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
        result = collector.collect_all(date="2026-02-07", scope=CollectScope.INDUSTRIES)
        assert len(result.succeeded) == 149
        assert all(k.startswith("ind_") for k in result.succeeded)

    def test_collect_all_returns_collect_result(self, collector, mocker):
        """collect_all should return a CollectResult with succeeded/failed."""
        mocker.patch.object(
            collector._session, "get",
            return_value=_csv_response(SAMPLE_CSV),
        )
        result = collector.collect_all(date="2026-02-07", scope=CollectScope.SECTORS)
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
            date=None, dry_run=True, scope=CollectScope.ALL,
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
            date=None, dry_run=False, scope=CollectScope.SECTORS,
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
