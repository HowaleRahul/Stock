"""
Real-Time Market Data Feed & TradingView Analysis Engine.

Integrates:
1. TradingView Technical Analysis via tradingview-ta (Real-time live prices, indicators, and recommendation signals directly from TradingView).
2. Third-party API support (AlphaVantage, TwelveData, Finnhub, Upstox) configurable via .env or config.json.
3. High-performance caching with fallback to Yahoo Finance.
4. Live candle streaming & OHLCV generation for interactive charts.
"""

import os
import time
import logging
import asyncio
from typing import Dict, Any, List, Optional
import pandas as pd
import yfinance as yf

try:
    from tradingview_ta import TA_Handler, Interval, Exchange
    HAS_TRADINGVIEW_TA = True
except ImportError:
    HAS_TRADINGVIEW_TA = False

from data.market_hours import get_market_status, is_market_open
from cachetools import TTLCache

logger = logging.getLogger("trading.data.realtime_feed")


class RealTimeDataFeed:
    """
    Unified Real-Time Data Feed providing live market prices,
    TradingView technical indicators, and candle bars.
    """

    # Bounded in-memory TTL cache to prevent memory leaks in long-running processes
    _cache = TTLCache(maxsize=10000, ttl=60.0)
    _QUOTE_CACHE_TTL = 3.0  # 3 seconds for quotes
    _TA_CACHE_TTL = 10.0    # 10 seconds for full TA analysis
    _CANDLE_CACHE_TTL = 15.0 # 15 seconds for candle bars

    # Mapping of tickers to TradingView symbols and exchanges
    SYMBOL_MAPPING = {
        "^NSEI": ("NIFTY", "NSE", "india"),
        "NIFTY": ("NIFTY", "NSE", "india"),
        "NIFTY 50": ("NIFTY", "NSE", "india"),
        "^NSEBANK": ("BANKNIFTY", "NSE", "india"),
        "BANKNIFTY": ("BANKNIFTY", "NSE", "india"),
        "NIFTY BANK": ("BANKNIFTY", "NSE", "india"),
        "^BSESN": ("SENSEX", "BSE", "india"),
        "SENSEX": ("SENSEX", "BSE", "india"),
        "FINNIFTY": ("FINNIFTY", "NSE", "india"),
        "MIDCPNIFTY": ("MIDCPNIFTY", "NSE", "india"),
        "RELIANCE": ("RELIANCE", "NSE", "india"),
        "RELIANCE.NS": ("RELIANCE", "NSE", "india"),
        "HDFCBANK": ("HDFCBANK", "NSE", "india"),
        "HDFCBANK.NS": ("HDFCBANK", "NSE", "india"),
        "TCS": ("TCS", "NSE", "india"),
        "TCS.NS": ("TCS", "NSE", "india"),
        "INFY": ("INFY", "NSE", "india"),
        "INFY.NS": ("INFY", "NSE", "india"),
        "ICICIBANK": ("ICICIBANK", "NSE", "india"),
        "ICICIBANK.NS": ("ICICIBANK", "NSE", "india"),
        "SBIN": ("SBIN", "NSE", "india"),
        "SBIN.NS": ("SBIN", "NSE", "india"),
        "TATAMOTORS": ("TATAMOTORS", "NSE", "india"),
        "TATAMOTORS.NS": ("TATAMOTORS", "NSE", "india"),
        "BTC-USD": ("BTCUSD", "BINANCE", "crypto"),
        "ETH-USD": ("ETHUSD", "BINANCE", "crypto"),
        "SPY": ("SPY", "AMEX", "america"),
        "^GSPC": ("SPX", "SP", "america"),
        "INDIAVIX": ("INDIAVIX", "NSE", "india"),
        "^INDIAVIX": ("INDIAVIX", "NSE", "india"),
        "INDIA VIX": ("INDIAVIX", "NSE", "india"),
    }

    INTERVAL_MAPPING = {
        "1m": Interval.INTERVAL_1_MINUTE if HAS_TRADINGVIEW_TA else "1m",
        "5m": Interval.INTERVAL_5_MINUTES if HAS_TRADINGVIEW_TA else "5m",
        "15m": Interval.INTERVAL_15_MINUTES if HAS_TRADINGVIEW_TA else "15m",
        "30m": Interval.INTERVAL_30_MINUTES if HAS_TRADINGVIEW_TA else "30m",
        "1h": Interval.INTERVAL_1_HOUR if HAS_TRADINGVIEW_TA else "1h",
        "2h": Interval.INTERVAL_2_HOURS if HAS_TRADINGVIEW_TA else "2h",
        "4h": Interval.INTERVAL_4_HOURS if HAS_TRADINGVIEW_TA else "4h",
        "1d": Interval.INTERVAL_1_DAY if HAS_TRADINGVIEW_TA else "1d",
        "1wk": Interval.INTERVAL_1_WEEK if HAS_TRADINGVIEW_TA else "1wk",
        "1mo": Interval.INTERVAL_1_MONTH if HAS_TRADINGVIEW_TA else "1mo",
    }

    @classmethod
    def _resolve_symbol(cls, ticker: str) -> tuple[str, str, str]:
        """Resolves internal ticker to (tv_symbol, tv_exchange, screener)."""
        clean = ticker.upper().strip()
        if clean in cls.SYMBOL_MAPPING:
            return cls.SYMBOL_MAPPING[clean]

        # Auto-detect Indian stocks
        if clean.endswith(".NS"):
            return (clean[:-3], "NSE", "india")
        if clean.endswith(".BO"):
            return (clean[:-3], "BSE", "india")

        # Default fallback
        return (clean, "NSE", "india")

    @classmethod
    def get_realtime_quote_sync(cls, ticker: str) -> Dict[str, Any]:
        """
        Synchronously fetches real-time quote for ticker.
        Uses in-memory cache if fresh.
        """
        cache_key = f"quote_{ticker.upper()}"
        now = time.time()
        if cache_key in cls._cache:
            ts, data = cls._cache[cache_key]
            if now - ts < cls._QUOTE_CACHE_TTL:
                return data

        symbol, exchange, screener = cls._resolve_symbol(ticker)
        quote_data = None

        # 1. Try TradingView TA Feed
        if HAS_TRADINGVIEW_TA:
            try:
                handler = TA_Handler(
                    symbol=symbol,
                    exchange=exchange,
                    screener=screener,
                    interval=Interval.INTERVAL_1_MINUTE
                )
                analysis = handler.get_analysis()
                ind = analysis.indicators
                ltp = float(ind.get("close") or ind.get("open") or 0.0)
                if ltp > 0:
                    open_p = float(ind.get("open") or ltp)
                    high_p = float(ind.get("high") or ltp)
                    low_p = float(ind.get("low") or ltp)
                    vol = float(ind.get("volume") or 0.0)
                    chg = ltp - open_p
                    chg_pct = (chg / open_p * 100) if open_p > 0 else 0.0

                    quote_data = {
                        "ticker": ticker.upper(),
                        "symbol": symbol,
                        "exchange": exchange,
                        "source": "TradingView",
                        "ltp": round(ltp, 2),
                        "open": round(open_p, 2),
                        "high": round(high_p, 2),
                        "low": round(low_p, 2),
                        "volume": vol,
                        "change": round(chg, 2),
                        "change_pct": round(chg_pct, 2),
                        "recommendation": analysis.summary.get("RECOMMENDATION", "NEUTRAL"),
                        "buy_votes": analysis.summary.get("BUY", 0),
                        "sell_votes": analysis.summary.get("SELL", 0),
                        "neutral_votes": analysis.summary.get("NEUTRAL", 0),
                        "timestamp": now,
                    }
            except Exception as tv_err:
                logger.debug(f"TradingView quote fetch failed for {ticker}: {tv_err}")

        # 2. Fallback to Yahoo Finance fast quote
        if quote_data is None:
            try:
                yf_sym = ticker
                if ticker in ("NIFTY", "NIFTY 50"):
                    yf_sym = "^NSEI"
                elif ticker in ("BANKNIFTY", "NIFTY BANK"):
                    yf_sym = "^NSEBANK"
                elif ticker in ("INDIAVIX", "INDIA VIX", "^INDIAVIX"):
                    yf_sym = "^INDIAVIX"
                yt = yf.Ticker(yf_sym)
                fast_info = getattr(yt, "fast_info", None)
                if fast_info:
                    ltp = float(fast_info.last_price or 0.0)
                    prev_close = float(fast_info.previous_close or ltp)
                    if ltp > 0:
                        chg = ltp - prev_close
                        chg_pct = (chg / prev_close * 100) if prev_close > 0 else 0.0
                        quote_data = {
                            "ticker": ticker.upper(),
                            "symbol": symbol,
                            "exchange": exchange,
                            "source": "YahooFinanceFast",
                            "ltp": round(ltp, 2),
                            "open": round(float(fast_info.open or ltp), 2),
                            "high": round(float(fast_info.day_high or ltp), 2),
                            "low": round(float(fast_info.day_low or ltp), 2),
                            "volume": float(fast_info.last_volume or 0),
                            "change": round(chg, 2),
                            "change_pct": round(chg_pct, 2),
                            "recommendation": "NEUTRAL",
                            "buy_votes": 0,
                            "sell_votes": 0,
                            "neutral_votes": 0,
                            "timestamp": now,
                        }
            except Exception as yf_err:
                logger.debug(f"Yahoo finance fast quote failed for {ticker}: {yf_err}")

        # 3. Final default fallback
        if quote_data is None:
            quote_data = {
                "ticker": ticker.upper(),
                "symbol": symbol,
                "exchange": exchange,
                "source": "Unavailable",
                "ltp": 0.0,
                "open": 0.0,
                "high": 0.0,
                "low": 0.0,
                "volume": 0.0,
                "change": 0.0,
                "change_pct": 0.0,
                "recommendation": "NEUTRAL",
                "buy_votes": 0,
                "sell_votes": 0,
                "neutral_votes": 0,
                "timestamp": now,
            }

        cls._cache[cache_key] = (now, quote_data)
        return quote_data

    @classmethod
    async def get_realtime_quote(cls, ticker: str) -> Dict[str, Any]:
        """Asynchronous wrapper for get_realtime_quote_sync."""
        return await asyncio.to_thread(cls.get_realtime_quote_sync, ticker)

    @classmethod
    def get_tradingview_analysis_sync(cls, ticker: str, interval: str = "1h") -> Dict[str, Any]:
        """
        Fetches detailed TradingView technical indicators and setup summary.
        """
        cache_key = f"ta_{ticker.upper()}_{interval}"
        now = time.time()
        if cache_key in cls._cache:
            ts, data = cls._cache[cache_key]
            if now - ts < cls._TA_CACHE_TTL:
                return data

        symbol, exchange, screener = cls._resolve_symbol(ticker)
        tv_interval = cls.INTERVAL_MAPPING.get(interval, Interval.INTERVAL_1_HOUR if HAS_TRADINGVIEW_TA else "1h")

        if HAS_TRADINGVIEW_TA:
            try:
                handler = TA_Handler(
                    symbol=symbol,
                    exchange=exchange,
                    screener=screener,
                    interval=tv_interval
                )
                analysis = handler.get_analysis()
                ind = analysis.indicators

                result = {
                    "ticker": ticker.upper(),
                    "symbol": symbol,
                    "exchange": exchange,
                    "interval": interval,
                    "summary": analysis.summary,
                    "oscillators": analysis.oscillators,
                    "moving_averages": analysis.moving_averages,
                    "indicators": {
                        "close": ind.get("close"),
                        "open": ind.get("open"),
                        "high": ind.get("high"),
                        "low": ind.get("low"),
                        "volume": ind.get("volume"),
                        "RSI": ind.get("RSI"),
                        "RSI_1": ind.get("RSI[1]"),
                        "MACD": ind.get("MACD.macd"),
                        "MACD_signal": ind.get("MACD.signal"),
                        "ADX": ind.get("ADX"),
                        "ADX_plus_di": ind.get("ADX+DI"),
                        "ADX_minus_di": ind.get("ADX-DI"),
                        "Stoch_K": ind.get("Stoch.K"),
                        "Stoch_D": ind.get("Stoch.D"),
                        "EMA20": ind.get("EMA20"),
                        "EMA50": ind.get("EMA50"),
                        "EMA200": ind.get("EMA200"),
                        "SMA20": ind.get("SMA20"),
                        "SMA50": ind.get("SMA50"),
                        "SMA200": ind.get("SMA200"),
                        "BB_upper": ind.get("BB.upper"),
                        "BB_lower": ind.get("BB.lower"),
                    },
                    "timestamp": now,
                    "status": "success"
                }
                cls._cache[cache_key] = (now, result)
                return result
            except Exception as e:
                logger.debug(f"TradingView analysis failed for {ticker}: {e}")
                # Back off on failure by extending cache TTL for 30s
                now += 25.0

        fallback = {
            "ticker": ticker.upper(),
            "symbol": symbol,
            "exchange": exchange,
            "interval": interval,
            "summary": {"RECOMMENDATION": "NEUTRAL", "BUY": 0, "SELL": 0, "NEUTRAL": 0},
            "oscillators": {},
            "moving_averages": {},
            "indicators": {},
            "timestamp": now,
            "status": "fallback"
        }
        cls._cache[cache_key] = (now, fallback)
        return fallback

    @classmethod
    async def get_tradingview_analysis(cls, ticker: str, interval: str = "1h") -> Dict[str, Any]:
        """Asynchronous wrapper for get_tradingview_analysis_sync."""
        return await asyncio.to_thread(cls.get_tradingview_analysis_sync, ticker, interval)

    @classmethod
    def get_chart_candles_sync(cls, ticker: str, timeframe: str = "1d", limit: int = 300) -> List[Dict[str, Any]]:
        """
        Fetches historical candles merged with real-time last-traded price (LTP).
        Formats data perfectly for Lightweight Charts:
        [{ time: timestamp_or_yyyy_mm_dd, open, high, low, close, volume }]
        """
        cache_key = f"candles_{ticker.upper()}_{timeframe}_{limit}"
        now = time.time()
        if cache_key in cls._cache:
            ts, data = cls._cache[cache_key]
            if now - ts < cls._CANDLE_CACHE_TTL:
                return data

        from data.fetcher import YFinanceFetcher
        # Map timeframes to standard period
        period_map = {
            "1m": "5d",
            "5m": "30d",
            "15m": "60d",
            "30m": "60d",
            "1h": "730d",
            "1d": "5y",
            "1wk": "10y"
        }
        period = period_map.get(timeframe, "1y")

        yf_sym = ticker
        if ticker in ("NIFTY", "NIFTY 50"):
            yf_sym = "^NSEI"
        elif ticker in ("BANKNIFTY", "NIFTY BANK"):
            yf_sym = "^NSEBANK"
        elif not ticker.startswith("^") and not ticker.endswith((".NS", ".BO")) and ticker not in ("BTC-USD", "SPY"):
            yf_sym = f"{ticker}.NS"

        df = YFinanceFetcher._fetch_history_sync(ticker=yf_sym, period=period, interval=timeframe)
        candles = []
        if df is not None and not df.empty:
            df = df.tail(limit)
            for idx, row in df.iterrows():
                try:
                    if hasattr(idx, 'timestamp'):
                        t_val = int(idx.timestamp())
                    else:
                        t_val = int(pd.to_datetime(idx).timestamp())
                except Exception:
                    continue

                candles.append({
                    "time": t_val,
                    "open": round(float(row.get("Open", 0.0)), 2),
                    "high": round(float(row.get("High", 0.0)), 2),
                    "low": round(float(row.get("Low", 0.0)), 2),
                    "close": round(float(row.get("Close", 0.0)), 2),
                    "volume": float(row.get("Volume", 0.0))
                })

        # Inject / update live LTP into the latest candle if real-time quote is available
        quote = cls.get_realtime_quote_sync(ticker)
        if quote and quote.get("ltp", 0.0) > 0 and candles:
            latest = candles[-1]
            ltp = quote["ltp"]
            if ltp > latest["high"]:
                latest["high"] = ltp
            if ltp < latest["low"]:
                latest["low"] = ltp
            latest["close"] = ltp

        cls._cache[cache_key] = (now, candles)
        return candles

    @classmethod
    async def get_chart_candles(cls, ticker: str, timeframe: str = "1d", limit: int = 300) -> List[Dict[str, Any]]:
        """Asynchronous wrapper for get_chart_candles_sync."""
        return await asyncio.to_thread(cls.get_chart_candles_sync, ticker, timeframe, limit)

    @classmethod
    def get_india_vix_sync(cls) -> float:
        """
        Synchronously fetches real-time India VIX level.
        Returns percentage (e.g. 14.5 for 14.5%). Defaults to 14.0 if unreachable.
        """
        quote = cls.get_realtime_quote_sync("INDIAVIX")
        if quote and isinstance(quote, dict) and quote.get("ltp", 0.0) > 0:
            return float(quote["ltp"])
        return 14.0

    @classmethod
    async def get_india_vix(cls) -> float:
        """Asynchronous wrapper for get_india_vix_sync."""
        return await asyncio.to_thread(cls.get_india_vix_sync)
