"""Finviz Elite CSV-based data collector for uptrend dashboard."""

import io
import logging
import random
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests

from src.constants import CONSTITUENT_COLUMNS, INDUSTRIES, SECTORS, VALID_WORKSHEETS, is_industry
from src.db_client import DBClient

logger = logging.getLogger(__name__)

# Finviz export column -> stored constituent column
_NUMERIC_SOURCE_COLUMNS = {"Market Cap": "market_cap"}
_PERCENT_SOURCE_COLUMNS = {
    "Change": "change",
    "Performance (Week)": "perf_week",
    "Performance (YTD)": "perf_ytd",
}


def _parse_percent(series: pd.Series) -> pd.Series:
    """Convert Finviz percent strings ('-8.05%') to fractions; unparseable -> NaN."""
    cleaned = series.astype(str).str.strip().str.rstrip("%")
    return pd.to_numeric(cleaned, errors="coerce") / 100.0


def extract_constituents(total_df: pd.DataFrame, uptrend_df: pd.DataFrame) -> pd.DataFrame:
    """Build the constituent snapshot from Finviz total/uptrend export frames.

    Every stock in total_df becomes one row; is_uptrend marks the ones that also
    appear in uptrend_df. Missing source columns yield NaN instead of failing.
    """
    if total_df.empty or "Ticker" not in total_df.columns:
        return pd.DataFrame(columns=CONSTITUENT_COLUMNS)

    result = pd.DataFrame({"ticker": total_df["Ticker"].astype(str)})
    result["company"] = total_df["Company"] if "Company" in total_df.columns else None
    for src, dst in _NUMERIC_SOURCE_COLUMNS.items():
        result[dst] = (
            pd.to_numeric(total_df[src], errors="coerce") if src in total_df.columns else float("nan")
        )
    for src, dst in _PERCENT_SOURCE_COLUMNS.items():
        result[dst] = _parse_percent(total_df[src]) if src in total_df.columns else float("nan")

    uptrend_tickers = (
        set(uptrend_df["Ticker"].astype(str)) if "Ticker" in uptrend_df.columns else set()
    )
    result["is_uptrend"] = result["ticker"].isin(uptrend_tickers)
    # Null or duplicate tickers would break the (worksheet, ticker) primary key
    valid = total_df["Ticker"].notna().to_numpy()
    result = result[valid].drop_duplicates("ticker")
    return result[CONSTITUENT_COLUMNS].reset_index(drop=True)

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


def mask_secrets(text: str) -> str:
    """Mask known secrets from URLs and exception messages."""
    if not text:
        return text
    return re.sub(r"(auth=)[^&\s]+", r"\1***", text)


@dataclass
class CollectorConfig:
    """Configuration for DataCollector."""

    finviz_api_key: str
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

    @staticmethod
    def _safe_http_error(exc: requests.HTTPError) -> requests.HTTPError:
        """Create an HTTPError with a sanitized message."""
        status = exc.response.status_code if exc.response is not None else "unknown"
        return requests.HTTPError(f"HTTP {status} from Finviz export API")

    def _make_request(self, url: str) -> pd.DataFrame:
        """Fetch CSV from Finviz with exponential backoff retry + jitter."""
        delay = self._config.retry_delay
        for attempt in range(1, self._config.max_retries + 1):
            try:
                resp = self._session.get(url, timeout=self._config.http_timeout)
                resp.raise_for_status()
                try:
                    # "NA" is a real ticker: only "" and "-" mean missing
                    return pd.read_csv(
                        io.BytesIO(resp.content),
                        keep_default_na=False,
                        na_values=["", "-"],
                        dtype={"Ticker": str},
                    )
                except pd.errors.EmptyDataError:
                    logger.warning("Empty CSV body received")
                    return pd.DataFrame()
            except (requests.ConnectionError, requests.Timeout) as exc:
                logger.warning(
                    "Request failed (attempt %d/%d): %s",
                    attempt,
                    self._config.max_retries,
                    mask_secrets(str(exc)),
                )
                if attempt == self._config.max_retries:
                    raise
                jitter = random.uniform(0, delay * 0.25)
                time.sleep(delay + jitter)
                delay *= 2
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status in self._RETRYABLE_STATUS_CODES:
                    logger.warning("HTTP %s (attempt %d/%d), backing off %.1fs",
                                   status, attempt, self._config.max_retries, delay)
                    if attempt == self._config.max_retries:
                        raise self._safe_http_error(exc) from exc
                    jitter = random.uniform(0, delay * 0.25)
                    time.sleep(delay + jitter)
                    delay *= 2
                else:
                    raise self._safe_http_error(exc) from exc

    def _fetch_stock_lists(self, sector: str = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Fetch the uptrend and total stock lists for a sector/industry (or all)."""
        uptrend_df = self._make_request(self._build_uptrend_url(sector))
        time.sleep(self._config.request_interval)
        total_df = self._make_request(self._build_total_url(sector))
        return uptrend_df, total_df

    def _fetch_stock_count(self, sector: str = None) -> Tuple[int, int]:
        """Fetch uptrend count and total count for a sector (or all)."""
        uptrend_df, total_df = self._fetch_stock_lists(sector)
        return len(uptrend_df), len(total_df)

    def _save_constituents(self, worksheet: str, date: str, constituents: pd.DataFrame) -> None:
        """Store an industry's stock list. Secondary data: failures only warn."""
        try:
            self._db.replace_constituents(worksheet, date, constituents)
        except (sqlite3.Error, ValueError) as exc:
            logger.warning("Failed to save constituents for %s: %s", worksheet, exc)

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
        if date is None:
            from datetime import date as date_cls
            date = date_cls.today().isoformat()

        sector = worksheet if worksheet != "all" else None
        uptrend_df, total_df = self._fetch_stock_lists(sector)
        count, total = len(uptrend_df), len(total_df)
        self._validate_counts(worksheet, count, total)

        if dry_run:
            logger.info("Dry run %s: count=%d, total=%d", worksheet, count, total)
        elif total > 0:
            self._db.upsert_raw_data(date, worksheet, count, total)
            logger.info("Collected %s: count=%d, total=%d", worksheet, count, total)
        elif is_industry(worksheet):
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

        if not dry_run and is_industry(worksheet):
            self._maybe_save_constituents(worksheet, date, uptrend_df, total_df)

        return count, total

    @staticmethod
    def _today() -> str:
        from datetime import date as date_cls
        return date_cls.today().isoformat()

    def _maybe_save_constituents(
        self, worksheet: str, date: str, uptrend_df: pd.DataFrame, total_df: pd.DataFrame,
    ) -> None:
        """Save the industry stock list when the fetched frames are a trustworthy snapshot.

        Runs after the count row is written. Skipped (old list kept) when:
        - date is not today: Finviz always returns today's screen, so a backfill
          run would label today's list with a past date;
        - the total response had no header: a blank body is a glitch, not "0 stocks".
        A header-only response (0 stocks) does clear the list.
        """
        if date != self._today():
            logger.info("Skipping constituents for %s: date %s is not today", worksheet, date)
            return
        if "Ticker" not in total_df.columns:
            logger.warning("Skipping constituents for %s: response had no header", worksheet)
            return
        self._save_constituents(worksheet, date, extract_constituents(total_df, uptrend_df))

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
        if date is None:
            from datetime import date as date_cls
            date = date_cls.today().isoformat()

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
            except (requests.RequestException, ValueError, pd.errors.EmptyDataError) as exc:
                logger.error("Failed to collect %s: %s", worksheet, mask_secrets(str(exc)))
                result.failed.append(worksheet)
        return result

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self._session.close()
