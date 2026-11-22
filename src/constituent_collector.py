"""Daily industry constituent (stock list) collection (v5.9).

The count collection (DataCollector) requests ticker-only exports (c=1) and is
pinned by the Finviz migration evidence, so it cannot carry stock details.
This module makes two extra requests per day instead:

1. details: every stock passing the base filters, with Industry, Market Cap,
   Change and performance columns;
2. uptrend: tickers passing the uptrend filters (ticker only).

Stocks are grouped into industries by the export's Industry column and each
industry's snapshot replaces the previous one (latest-only storage).
ETF / closed-end fund industries are skipped: they come from the ETF universe.
"""

import logging
import re
import time
from typing import Dict, Optional, Set
from urllib.parse import urlencode

import pandas as pd

from src.constants import CONSTITUENT_COLUMNS, INDUSTRIES
from src.finviz_universe import BASE_FILTERS, FUND_WORKSHEETS, UPTREND_FILTERS

logger = logging.getLogger(__name__)

# Finviz export column ids (verified 2026-11-22): 1 Ticker, 2 Company, 3 Sector,
# 4 Industry, 6 Market Cap, 42 Performance (Week), 47 Performance (YTD), 66 Change
DETAIL_COLUMN_IDS = "1,2,3,4,6,42,47,66"

_PERCENT_COLUMNS = {
    "Change": "change",
    "Performance (Week)": "perf_week",
    "Performance (YTD)": "perf_ytd",
}

STOCK_INDUSTRIES = [ws for ws in INDUSTRIES if ws not in FUND_WORKSHEETS]

# More unmapped stocks than this means the industry labels changed, not a few new ones
MAX_UNKNOWN_INDUSTRY_SHARE = 0.05


def industry_key_for(name: Optional[str]) -> Optional[str]:
    """Map a Finviz Industry name to its worksheet key ('Oil & Gas E&P' -> 'ind_oilgasep')."""
    if not name:
        return None
    key = "ind_" + re.sub(r"[^a-z0-9]", "", str(name).lower())
    return key if key in INDUSTRIES else None


def build_details_url(base_url: str, api_key: str, uptrend: bool) -> str:
    """Market-wide stock export: details (base filters) or uptrend tickers only."""
    params = {
        "v": "151",
        "f": ",".join(UPTREND_FILTERS if uptrend else BASE_FILTERS),
        "ft": "4",
        "type": "stocks",
        "c": "1" if uptrend else DETAIL_COLUMN_IDS,
        "auth": api_key,
    }
    return base_url.rstrip("/") + "/export/screener?" + urlencode(params, safe=",")


def _parse_percent(series: pd.Series) -> pd.Series:
    """'-8.05%' -> -0.0805; '-' or blank -> NaN."""
    cleaned = series.astype(str).str.strip().str.rstrip("%")
    return pd.to_numeric(cleaned, errors="coerce") / 100.0


def build_constituent_snapshots(
    details: pd.DataFrame, uptrend_tickers: Set[str]
) -> Dict[str, pd.DataFrame]:
    """Group the details export into one CONSTITUENT_COLUMNS frame per stock industry.

    Every stock industry gets a frame (possibly empty) so that an industry with
    no stocks today is cleared rather than left stale.
    """
    frame = pd.DataFrame({
        "ticker": details["Ticker"].astype(str),
        "company": details["Company"] if "Company" in details.columns else None,
        "market_cap": pd.to_numeric(details.get("Market Cap"), errors="coerce"),
        "worksheet": details["Industry"].map(industry_key_for),
    })
    for src, dst in _PERCENT_COLUMNS.items():
        frame[dst] = _parse_percent(details[src]) if src in details.columns else float("nan")
    frame["is_uptrend"] = frame["ticker"].isin(uptrend_tickers)

    unknown = frame["worksheet"].isna()
    if unknown.any():
        names = sorted(set(details.loc[unknown, "Industry"].astype(str)))[:5]
        logger.warning("Ignoring %d stocks in unknown industries: %s", unknown.sum(), names)

    snapshots = {}
    for ws in STOCK_INDUSTRIES:
        rows = frame[frame["worksheet"] == ws]
        snapshots[ws] = rows[CONSTITUENT_COLUMNS].reset_index(drop=True)
    return snapshots


def collect_constituents_safely(data_collector, db_client, date: str, secrets=()) -> bool:
    """Run the constituent collection; log and swallow any failure.

    Stock lists are secondary data, so they never change the daily exit status.
    """
    from src.collection_session import SessionPolicyError
    from src.data_collector import redact
    from src.finviz_universe import MigrationEvidenceError

    try:
        ConstituentCollector(data_collector, db_client).collect(date)
        return True
    except (SessionPolicyError, MigrationEvidenceError) as exc:
        # The policy refusal still blocks every constituent write. It is not re-raised:
        # the day's count rows are already validated and written, and failing the run
        # here would make the workflow skip committing them.
        logger.error("Constituent collection refused by policy (lists unchanged): %s", exc)
        return False
    except Exception as exc:  # noqa: BLE001 - secondary data must not fail the run
        logger.warning(
            "Constituent collection failed (previous stock lists kept): %s",
            redact(str(exc), list(secrets)),
        )
        return False


class ConstituentCollector:
    """Fetches the two market-wide exports and replaces every industry snapshot."""

    def __init__(self, data_collector, db_client):
        # Reuse DataCollector's HTTP session, retries, response contract and redaction
        self._collector = data_collector
        self._db = db_client

    def _fetch(self, uptrend: bool, date: str) -> pd.DataFrame:
        config = self._collector._config
        url = build_details_url(config.base_url, config.finviz_api_key, uptrend=uptrend)
        return self._collector._make_request(url, session_date=date)

    def collect(self, date: str) -> int:
        """Collect and store all stock-industry snapshots. Returns industries written.

        Nothing is written unless both exports are valid and consistent.
        """
        details = self._fetch(uptrend=False, date=date)
        time.sleep(self._collector._config.request_interval)
        uptrend = self._fetch(uptrend=True, date=date)

        for name, df in (("details", details), ("uptrend", uptrend)):
            if "Ticker" not in df.columns:
                raise ValueError(f"{name} export has no Ticker column")
        if "Industry" not in details.columns:
            raise ValueError("details export has no Industry column")

        detail_tickers = set(details["Ticker"].astype(str))
        uptrend_tickers = set(uptrend["Ticker"].astype(str))
        # A header-only details export would clear every list: treat it as a bad response
        if not detail_tickers:
            raise ValueError("details export returned no stocks; keeping previous lists")
        if not uptrend_tickers <= detail_tickers:
            raise ValueError("uptrend tickers are not a subset of the details universe")
        unknown = details["Industry"].map(industry_key_for).isna().mean()
        if unknown > MAX_UNKNOWN_INDUSTRY_SHARE:
            # e.g. Finviz renamed its industry labels: refuse instead of clearing lists
            raise ValueError(
                f"{unknown:.0%} of stocks are in unknown industries; keeping previous lists"
            )

        snapshots = build_constituent_snapshots(details, uptrend_tickers)
        # One transaction: a storage error leaves every industry on its previous snapshot
        self._db.replace_all_constituents(date, snapshots)
        logger.info(
            "Constituents saved: %d stocks (%d uptrend) across %d industries",
            len(detail_tickers), len(uptrend_tickers), len(snapshots),
        )
        return len(snapshots)
