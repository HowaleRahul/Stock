"""
Frankfurter Currency Exchange API integration.
Source: public-apis (https://www.frankfurter.app/docs)

Provides keyless, high-reliability USD/INR live and historical foreign exchange rates
published by the European Central Bank. Used as a high-speed fallback when Yahoo Finance
INR=X quotes are delayed or unavailable.
"""

import datetime
import logging
import re
import urllib.parse
from typing import Dict, Any, Optional
import httpx
import pandas as pd

logger = logging.getLogger("trading.data.fx_fetcher")

FRANKFURTER_BASE_URL = "https://api.frankfurter.app"
_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_safe_fx_redirect(url: str) -> bool:
    """Validate redirect destination against SSRF: only HTTPS to frankfurter.app or frankfurter.dev allowed."""
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https":
            return False
        host = parsed.hostname
        if not host:
            return False
        return host in ("api.frankfurter.app", "api.frankfurter.dev", "frankfurter.app", "frankfurter.dev") or host.endswith(".frankfurter.app") or host.endswith(".frankfurter.dev")
    except Exception:
        return False


class FrankfurterFXFetcher:
    """
    Client for querying the open Frankfurter currency exchange API.
    Zero-auth, zero-rate-limit reference rates.
    """

    @classmethod
    def get_latest_usdinr_sync(cls, timeout: float = 6.0) -> Optional[float]:
        """Fetch the latest USD/INR exchange rate."""
        try:
            current_url = f"{FRANKFURTER_BASE_URL}/latest?from=USD&to=INR"
            with httpx.Client(timeout=timeout, follow_redirects=False) as client:
                resp = None
                for _ in range(3):
                    resp = client.get(current_url)
                    if resp.status_code in (301, 302, 303, 307, 308):
                        loc = resp.headers.get("Location")
                        if not loc:
                            break
                        next_url = urllib.parse.urljoin(current_url, loc)
                        if not _is_safe_fx_redirect(next_url):
                            logger.warning(f"Blocked unsafe SSRF redirect to: {next_url}")
                            return None
                        current_url = next_url
                    else:
                        break

                if resp and resp.status_code == 200:
                    data = resp.json()
                    rate = float(data.get("rates", {}).get("INR", 0.0))
                    if rate > 0:
                        logger.debug(f"Frankfurter live USD/INR: {rate}")
                        return rate
        except Exception as e:
            logger.warning(f"Frankfurter latest USD/INR fetch failed: {e}")
        return None

    @classmethod
    def get_historical_usdinr_series_sync(
        cls,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        days: Optional[int] = None,
        timeout: float = 10.0,
    ) -> Optional[pd.Series]:
        """
        Fetch historical daily USD/INR exchange rates from Frankfurter.
        start_date format: 'YYYY-MM-DD'
        end_date format: 'YYYY-MM-DD' (defaults to latest)
        days: optional integer to fetch the past N days.
        Returns a pd.Series indexed by UTC Timestamp.
        """
        try:
            if days is not None and not start_date:
                start_date = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
            if not start_date:
                start_date = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()

            # Input validation: strictly validate start_date and end_date formats
            clean_start = str(start_date).strip()
            if not _ISO_DATE_PATTERN.match(clean_start):
                logger.warning(f"Invalid start_date format '{start_date}'; rejecting request.")
                return None
            try:
                datetime.date.fromisoformat(clean_start)
            except ValueError:
                logger.warning(f"Invalid calendar date for start_date: '{start_date}'")
                return None

            clean_end = ""
            if end_date:
                clean_end = str(end_date).strip()
                if not _ISO_DATE_PATTERN.match(clean_end):
                    logger.warning(f"Invalid end_date format '{end_date}'; rejecting request.")
                    return None
                try:
                    datetime.date.fromisoformat(clean_end)
                except ValueError:
                    logger.warning(f"Invalid calendar date for end_date: '{end_date}'")
                    return None

            endpoint = f"{FRANKFURTER_BASE_URL}/{clean_start}.."
            if clean_end:
                endpoint += f"{clean_end}"
            endpoint += "?from=USD&to=INR"

            current_url = endpoint
            with httpx.Client(timeout=timeout, follow_redirects=False) as client:
                resp = None
                for _ in range(3):
                    resp = client.get(current_url)
                    if resp.status_code in (301, 302, 303, 307, 308):
                        loc = resp.headers.get("Location")
                        if not loc:
                            break
                        next_url = urllib.parse.urljoin(current_url, loc)
                        if not _is_safe_fx_redirect(next_url):
                            logger.warning(f"Blocked unsafe SSRF redirect in FX fetcher: {next_url}")
                            return None
                        current_url = next_url
                    else:
                        break

                if resp and resp.status_code == 200:
                    data = resp.json()
                    rates_dict = data.get("rates", {})
                    if not rates_dict:
                        return None

                    dates = []
                    values = []
                    for dt_str, pair in sorted(rates_dict.items()):
                        if "INR" in pair:
                            dates.append(pd.to_datetime(dt_str, utc=True))
                            values.append(float(pair["INR"]))

                    if dates:
                        s = pd.Series(values, index=dates, name="usdinr").sort_index()
                        logger.info(f"Retrieved {len(s)} USD/INR historical rates from Frankfurter.")
                        return s
        except Exception as e:
            logger.warning(f"Frankfurter historical USD/INR fetch failed: {e}")
        return None
