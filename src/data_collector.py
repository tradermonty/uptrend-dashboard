"""Finviz Elite CSV-based data collector for uptrend dashboard."""

import csv
import io
import logging
import random
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, NoReturn, Optional, Tuple

import pandas as pd
import requests

from src.constants import INDUSTRIES, SECTORS, VALID_WORKSHEETS
from src.db_client import DBClient
from src.collection_session import SessionPolicyError, resolve_collection_date

logger = logging.getLogger(__name__)

# Finviz screener filters
_BASE_FILTERS = ["cap_microover", "sh_avgvol_o100", "sh_price_o10"]
_UPTREND_FILTERS = _BASE_FILTERS + [
    "ta_highlow52w_a30h",
    "ta_perf2_4wup",
    "ta_sma20_pa",
    "ta_sma200_pa",
    "ta_sma50_sa200",
]


class CollectScope(Enum):
    """Scope for data collection."""

    SECTORS = "sectors"      # "all" + 11 sectors (12 worksheets)
    INDUSTRIES = "industries"  # 149 industries
    ALL = "all"              # all 161 worksheets


@dataclass
class CollectResult:
    """Result of a collect_all run, separating succeeded and failed worksheets."""

    succeeded: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    failed: List[str] = field(default_factory=list)

    @property
    def sector_succeeded(self) -> Dict[str, Tuple[int, int]]:
        return {k: v for k, v in self.succeeded.items() if k == "all" or k.startswith("sec_")}

    @property
    def industry_succeeded(self) -> Dict[str, Tuple[int, int]]:
        return {k: v for k, v in self.succeeded.items() if k.startswith("ind_")}

    @property
    def sector_failed(self) -> List[str]:
        return [k for k in self.failed if k == "all" or k.startswith("sec_")]

    @property
    def industry_failed(self) -> List[str]:
        return [k for k in self.failed if k.startswith("ind_")]


DEFAULT_SECRET_MASK = "***"


def redact(text, secrets=(), mask: str = DEFAULT_SECRET_MASK):
    """Redact secrets from arbitrary text.

    Replaces each literal secret value with ``mask`` and masks ``auth=...``
    query tokens in URLs. Non-string inputs are returned unchanged so this is
    safe to apply to log-record ``args`` (which may contain ints, floats, etc).
    """
    if not text or not isinstance(text, str):
        return text
    out = text
    for secret in secrets:
        if secret:
            out = out.replace(secret, mask)
    return re.sub(r"(auth=)[^&\s]+", r"\1" + mask, out)


def mask_secrets(text: str) -> str:
    """Mask known secrets from URLs and exception messages (backward-compatible)."""
    return redact(text)


def _render_log_message(record: logging.LogRecord) -> str:
    """Render a record's message without ever raising into the logging caller.

    Filters run outside the error handling in ``Handler.emit``, so a malformed
    log call would otherwise propagate into the application. The arguments are
    dropped on failure because ``Handler.handleError`` would print them raw.
    """
    try:
        return record.getMessage()
    except Exception:
        template = record.msg if isinstance(record.msg, str) else type(record.msg).__name__
        return f"Unformattable log record at {record.pathname}:{record.lineno}: {template}"


def _render_exception_text(record: logging.LogRecord) -> str:
    """Format a record's exc_info without ever raising into the logging caller."""
    try:
        return logging.Formatter().formatException(record.exc_info)
    except Exception:
        return "Unformattable exception info"


class RedactingFilter(logging.Filter):
    """Log filter that removes secret values before a record is emitted.

    This must be attached to a logging *handler*, not merely to a logger: a
    logger-level filter does not apply to records propagated from child loggers
    (e.g. urllib3's ``connectionpool``), whereas a handler-level filter does.
    The filter mutates the ``LogRecord`` in place, so every handler that sees
    the record observes the scrubbed values, including pytest's caplog handler.
    """

    def __init__(self, secrets=()):
        super().__init__()
        self.secrets = tuple(s for s in secrets if s)

    def filter(self, record: logging.LogRecord) -> bool:
        # Interpolate first: objects/nested values become text, and redacting
        # auth=%s cannot destroy the template's placeholder correspondence.
        record.msg = redact(_render_log_message(record), self.secrets)
        record.args = ()
        if record.exc_info and not record.exc_text:
            record.exc_text = _render_exception_text(record)
        if record.exc_text:
            record.exc_text = redact(record.exc_text, self.secrets)
        # Keep sanitized traceback frames but prevent any later formatter from
        # regenerating exception text from the original secret-bearing objects.
        record.exc_info = None
        if record.stack_info:
            record.stack_info = redact(record.stack_info, self.secrets)
        return True


def configure_logging(verbose: bool, secrets=()) -> None:
    """Configure root logging with a secret-redacting filter.

    The filter is attached to the handlers present on the root logger so that
    records emitted by third-party loggers (such as urllib3) are scrubbed of
    secrets before emission, while keeping normal status/retry diagnostics.

    Limitation: only handlers present at this call are filtered; any handler
    added afterwards bypasses the filter (acceptable for the single-entrypoint
    collector CLI).
    """
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
    )
    redacting = RedactingFilter(secrets)
    root = logging.getLogger()
    for handler in list(root.handlers):
        handler.addFilter(redacting)
    # Safety net for records logged directly through the root logger itself.
    root.addFilter(redacting)


class InvalidFinvizResponse(ValueError):
    """A Finviz export body that does not satisfy the CSV contract.

    Subclasses ValueError so ``collect_all`` records it as a worksheet failure.
    Messages carry only the reason and sizes, never body text or the URL.
    """


def _reject(reason: str) -> NoReturn:
    raise InvalidFinvizResponse(f"invalid Finviz export: {reason}")


def _has_bad_ticker_chars(ticker: str) -> bool:
    return any(ch.isspace() or not ch.isprintable() for ch in ticker)


def parse_finviz_export(content: bytes) -> pd.DataFrame:
    """Parse a Finviz screener export, enforcing the documented CSV contract.

    The first non-empty row is the header and must contain exactly one
    ``Ticker`` column. Every data row must have the header's field count and a
    unique, non-blank ticker without whitespace or control characters. A
    header-only body is a valid zero-result export. All values stay strings,
    so tickers such as ``NA`` are not coerced to missing values.
    See docs/design.md "Finviz CSV response contract (v5.5)".
    """
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InvalidFinvizResponse(
            f"invalid Finviz export: body is not UTF-8 ({len(content)} bytes)"
        ) from None
    stripped = text.strip()
    if not stripped:
        _reject(f"empty body ({len(content)} bytes)")
    if stripped.startswith("<"):
        _reject(f"markup instead of CSV ({len(content)} bytes)")

    try:
        rows = [row for row in csv.reader(io.StringIO(text, newline=""), strict=True) if row]
    except csv.Error as exc:
        raise InvalidFinvizResponse(f"invalid Finviz export: CSV parse error ({exc})") from None

    header = [name.strip() for name in rows[0]]
    ticker_cols = [i for i, name in enumerate(header) if name.casefold() == "ticker"]
    if len(ticker_cols) != 1:
        _reject(f"expected exactly one Ticker column, found {len(ticker_cols)} "
                f"among {len(header)} header columns")
    ticker_col = ticker_cols[0]

    data = rows[1:]
    seen = set()
    for index, row in enumerate(data, start=1):
        if len(row) != len(header):
            _reject(f"data row {index} has {len(row)} fields, header has {len(header)}")
        ticker = row[ticker_col]
        if not ticker or _has_bad_ticker_chars(ticker):
            _reject(f"data row {index} has a blank or malformed ticker")
        if ticker in seen:
            _reject(f"data row {index} repeats a ticker")
        seen.add(ticker)

    return pd.DataFrame(data, columns=header, dtype=str)


@dataclass
class CollectorConfig:
    """Configuration for DataCollector."""

    finviz_api_key: str = field(repr=False)
    base_url: str = "https://elite.finviz.com"
    max_retries: int = 5
    retry_delay: float = 2.0
    request_interval: float = 2.0
    http_timeout: float = 30.0


class DataCollector:
    """Collects uptrend stock counts from Finviz Elite CSV export API."""

    def __init__(self, db_client: DBClient, config: CollectorConfig):
        self._db = db_client
        self._config = config
        self._session = requests.Session()

    def _build_filters(self, uptrend: bool, sector: str = None) -> str:
        filters = list(_UPTREND_FILTERS if uptrend else _BASE_FILTERS)
        if sector:
            filters.append(sector)
        return ",".join(filters)

    def _build_url(self, uptrend: bool, sector: str = None) -> str:
        filters = self._build_filters(uptrend, sector)
        return (
            f"{self._config.base_url}/export.ashx"
            f"?v=151&f={filters}&ft=4&auth={self._config.finviz_api_key}"
        )

    def _build_uptrend_url(self, sector: str = None) -> str:
        return self._build_url(uptrend=True, sector=sector)

    def _build_total_url(self, sector: str = None) -> str:
        return self._build_url(uptrend=False, sector=sector)

    _RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    @property
    def _redaction_secrets(self) -> Tuple[str, ...]:
        return (self._config.finviz_api_key,)

    def _safe_http_error(self, exc: requests.HTTPError) -> requests.HTTPError:
        """Create an HTTPError with a sanitized, secret-free message."""
        status = exc.response.status_code if exc.response is not None else "unknown"
        return requests.HTTPError(
            redact(f"HTTP {status} from Finviz export API", self._redaction_secrets)
        )

    def _raise_request_error(self, exc: requests.RequestException) -> None:
        """Re-raise a request exception with a sanitized message of the same class.

        ``from None`` suppresses the secret-bearing exception context so that a
        formatted traceback cannot expose the API key via the exception chain.
        Preserving the ``RequestException`` subclass keeps worksheet failures
        classified correctly by ``collect_all``.
        """
        raise exc.__class__(redact(str(exc), self._redaction_secrets)) from None

    def _make_request(self, url: str, *, session_date: Optional[str] = None) -> pd.DataFrame:
        """Fetch CSV from Finviz with exponential backoff retry + jitter.

        A 200 body is validated by ``parse_finviz_export``; an invalid body
        raises ``InvalidFinvizResponse`` and is not retried.
        """
        session_date = resolve_collection_date(session_date)
        delay = self._config.retry_delay
        for attempt in range(1, self._config.max_retries + 1):
            try:
                resolve_collection_date(session_date)
                resp = self._session.get(url, timeout=self._config.http_timeout)
                # Policy must take precedence over content/HTTP error tolerance.
                resolve_collection_date(session_date)
                resp.raise_for_status()
                return parse_finviz_export(resp.content)
            except (requests.ConnectionError, requests.Timeout) as exc:
                resolve_collection_date(session_date)
                logger.warning(
                    "Request failed (attempt %d/%d): %s",
                    attempt,
                    self._config.max_retries,
                    redact(str(exc), self._redaction_secrets),
                )
                if attempt == self._config.max_retries:
                    self._raise_request_error(exc)
                jitter = random.uniform(0, delay * 0.25)
                time.sleep(delay + jitter)
                delay *= 2
            except requests.HTTPError as exc:
                resolve_collection_date(session_date)
                status = exc.response.status_code if exc.response is not None else None
                if status in self._RETRYABLE_STATUS_CODES:
                    logger.warning("HTTP %s (attempt %d/%d), backing off %.1fs",
                                   status, attempt, self._config.max_retries, delay)
                    if attempt == self._config.max_retries:
                        raise self._safe_http_error(exc) from None
                    jitter = random.uniform(0, delay * 0.25)
                    time.sleep(delay + jitter)
                    delay *= 2
                else:
                    raise self._safe_http_error(exc) from None
            except requests.RequestException as exc:
                resolve_collection_date(session_date)
                self._raise_request_error(exc)

    def _fetch_stock_count(self, sector: str = None, *, session_date: Optional[str] = None) -> Tuple[int, int]:
        """Fetch uptrend count and total count for a sector (or all)."""
        session_date = resolve_collection_date(session_date)
        uptrend_url = self._build_uptrend_url(sector)
        total_url = self._build_total_url(sector)

        uptrend_df = self._fetch_export("uptrend", uptrend_url, session_date=session_date)
        time.sleep(self._config.request_interval)
        total_df = self._fetch_export("total", total_url, session_date=session_date)

        return len(uptrend_df), len(total_df)

    def _fetch_export(self, label: str, url: str, *, session_date: Optional[str] = None) -> pd.DataFrame:
        """Fetch one export, naming which request failed the contract."""
        try:
            return self._make_request(url, session_date=session_date)
        except InvalidFinvizResponse as exc:
            raise InvalidFinvizResponse(f"{label} response: {exc}") from None

    def _validate_counts(self, worksheet: str, count: int, total: int) -> None:
        """Validate count and total values before DB write."""
        if count < 0 or total < 0:
            raise ValueError(
                f"Invalid negative value for {worksheet}: "
                f"count={count}, total={total}"
            )
        if count > total:
            raise ValueError(
                f"count exceeds total for {worksheet}: "
                f"count={count}, total={total}"
            )

    def collect_worksheet(
        self, worksheet: str, date: Optional[str] = None, dry_run: bool = False
    ) -> Tuple[int, int]:
        """Collect data for a single worksheet and write to DB."""
        if worksheet not in VALID_WORKSHEETS:
            raise ValueError(
                f"Invalid worksheet: '{worksheet}'. "
                f"Must be one of {VALID_WORKSHEETS}"
            )
        date = resolve_collection_date(date)

        sector = worksheet if worksheet != "all" else None
        count, total = self._fetch_stock_count(sector, session_date=date)
        resolve_collection_date(date)  # A response pair crossing NY midnight cannot be written.
        self._validate_counts(worksheet, count, total)

        if dry_run:
            logger.info("Dry run %s: count=%d, total=%d", worksheet, count, total)
        elif total > 0:
            self._db.upsert_raw_data(date, worksheet, count, total)
            logger.info("Collected %s: count=%d, total=%d", worksheet, count, total)
        elif worksheet.startswith("ind_"):
            # 小規模 industry ではベースフィルタ (cap/vol/price) 通過銘柄が 0 件と
            # なり得る正当ケース。8c7f23d 以前の挙動に戻し warning + skip で継続。
            # DB には書き込まない (0.0 ratio を描画するとチャートに偽の下落ピークが出るため)。
            logger.warning("Skipping %s: total=0 (no stocks match base filters)", worksheet)
        else:
            # "all" と sec_* は total=0 なら API 障害の強いシグナル（市場全体/大セクターに銘柄ゼロはあり得ない）
            raise ValueError(
                f"Empty data for {worksheet}: total=0 "
                f"(API returned no stocks matching filters)"
            )

        return count, total

    def collect_all(
        self,
        date: Optional[str] = None,
        dry_run: bool = False,
        scope: CollectScope = CollectScope.ALL,
    ) -> CollectResult:
        """Collect data for worksheets determined by scope.

        Args:
            date: Date string in YYYY-MM-DD format (default: today).
            dry_run: If True, fetch data without writing to DB.
            scope: Which worksheets to collect (ALL, SECTORS, or INDUSTRIES).
        """
        date = resolve_collection_date(date)

        if scope == CollectScope.SECTORS:
            worksheets = ["all"] + SECTORS
        elif scope == CollectScope.INDUSTRIES:
            worksheets = list(INDUSTRIES)
        else:
            worksheets = list(VALID_WORKSHEETS)

        result = CollectResult()
        total = len(worksheets)
        for idx, worksheet in enumerate(worksheets):
            logger.info("Collecting %d/%d: %s", idx + 1, total, worksheet)
            try:
                result.succeeded[worksheet] = self.collect_worksheet(
                    worksheet, date, dry_run=dry_run,
                )
            except SessionPolicyError:
                raise  # Fatal even for the final industry: never absorb into tolerance.
            except (requests.RequestException, ValueError) as exc:
                logger.error(
                    "Failed to collect %s: %s", worksheet,
                    redact(str(exc), self._redaction_secrets),
                )
                result.failed.append(worksheet)
        return result

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self._session.close()
