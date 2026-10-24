"""
Frankfurter Currency Exchange API integration.
Source: public-apis (https://www.frankfurter.app/docs)

Provides keyless, high-reliability USD/INR live and historical foreign exchange rates
published by the European Central Bank. Used as a high-speed fallback when Yahoo Finance
INR=X quotes are delayed or unavailable.
"""

import datetime
import logging
from typing import Dict, Any, Optional
import httpx
import pandas as pd

logger = logging.getLogger("trading.data.fx_fetcher")

FRANKFURTER_BASE_URL = "https://api.frankfurter.app"


class FrankfurterFXFetcher:
    """
    Client for querying the open Frankfurter currency exchange API.
    Zero-auth, zero-rate-limit reference rates.
    """

    @classmethod
    def get_latest_usdinr_sync(cls, timeout: float = 6.0) -> Optional[float]:
        """Fetch the latest USD/INR exchange rate."""
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                resp = client.get(f"{FRANKFURTER_BASE_URL}/latest?from=USD&to=INR")
                if resp.status_code == 200:
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

            endpoint = f"{FRANKFURTER_BASE_URL}/{start_date}.."
            if end_date:
                endpoint += f"{end_date}"
            endpoint += "?from=USD&to=INR"

            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                resp = client.get(endpoint)
                if resp.status_code == 200:
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
