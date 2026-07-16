import asyncio
import logging
from typing import List, Dict, Any, Optional
import pandas as pd
import yfinance as yf

logger = logging.getLogger("trading.data.fetcher")

class YFinanceFetcher:
    """
    Async wrapper around yfinance for downloading OHLCV bars, corporate actions, and symbol metadata.
    Runs synchronous yfinance calls inside asyncio threads to avoid blocking the loop.
    """

    YAHOO_TICKER_ALIASES = {
        "NIFTY": "^NSEI",
        "NIFTY.NS": "^NSEI",
        "NIFTY 50": "^NSEI",
        "BANKNIFTY": "^NSEBANK",
        "BANKNIFTY.NS": "^NSEBANK",
        "NIFTY BANK": "^NSEBANK",
        "SENSEX": "^BSESN",
        "SENSEX.BO": "^BSESN",
        "BSE SENSEX": "^BSESN",
    }

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
        if not start and not end:
            if interval in ["1m"]:
                period = "7d"
            elif interval in ["2m", "5m", "15m", "30m"]:
                period = "60d"
            elif interval in ["60m", "1h", "90m"]:
                if period in ["5y", "max", "10y"]:
                    period = "730d"
        logger.info(f"Downloading history for {ticker} (yahoo={yahoo_ticker}, period={period}, interval={interval}, start={start}, end={end})...")
        yt = yf.Ticker(yahoo_ticker)
        
        kwargs = {
            "interval": interval,
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

        try:
            df = yt.history(**kwargs)
            return df
        except Exception as e:
            logger.warning(f"Error fetching history from yfinance for {ticker}: {e}")
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
