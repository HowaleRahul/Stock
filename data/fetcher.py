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

    @staticmethod
    def _fetch_history_sync(
        ticker: str,
        period: str = "5y",
        interval: str = "1d",
        start: Optional[str] = None,
        end: Optional[str] = None
    ) -> pd.DataFrame:
        logger.info(f"Downloading history for {ticker} (period={period}, interval={interval}, start={start}, end={end})...")
        yt = yf.Ticker(ticker)
        
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

        df = yt.history(**kwargs)
        return df

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
        df = await asyncio.to_thread(
            cls._fetch_history_sync,
            ticker=ticker,
            period=period,
            interval=interval,
            start=start,
            end=end
        )

        if df is None or df.empty:
            logger.warning(f"No OHLCV data returned for {ticker}.")
            return []

        # Standardize dataframe
        bars = []
        for dt, row in df.iterrows():
            # Ensure timezone aware (UTC)
            if dt.tzinfo is None:
                dt_utc = dt.tz_localize("UTC")
            else:
                dt_utc = dt.tz_convert("UTC")

            # Extract corporate actions safely
            split_ratio = float(row["Stock Splits"]) if "Stock Splits" in row and pd.notna(row["Stock Splits"]) else 1.0
            if split_ratio == 0.0:
                split_ratio = 1.0
            dividend = float(row["Dividends"]) if "Dividends" in row and pd.notna(row["Dividends"]) else 0.0

            open_val = float(row["Open"]) if pd.notna(row["Open"]) else 0.0
            high_val = float(row["High"]) if pd.notna(row["High"]) else 0.0
            low_val = float(row["Low"]) if pd.notna(row["Low"]) else 0.0
            close_val = float(row["Close"]) if pd.notna(row["Close"]) else 0.0
            adj_close_val = float(row["Adj Close"]) if "Adj Close" in row and pd.notna(row["Adj Close"]) else close_val
            vol_val = float(row["Volume"]) if pd.notna(row["Volume"]) else 0.0

            # Skip rows where Open and Close are both 0 or NaN
            if open_val == 0.0 and close_val == 0.0 and vol_val == 0.0:
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

    @staticmethod
    def _fetch_info_sync(ticker: str) -> Dict[str, Any]:
        yt = yf.Ticker(ticker)
        try:
            info = yt.info or {}
            return {
                "name": info.get("longName") or info.get("shortName") or ticker,
                "exchange": info.get("exchange") or ("NSE" if ticker.endswith(".NS") else "NASDAQ"),
                "currency": info.get("currency") or ("INR" if ticker.endswith(".NS") else "USD")
            }
        except Exception as e:
            logger.warning(f"Failed to fetch metadata for {ticker}: {e}")
            return {
                "name": ticker,
                "exchange": "NSE" if ticker.endswith(".NS") else "NASDAQ",
                "currency": "INR" if ticker.endswith(".NS") else "USD"
            }

    @classmethod
    async def fetch_symbol_info(cls, ticker: str) -> Dict[str, Any]:
        """
        Fetches basic symbol metadata asynchronously.
        """
        return await asyncio.to_thread(cls._fetch_info_sync, ticker)
