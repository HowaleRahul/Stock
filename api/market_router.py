"""
Market Data & Real-Time Charting API Router.

Provides:
- Live market session & trading hours (NSE/BSE)
- Real-time quotes with LTP & day metrics (TradingView / Yahoo fallback)
- Real-time candle bars formatted for TradingView Lightweight Charts
- Full TradingView technical analysis (RSI, MACD, ADX, EMAs, Recommendation)
- Watchlist of active Indian market indices and heavyweights
"""

import time
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Dict, Any, List, Optional


from data.market_hours import get_market_status, is_market_open
from data.realtime_feed import RealTimeDataFeed
from api.auth import get_api_key, rate_limiter

router = APIRouter(
    prefix="/api/v1/market",
    tags=["Market Data"],
    dependencies=[Depends(get_api_key)],
)

WATCHLIST_TICKERS = [
    {"ticker": "NIFTY", "name": "Nifty 50 Index (F&O)", "tv_symbol": "NSE:NIFTY"},
    {"ticker": "BANKNIFTY", "name": "Bank Nifty Index (F&O)", "tv_symbol": "NSE:BANKNIFTY"},
    {"ticker": "SENSEX", "name": "BSE Sensex Index (F&O)", "tv_symbol": "BSE:SENSEX"},
    {"ticker": "FINNIFTY", "name": "FinNifty Index (F&O)", "tv_symbol": "NSE:FINNIFTY"},
    {"ticker": "MIDCPNIFTY", "name": "Midcap Nifty Index (F&O)", "tv_symbol": "NSE:MIDCPNIFTY"},
]


@router.get("/status")
async def market_status(
    exchange: str = Query("NSE", description="Exchange code: NSE, BSE, CRYPTO"),
    _rate_limit: bool = Depends(rate_limiter(60))
):
    """Returns the current trading session and hours for the specified exchange."""
    return get_market_status(exchange)


@router.get("/quote/{ticker}")
async def get_quote(
    ticker: str,
    _rate_limit: bool = Depends(rate_limiter(60))
):
    """
    Returns real-time LTP, high, low, volume, and TradingView recommendation.
    """
    clean_ticker = ticker.strip().upper()
    quote = await RealTimeDataFeed.get_realtime_quote(clean_ticker)
    if not quote:
        raise HTTPException(status_code=404, detail=f"Quote not available for {ticker}")
    return quote


@router.get("/candles/{ticker}")
async def get_candles(
    ticker: str,
    timeframe: str = Query("1d", description="Timeframe: 1m, 5m, 15m, 30m, 1h, 1d, 1wk"),
    limit: int = Query(300, ge=10, le=1000, description="Max candle bars to return"),
    _rate_limit: bool = Depends(rate_limiter(60))
):
    """
    Returns candle bars formatted for Lightweight Charts, with live LTP injected into the latest bar.
    """
    clean_ticker = ticker.strip().upper()
    candles = await RealTimeDataFeed.get_chart_candles(clean_ticker, timeframe=timeframe, limit=limit)
    return {
        "ticker": clean_ticker,
        "timeframe": timeframe,
        "count": len(candles),
        "candles": candles
    }


@router.get("/ta/{ticker}")
async def get_tradingview_ta(
    ticker: str,
    interval: str = Query("1h", description="Interval: 1m, 5m, 15m, 1h, 1d, 1wk"),
    _rate_limit: bool = Depends(rate_limiter(60))
):
    """
    Returns complete TradingView technical analysis, oscillators, moving averages, and indicators.
    """
    clean_ticker = ticker.strip().upper()
    return await RealTimeDataFeed.get_tradingview_analysis(clean_ticker, interval=interval)


@router.get("/watchlist")
async def get_watchlist(
    _rate_limit: bool = Depends(rate_limiter(60))
):
    """
    Returns real-time prices, % changes, and TradingView recommendations for the active watchlist.
    """
    async def _fetch_item(item):
        quote = await RealTimeDataFeed.get_realtime_quote(item["ticker"])
        return {
            "ticker": item["ticker"],
            "name": item["name"],
            "tv_symbol": item["tv_symbol"],
            "ltp": quote.get("ltp", 0.0),
            "change": quote.get("change", 0.0),
            "change_pct": quote.get("change_pct", 0.0),
            "recommendation": quote.get("recommendation", "NEUTRAL"),
            "buy_votes": quote.get("buy_votes", 0),
            "sell_votes": quote.get("sell_votes", 0),
            "neutral_votes": quote.get("neutral_votes", 0),
        }

    results = await asyncio.gather(*[_fetch_item(item) for item in WATCHLIST_TICKERS])
    return {
        "market_status": get_market_status("NSE"),
        "watchlist": list(results)
    }


# ===========================================================================
# Option Premium Charting Endpoint
# ===========================================================================

import math
from ml.options_engine import DerivativeEngine

_deriv_engine = DerivativeEngine()


@router.get("/option-chart")
async def get_option_chart(
    underlying: str = Query("NIFTY", description="Underlying index: NIFTY, BANKNIFTY, FINNIFTY"),
    strike: float = Query(22800.0, description="Option strike price"),
    option_type: str = Query("CE", description="CE for Call, PE for Put"),
    timeframe: str = Query("1h", description="Timeframe: 5m, 15m, 1h, 1d"),
    limit: int = Query(100, ge=10, le=500),
    _rate_limit: bool = Depends(rate_limiter(60))
):
    """
    Returns candlestick chart data (OHLCV) for a specific Option contract,
    calculated dynamically via Black-Scholes using real-time underlying index candles,
    option Greeks (Delta, Theta, Gamma, Vega), and Intraday Option VWAP.
    """
    clean_und = underlying.strip().upper()
    opt_type = option_type.strip().upper()
    if opt_type not in ("CE", "PE"):
        opt_type = "CE"

    # Fetch underlying spot candles
    candles = await RealTimeDataFeed.get_chart_candles(clean_und, timeframe=timeframe, limit=limit)
    if not candles:
        raise HTTPException(status_code=404, detail=f"No underlying data available for {clean_und}")

    # Quote for current spot & baseline IV
    quote = await RealTimeDataFeed.get_realtime_quote(clean_und)
    current_spot = quote.get("ltp", candles[-1]["close"])
    sigma = 0.14  # Default 14% IV baseline
    r = 0.065     # 6.5% interest rate
    interval = _deriv_engine.get_strike_interval(clean_und)

    n_bars = len(candles)
    option_candles = []
    cum_pv = 0.0
    cum_vol = 0.0

    for i, bar in enumerate(candles):
        # Progressively calculate time to expiry across the candle series
        days_left = max(0.02, 7.0 - ((n_bars - 1 - i) / max(1, n_bars)) * 2.0)
        T = days_left / 365.0

        if opt_type == "CE":
            o_prem = _deriv_engine.black_scholes(bar["open"], strike, T, r, sigma, "CE")["premium"]
            h_prem = _deriv_engine.black_scholes(bar["high"], strike, T, r, sigma, "CE")["premium"]
            l_prem = _deriv_engine.black_scholes(bar["low"], strike, T, r, sigma, "CE")["premium"]
            c_prem = _deriv_engine.black_scholes(bar["close"], strike, T, r, sigma, "CE")["premium"]
        else:
            o_prem = _deriv_engine.black_scholes(bar["open"], strike, T, r, sigma, "PE")["premium"]
            h_prem = _deriv_engine.black_scholes(bar["low"], strike, T, r, sigma, "PE")["premium"]
            l_prem = _deriv_engine.black_scholes(bar["high"], strike, T, r, sigma, "PE")["premium"]
            c_prem = _deriv_engine.black_scholes(bar["close"], strike, T, r, sigma, "PE")["premium"]

        high_val = max(h_prem, o_prem, c_prem)
        low_val = min(l_prem, o_prem, c_prem)

        spot_close = bar["close"]
        dist = abs(spot_close - strike) / max(1, interval)
        base_vol = bar.get("volume", 1000)
        opt_vol = int(max(10, base_vol * math.exp(-0.4 * (dist ** 2))))

        cum_pv += c_prem * opt_vol
        cum_vol += opt_vol
        vwap_val = round(cum_pv / cum_vol, 2) if cum_vol > 0 else round(c_prem, 2)

        option_candles.append({
            "time": bar["time"],
            "open": round(o_prem, 2),
            "high": round(high_val, 2),
            "low": round(low_val, 2),
            "close": round(c_prem, 2),
            "volume": opt_vol,
            "vwap": vwap_val,
        })

    latest_greeks = _deriv_engine.black_scholes(current_spot, strike, 7.0 / 365.0, r, sigma, opt_type)
    option_symbol = f"{clean_und} {int(strike)} {opt_type}"

    latest_close = option_candles[-1]["close"]
    latest_vwap = option_candles[-1]["vwap"]
    above_vwap = latest_close >= latest_vwap

    return {
        "option_symbol": option_symbol,
        "underlying": clean_und,
        "current_spot": round(current_spot, 2),
        "strike": strike,
        "option_type": opt_type,
        "timeframe": timeframe,
        "current_premium": latest_close,
        "lot_size": _deriv_engine.get_lot_size(clean_und),
        "greeks": {
            "delta": round(latest_greeks["delta"], 3),
            "theta": round(latest_greeks["theta"], 2),
            "gamma": round(latest_greeks["gamma"], 5),
            "vega": round(latest_greeks["vega"], 3),
            "iv": round(sigma * 100, 1),
        },
        "indicators": {
            "vwap": latest_vwap,
            "is_above_vwap": above_vwap,
            "day_high": max(c["high"] for c in option_candles),
            "day_low": min(c["low"] for c in option_candles),
        },
        "count": len(option_candles),
        "candles": option_candles
    }


@router.get("/live-tick/{ticker}")
async def get_live_tick(
    ticker: str,
    timeframe: str = Query("1h", description="Candle timeframe to update"),
    _rate_limit: bool = Depends(rate_limiter(120))
):
    """
    Returns high-frequency live market tick for charts (LTP, bid/ask, day metrics,
    and the real-time updating active candle bar).
    Used by frontend charts to stretch candles up/down dynamically like broker terminals.
    """
    clean_sym = ticker.strip().upper()
    quote = await RealTimeDataFeed.get_realtime_quote(clean_sym)
    ltp = float(quote.get("ltp", 0.0))

    candles = await RealTimeDataFeed.get_chart_candles(clean_sym, timeframe=timeframe, limit=2)
    latest_candle = candles[-1] if candles else {
        "time": int(time.time()),
        "open": ltp,
        "high": ltp,
        "low": ltp,
        "close": ltp,
        "volume": float(quote.get("volume", 0.0))
    }

    # Dynamic spread simulation for bid/ask
    spread = max(0.05, round(ltp * 0.0002, 2))
    bid = round(ltp - spread / 2.0, 2)
    ask = round(ltp + spread / 2.0, 2)

    status = get_market_status("NSE")

    return {
        "ticker": clean_sym,
        "ltp": ltp,
        "bid": bid,
        "ask": ask,
        "open": quote.get("open", ltp),
        "high": quote.get("high", ltp),
        "low": quote.get("low", ltp),
        "volume": quote.get("volume", 0.0),
        "change": quote.get("change", 0.0),
        "change_pct": quote.get("change_pct", 0.0),
        "is_market_open": status["is_open"],
        "session": status["session"],
        "market_phase": status.get("market_phase", "REGULAR"),
        "timestamp": time.time(),
        "candle": latest_candle
    }


@router.get("/option-tick")
async def get_option_tick(
    underlying: str = Query("NIFTY", description="Index: NIFTY, BANKNIFTY, FINNIFTY"),
    strike: float = Query(22800.0, description="Strike price"),
    option_type: str = Query("CE", description="CE or PE"),
    _rate_limit: bool = Depends(rate_limiter(120))
):
    """
    Returns instantaneous live tick for an Option contract, including current premium,
    Greeks, intraday Option VWAP, and the real-time updating active option candle.
    """
    clean_und = underlying.strip().upper()
    opt_type = option_type.strip().upper()
    if opt_type not in ("CE", "PE"):
        opt_type = "CE"

    quote = await RealTimeDataFeed.get_realtime_quote(clean_und)
    current_spot = float(quote.get("ltp", 22800.0))
    sigma = 0.14
    r = 0.065
    T = 7.0 / 365.0

    bs_res = _deriv_engine.black_scholes(current_spot, strike, T, r, sigma, opt_type)
    premium = round(bs_res["premium"], 2)

    option_symbol = f"{clean_und} {int(strike)} {opt_type}"
    status = get_market_status("NSE")

    now_t = int(time.time())

    return {
        "option_symbol": option_symbol,
        "underlying": clean_und,
        "current_spot": current_spot,
        "strike": strike,
        "option_type": opt_type,
        "premium": premium,
        "delta": round(bs_res["delta"], 3),
        "theta": round(bs_res["theta"], 2),
        "gamma": round(bs_res["gamma"], 5),
        "vega": round(bs_res["vega"], 3),
        "iv": round(sigma * 100, 1),
        "lot_size": _deriv_engine.get_lot_size(clean_und),
        "is_market_open": status["is_open"],
        "session": status["session"],
        "timestamp": now_t,
        "candle": {
            "time": now_t,
            "open": premium,
            "high": premium,
            "low": premium,
            "close": premium,
            "volume": 100,
            "vwap": premium
        }
    }


@router.get("/news-sentiment/{ticker}")
async def get_index_news_sentiment(
    ticker: str,
    _rate_limit: bool = Depends(rate_limiter(60))
):
    """
    Returns live Indian market news headlines and VADER financial sentiment metrics
    for an F&O underlying index or stock (NIFTY, BANKNIFTY, SENSEX).
    """
    from data.news_fetcher import NewsFetcher
    clean = ticker.strip().upper()
    summary = await NewsFetcher.get_sentiment_summary(clean)
    return summary



