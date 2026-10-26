import asyncio
import logging
import threading
from typing import List, Dict, Any, Optional
import pandas as pd
import requests
import yfinance as yf
from cachetools import TTLCache

logger = logging.getLogger("trading.data.fetcher")

_HISTORY_CACHE = TTLCache(maxsize=1000, ttl=300)  # 5-minute TTL cache for OHLCV bars
_CACHE_LOCK = threading.Lock()

class YFinanceFetcher:
    """
    Async wrapper around yfinance for downloading OHLCV bars, corporate actions, and symbol metadata.
    Runs synchronous yfinance calls inside asyncio threads to avoid blocking the loop,
    with a direct v8 Yahoo Finance fallback and in-memory TTL caching to prevent rate limiting.
    """

    YAHOO_TICKER_ALIASES = {
        "NIFTY": "^NSEI",
        "NIFTY.NS": "^NSEI",
        "NIFTY 50": "^NSEI",
        "^NSEI": "^NSEI",
        "BANKNIFTY": "^NSEBANK",
        "BANKNIFTY.NS": "^NSEBANK",
        "NIFTY BANK": "^NSEBANK",
        "^NSEBANK": "^NSEBANK",
        "SENSEX": "^BSESN",
        "SENSEX.NS": "^BSESN",
        "SENSEX.BO": "^BSESN",
        "BSE SENSEX": "^BSESN",
        "^BSESN": "^BSESN",
        "FINNIFTY": "^NSEI",
        "MIDCPNIFTY": "^NSEI",
    }

    @classmethod
    def _fetch_chart_direct_sync(
        cls,
        yahoo_ticker: str,
        period: str = "1y",
        interval: str = "1d",
    ) -> pd.DataFrame:
        """
        Direct HTTP fallback querying Yahoo Finance's v8 chart API.
        Bypasses cookie/crumb authentication and avoids YFRateLimitError.
        """
        # Enforce valid Yahoo Finance ranges per interval
        # Intraday bars (1m..1h) must be within last 60 days
        if interval in ("1m",):
            p = "5d"
        elif interval in ("2m", "5m", "15m", "30m"):
            p = "30d" if period in ("30d", "1mo") else "60d"
        elif interval in ("60m", "1h", "90m"):
            p = "60d"
        else:
            p = period
            if p in ("max", "10y"):
                p = "5y"
            elif p in ("730d", "2y"):
                p = "2y"
            elif p in ("60d", "3mo"):
                p = "3mo"
            elif p in ("7d", "5d"):
                p = "5d"

        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_ticker}?range={p}&interval={interval}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json",
        }
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                logger.warning(f"Yahoo v8 chart API returned HTTP {r.status_code} for {yahoo_ticker}")
                return pd.DataFrame()
            data = r.json()
            results = data.get("chart", {}).get("result")
            if not results:
                return pd.DataFrame()
            chart_res = results[0]
            timestamps = chart_res.get("timestamp", [])
            indicators = chart_res.get("indicators", {}).get("quote", [{}])[0]
            if not timestamps or not indicators:
                return pd.DataFrame()

            idx = pd.to_datetime(timestamps, unit="s", utc=True)
            df = pd.DataFrame(
                {
                    "Open": indicators.get("open", []),
                    "High": indicators.get("high", []),
                    "Low": indicators.get("low", []),
                    "Close": indicators.get("close", []),
                    "Volume": indicators.get("volume", []),
                },
                index=idx,
            )
            df = df.dropna(subset=["Close"])
            if not df.empty:
                logger.info(f"Direct v8 chart API retrieved {len(df)} bars for {yahoo_ticker}.")
            return df
        except Exception as e:
            logger.warning(f"Direct v8 chart API failed for {yahoo_ticker}: {e}")
            return pd.DataFrame()

    @classmethod
    def _fetch_history_sync(
        cls,
        ticker: str,
        period: str = "5y",
        interval: str = "1d",
        start: Optional[str] = None,
        end: Optional[str] = None
    ) -> pd.DataFrame:
        ticker = ticker.upper().strip()
        yahoo_ticker = cls.YAHOO_TICKER_ALIASES.get(ticker, ticker)

        cache_key = (yahoo_ticker, period, interval, start, end)
        with _CACHE_LOCK:
            if cache_key in _HISTORY_CACHE:
                cached = _HISTORY_CACHE[cache_key]
                if cached is not None and not cached.empty:
                    return cached.copy()

        # Map non-native intervals to native yfinance intervals
        yf_interval = interval
        resample_rule = None
        if interval == "3m":
            yf_interval = "1m"
            resample_rule = "3min"
        elif interval == "4m":
            yf_interval = "1m"
            resample_rule = "4min"
        elif interval == "10m":
            yf_interval = "5m"
            resample_rule = "10min"
        elif interval == "45m":
            yf_interval = "15m"
            resample_rule = "45min"
        elif interval == "2h":
            yf_interval = "1h"
            resample_rule = "2h"
        elif interval == "3h":
            yf_interval = "1h"
            resample_rule = "3h"
        elif interval == "4h":
            yf_interval = "1h"
            resample_rule = "4h"

        if not start and not end:
            if yf_interval in ["1m"]:
                period = "7d"
            elif yf_interval in ["2m", "5m", "15m", "30m"]:
                period = "60d"
            elif yf_interval in ["60m", "1h", "90m"]:
                if period in ["5y", "max", "10y"]:
                    period = "730d"
        logger.info(f"Downloading history for {ticker} (yahoo={yahoo_ticker}, period={period}, interval={interval}, start={start}, end={end})...")
        yt = yf.Ticker(yahoo_ticker)
        
        kwargs = {
            "interval": yf_interval,
            "actions": True,
            "auto_adjust": False  # Keep raw Open/High/Low/Close separate from Adj Close
        }
        if start or end:
            if start:
                kwargs["start"] = start
            if end:
                kwargs["end"] = end
        else:
            kwargs["period"] = period

        df = pd.DataFrame()
        try:
            df = yt.history(**kwargs)
        except Exception as e:
            logger.warning(f"Error fetching history from yfinance for {ticker}: {e}. Trying direct chart API fallback...")

        # If yfinance returned empty or raised rate limit, fallback to direct chart API
        if df is None or df.empty:
            df = cls._fetch_chart_direct_sync(yahoo_ticker, period=period, interval=yf_interval)

        if df is None or df.empty:
            return pd.DataFrame()

        try:
            if resample_rule:
                agg_dict = {
                    "Open": "first",
                    "High": "max",
                    "Low": "min",
                    "Close": "last",
                    "Volume": "sum"
                }
                if "Dividends" in df.columns:
                    agg_dict["Dividends"] = "sum"
                if "Stock Splits" in df.columns:
                    agg_dict["Stock Splits"] = "sum"
                if "Adj Close" in df.columns:
                    agg_dict["Adj Close"] = "last"
                    
                df = df.resample(resample_rule).agg(agg_dict).dropna(subset=["Close"])

            with _CACHE_LOCK:
                _HISTORY_CACHE[cache_key] = df.copy()

            return df
        except Exception as e:
            logger.warning(f"Error processing history for {ticker}: {e}")
            return df if not df.empty else pd.DataFrame()

    @classmethod
    async def fetch_history(
        cls,
        ticker: str,
        period: str = "1y",
        interval: str = "1d",
        start: Optional[str] = None,
        end: Optional[str] = None,
        timeout: float = 45.0,
    ) -> pd.DataFrame:
        """
        Asynchronously fetches OHLCV history for a ticker and returns a cleaned pandas DataFrame
        with standardized lowercase column names ('open', 'high', 'low', 'close', 'volume').
        """
        ticker = ticker.upper().strip()
        try:
            df = await asyncio.wait_for(
                asyncio.to_thread(
                    cls._fetch_history_sync,
                    ticker=ticker,
                    period=period,
                    interval=interval,
                    start=start,
                    end=end,
                ),
                timeout=timeout,
            )
            if df is None or df.empty:
                logger.warning(f"No OHLCV history DataFrame returned for {ticker}.")
                return pd.DataFrame()

            # Normalize column names to lowercase and strip whitespaces
            df_norm = df.copy()
            df_norm.columns = [str(c).lower().replace(" ", "_") for c in df_norm.columns]
            return df_norm
        except asyncio.TimeoutError:
            logger.error(f"Network timeout ({timeout}s) while fetching history DataFrame for {ticker}.")
            return pd.DataFrame()
        except Exception as e:
            logger.warning(f"Error asynchronously fetching history for {ticker}: {e}")
            return pd.DataFrame()

    @classmethod
    async def fetch_ohlcv_bars(
        cls,
        ticker: str,
        period: str = "5y",
        interval: str = "1d",
        start: Optional[str] = None,
        end: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetches OHLCV bars + corporate actions (splits, dividends) for a ticker and returns a list of standardized dicts.
        """
        ticker = ticker.upper().strip()
        try:
            df = await asyncio.wait_for(
                asyncio.to_thread(
                    cls._fetch_history_sync,
                    ticker=ticker,
                    period=period,
                    interval=interval,
                    start=start,
                    end=end
                ),
                timeout=45.0
            )
        except asyncio.TimeoutError:
            logger.error(f"Network request timed out (45s) while fetching OHLCV for {ticker}.")
            return []

        if df is None or df.empty:
            logger.warning(f"No OHLCV data returned for {ticker}.")
            return []

        # Standardize dataframe
        bars = []
        def _safe_float(val: Any, default: float = 0.0) -> float:
            try:
                if val is None or pd.isna(val):
                    return default
                f = float(val)
                if pd.isna(f) or f != f or abs(f) == float('inf'):
                    return default
                return f
            except (ValueError, TypeError):
                return default

        for dt, row in df.iterrows():
            # Ensure timezone aware (UTC)
            try:
                if hasattr(dt, 'tzinfo') and dt.tzinfo is None:
                    dt_utc = dt.tz_localize("UTC")
                elif hasattr(dt, 'tz_convert'):
                    dt_utc = dt.tz_convert("UTC")
                else:
                    dt_utc = pd.to_datetime(dt).tz_localize("UTC") if pd.to_datetime(dt).tzinfo is None else pd.to_datetime(dt).tz_convert("UTC")
            except Exception as tz_err:
                logger.debug(f"Timezone conversion fallback for {dt}: {tz_err}")
                continue

            # Extract corporate actions safely
            split_ratio = _safe_float(row.get("Stock Splits"), 1.0)
            if split_ratio <= 0.0:
                split_ratio = 1.0
            dividend = _safe_float(row.get("Dividends"), 0.0)
            if dividend < 0.0:
                dividend = 0.0

            open_val = _safe_float(row.get("Open"), 0.0)
            high_val = _safe_float(row.get("High"), 0.0)
            low_val = _safe_float(row.get("Low"), 0.0)
            close_val = _safe_float(row.get("Close"), 0.0)
            adj_close_val = _safe_float(row.get("Adj Close"), close_val)
            vol_val = _safe_float(row.get("Volume"), 0.0)

            # Skip rows where Open and Close are both 0 or NaN
            if open_val <= 0.0 and close_val <= 0.0 and vol_val <= 0.0:
                continue

            bars.append({
                "time": dt_utc.to_pydatetime(),
                "timeframe": interval,
                "open": open_val,
                "high": high_val,
                "low": low_val,
                "close": close_val,
                "adjusted_close": adj_close_val,
                "volume": vol_val,
                "split_ratio": split_ratio,
                "dividend": dividend
            })

        logger.info(f"Successfully processed {len(bars)} bars for {ticker}.")
        return bars

    @classmethod
    def _fetch_info_sync(cls, ticker: str) -> Dict[str, Any]:
        ticker = ticker.upper().strip()
        yahoo_ticker = cls.YAHOO_TICKER_ALIASES.get(ticker, ticker)
        yt = yf.Ticker(yahoo_ticker)
        try:
            info = yt.info or {}
            return {
                "name": info.get("longName") or info.get("shortName") or ticker,
                "exchange": info.get("exchange") or ("NSE" if ticker.endswith(".NS") else ("BSE" if ticker.endswith(".BO") else "NASDAQ")),
                "currency": info.get("currency") or ("INR" if (ticker.endswith(".NS") or ticker.endswith(".BO")) else "USD")
            }
        except Exception as e:
            logger.warning(f"Failed to fetch metadata for {ticker}: {e}")
            return {
                "name": ticker,
                "exchange": "NSE" if ticker.endswith(".NS") else ("BSE" if ticker.endswith(".BO") else "NASDAQ"),
                "currency": "INR" if (ticker.endswith(".NS") or ticker.endswith(".BO")) else "USD"
            }

    @classmethod
    async def fetch_symbol_info(cls, ticker: str) -> Dict[str, Any]:
        """
        Fetches basic symbol metadata asynchronously.
        """
        ticker = ticker.upper().strip()
        try:
            return await asyncio.wait_for(asyncio.to_thread(cls._fetch_info_sync, ticker), timeout=20.0)
        except asyncio.TimeoutError:
            logger.error(f"Metadata request timed out (20s) for {ticker}. Using fallback info.")
            return {
                "name": ticker,
                "exchange": "NSE" if ticker.endswith(".NS") else ("BSE" if ticker.endswith(".BO") else "NASDAQ"),
                "currency": "INR" if (ticker.endswith(".NS") or ticker.endswith(".BO")) else "USD"
            }

    @classmethod
    async def verify_symbol_exists(cls, ticker: str) -> bool:
        """
        Verifies if ticker exists externally by attempting to fetch recent data.
        Returns True if at least one valid OHLCV bar is returned.
        """
        ticker = ticker.upper().strip()
        try:
            bars = await cls.fetch_ohlcv_bars(ticker, period="5d", interval="1d")
            return len(bars) > 0
        except Exception:
            return False

