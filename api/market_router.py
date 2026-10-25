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

import re

def _sanitize_ticker(ticker: str) -> str:
    if not ticker or not isinstance(ticker, str):
        raise HTTPException(status_code=400, detail="Ticker symbol cannot be empty.")
    if "\x00" in ticker:
        raise HTTPException(status_code=400, detail="Null byte injection detected in ticker.")
    clean = ticker.strip().upper()
    if not clean or len(clean) > 64 or ".." in clean or "/" in clean or "\\" in clean:
        raise HTTPException(status_code=400, detail="Invalid ticker symbol.")
    if not re.match(r"^[A-Z0-9\._\-\^\=]+$", clean):
        raise HTTPException(status_code=400, detail="Invalid characters in ticker symbol.")
    return clean


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
    clean_ex = exchange.strip().upper().replace("\x00", "")[:16]
    return get_market_status(clean_ex)


@router.get("/quote/{ticker}")
async def get_quote(
    ticker: str,
    _rate_limit: bool = Depends(rate_limiter(60))
):
    """
    Returns real-time LTP, high, low, volume, and TradingView recommendation.
    """
    clean_ticker = _sanitize_ticker(ticker)
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
    clean_ticker = _sanitize_ticker(ticker)
    valid_timeframes = {"1m", "5m", "15m", "30m", "1h", "1d", "1wk"}
    if timeframe not in valid_timeframes:
        raise HTTPException(status_code=400, detail=f"Invalid timeframe '{timeframe}'. Allowed: {sorted(valid_timeframes)}")
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
    clean_ticker = _sanitize_ticker(ticker)
    valid_intervals = {"1m", "5m", "15m", "1h", "1d", "1wk"}
    if interval not in valid_intervals:
        raise HTTPException(status_code=400, detail=f"Invalid interval '{interval}'. Allowed: {sorted(valid_intervals)}")
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
    strike: float = Query(22800.0, ge=1.0, le=10_000_000.0, allow_inf_nan=False, description="Option strike price"),
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
    clean_und = _sanitize_ticker(underlying)
    opt_type = option_type.strip().upper()
    if opt_type not in ("CE", "PE"):
        raise HTTPException(status_code=400, detail="Invalid option_type. Must be 'CE' or 'PE'.")

    valid_timeframes = {"1m", "5m", "15m", "30m", "1h", "1d", "1wk"}
    if timeframe not in valid_timeframes:
        raise HTTPException(status_code=400, detail=f"Invalid timeframe '{timeframe}'. Allowed: {sorted(valid_timeframes)}")

    if not math.isfinite(strike) or strike <= 0:
        raise HTTPException(status_code=400, detail="Invalid strike price.")

    # Fetch underlying spot candles
    candles = await RealTimeDataFeed.get_chart_candles(clean_und, timeframe=timeframe, limit=limit)
    if not candles:
        raise HTTPException(status_code=404, detail=f"No underlying data available for {clean_und}")

    # Quote for current spot & baseline IV
    quote = await RealTimeDataFeed.get_realtime_quote(clean_und)
    raw_spot = quote.get("ltp") if quote else None
    if raw_spot is not None and isinstance(raw_spot, (int, float)) and math.isfinite(raw_spot) and raw_spot > 0:
        current_spot = float(raw_spot)
    else:
        current_spot = float(candles[-1]["close"])
    sigma = _deriv_engine.fetch_live_iv(ticker=clean_und)
    r = _deriv_engine.RISK_FREE_RATE
    interval = _deriv_engine.get_strike_interval(clean_und)
    dynamic_dte = _deriv_engine.get_days_to_expiry(clean_und)

    n_bars = len(candles)
    option_candles = []
    cum_pv = 0.0
    cum_vol = 0.0

    for i, bar in enumerate(candles):
        # Progressively calculate dynamic time to expiry across the candle series
        days_left = max(0.01, dynamic_dte - ((n_bars - 1 - i) / max(1, n_bars)) * min(dynamic_dte * 0.5, 2.0))
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

    if not option_candles:
        raise HTTPException(status_code=404, detail=f"No option candle data available for {clean_und}")

    latest_greeks = _deriv_engine.black_scholes(current_spot, strike, max(0.001, dynamic_dte / 365.0), r, sigma, opt_type)
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
        "days_to_expiry": round(dynamic_dte, 4),
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
    clean_sym = _sanitize_ticker(ticker)
    valid_timeframes = {"1m", "5m", "15m", "30m", "1h", "1d", "1wk"}
    if timeframe not in valid_timeframes:
        raise HTTPException(status_code=400, detail=f"Invalid timeframe '{timeframe}'. Allowed: {sorted(valid_timeframes)}")

    quote = await RealTimeDataFeed.get_realtime_quote(clean_sym)
    raw_ltp = quote.get("ltp", 0.0)
    ltp = float(raw_ltp) if (raw_ltp is not None and isinstance(raw_ltp, (int, float)) and math.isfinite(raw_ltp) and raw_ltp > 0) else 0.0

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
    spread = max(0.05, round(ltp * 0.0002, 2)) if ltp > 0 else 0.05
    bid = max(0.0, round(ltp - spread / 2.0, 2)) if ltp > 0 else 0.0
    ask = max(0.0, round(ltp + spread / 2.0, 2)) if ltp > 0 else 0.0

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
    strike: float = Query(22800.0, ge=1.0, le=10_000_000.0, allow_inf_nan=False, description="Strike price"),
    option_type: str = Query("CE", description="CE or PE"),
    _rate_limit: bool = Depends(rate_limiter(120))
):
    """
    Returns instantaneous live tick for an Option contract, including current premium,
    Greeks, intraday Option VWAP, and the real-time updating active option candle.
    """
    clean_und = _sanitize_ticker(underlying)
    opt_type = option_type.strip().upper()
    if opt_type not in ("CE", "PE"):
        raise HTTPException(status_code=400, detail="Invalid option_type. Must be 'CE' or 'PE'.")

    if not math.isfinite(strike) or strike <= 0:
        raise HTTPException(status_code=400, detail="Invalid strike price.")

    quote = await RealTimeDataFeed.get_realtime_quote(clean_und)
    raw_spot = quote.get("ltp") if quote else None
    if raw_spot is not None and isinstance(raw_spot, (int, float)) and math.isfinite(raw_spot) and raw_spot > 0:
        current_spot = float(raw_spot)
    else:
        current_spot = 22800.0
    sigma = _deriv_engine.fetch_live_iv(ticker=clean_und)
    r = _deriv_engine.RISK_FREE_RATE
    dynamic_dte = _deriv_engine.get_days_to_expiry(clean_und)
    T = max(0.001, dynamic_dte / 365.0)

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
        "days_to_expiry": round(dynamic_dte, 4),
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


@router.get("/option-strategy-payoff")
async def get_strategy_payoff(
    underlying: str = Query("NIFTY", description="Underlying index: NIFTY, BANKNIFTY, SENSEX, FINNIFTY, MIDCPNIFTY"),
    strategy: str = Query("BULL_PUT_SPREAD", description="BUY_CALL, BUY_PUT, SELL_CALL, SELL_PUT, BULL_PUT_SPREAD, BEAR_CALL_SPREAD, LONG_FUTURES, SHORT_FUTURES"),
    strike: Optional[float] = Query(None, description="Primary strike price (ATM if omitted)"),
    _rate_limit: bool = Depends(rate_limiter(60))
):
    """
    Computes institutional Payoff Diagrams and Greeks for Indian F&O strategies:
    - Long Option (CE / PE Buying)
    - Short Option (CE / PE Directional Writing with positive theta)
    - Bull Put Credit Spread (Sell OTM PE, Buy lower PE hedge)
    - Bear Call Credit Spread (Sell OTM CE, Buy higher CE hedge)
    - Long / Short Futures
    Returns curve data points, breakeven levels, max profit, max loss, and net margin.
    """
    clean_und = _sanitize_ticker(underlying)
    strat = strategy.strip().upper()
    valid_strats = {
        "BUY_CALL", "BUY_PUT", "SELL_CALL", "SELL_PUT",
        "BULL_PUT_SPREAD", "BEAR_CALL_SPREAD", "LONG_FUTURES", "SHORT_FUTURES"
    }
    if strat not in valid_strats:
        raise HTTPException(status_code=400, detail=f"Invalid strategy '{strategy}'. Allowed: {sorted(valid_strats)}")

    quote = await RealTimeDataFeed.get_realtime_quote(clean_und)
    current_spot = float(quote.get("ltp", 24000.0))
    interval = _deriv_engine.get_strike_interval(clean_und)
    lot_size = _deriv_engine.get_lot_size(clean_und)
    sigma = _deriv_engine.fetch_live_iv(ticker=clean_und)
    r = _deriv_engine.RISK_FREE_RATE
    dynamic_dte = _deriv_engine.get_days_to_expiry(clean_und)
    T = max(0.001, dynamic_dte / 365.0)

    atm_strike = float(int(interval * round(current_spot / interval)))
    prim_strike = float(strike) if strike is not None and math.isfinite(strike) and strike > 0 else atm_strike

    # Generate spot range (+/- 5% around spot in 41 steps)
    spot_min = round(current_spot * 0.95, 2)
    spot_max = round(current_spot * 1.05, 2)
    spot_steps = [round(spot_min + (spot_max - spot_min) * (i / 40.0), 2) for i in range(41)]

    payoff_curve = []
    legs = []
    breakevens = []
    max_profit = 0.0
    max_loss = 0.0
    margin_req = 0.0

    if strat == "BUY_CALL":
        bs_entry = _deriv_engine.black_scholes(current_spot, prim_strike, T, r, sigma, "CE")
        prem = bs_entry["premium"]
        margin_req = prem * lot_size
        max_loss = -margin_req
        max_profit = float("inf")
        be = prim_strike + prem
        breakevens.append(round(be, 2))
        legs.append({"type": "BUY_CE", "strike": prim_strike, "premium": prem})

        for s in spot_steps:
            val_at_exp = max(0.0, s - prim_strike)
            pnl = (val_at_exp - prem) * lot_size
            payoff_curve.append({"spot": s, "pnl": round(pnl, 2)})

    elif strat == "BUY_PUT":
        bs_entry = _deriv_engine.black_scholes(current_spot, prim_strike, T, r, sigma, "PE")
        prem = bs_entry["premium"]
        margin_req = prem * lot_size
        max_loss = -margin_req
        max_profit = (prim_strike - prem) * lot_size
        be = prim_strike - prem
        breakevens.append(round(be, 2))
        legs.append({"type": "BUY_PE", "strike": prim_strike, "premium": prem})

        for s in spot_steps:
            val_at_exp = max(0.0, prim_strike - s)
            pnl = (val_at_exp - prem) * lot_size
            payoff_curve.append({"spot": s, "pnl": round(pnl, 2)})

    elif strat == "SELL_CALL":
        short_k = prim_strike if strike is not None else atm_strike + interval
        bs_entry = _deriv_engine.black_scholes(current_spot, short_k, T, r, sigma, "CE")
        prem = bs_entry["premium"]
        margin_req = current_spot * lot_size * _deriv_engine.FUTURES_MARGIN_RATES.get(clean_und, 0.15)
        max_profit = prem * lot_size
        max_loss = float("-inf")
        be = short_k + prem
        breakevens.append(round(be, 2))
        legs.append({"type": "SELL_CE", "strike": short_k, "premium": prem})

        for s in spot_steps:
            val_at_exp = max(0.0, s - short_k)
            pnl = (prem - val_at_exp) * lot_size
            payoff_curve.append({"spot": s, "pnl": round(pnl, 2)})

    elif strat == "SELL_PUT":
        short_k = prim_strike if strike is not None else atm_strike - interval
        bs_entry = _deriv_engine.black_scholes(current_spot, short_k, T, r, sigma, "PE")
        prem = bs_entry["premium"]
        margin_req = current_spot * lot_size * _deriv_engine.FUTURES_MARGIN_RATES.get(clean_und, 0.15)
        max_profit = prem * lot_size
        max_loss = -(short_k - prem) * lot_size
        be = short_k - prem
        breakevens.append(round(be, 2))
        legs.append({"type": "SELL_PE", "strike": short_k, "premium": prem})

        for s in spot_steps:
            val_at_exp = max(0.0, short_k - s)
            pnl = (prem - val_at_exp) * lot_size
            payoff_curve.append({"spot": s, "pnl": round(pnl, 2)})

    elif strat == "BULL_PUT_SPREAD":
        short_k = prim_strike if strike is not None else atm_strike - interval
        long_k = short_k - interval
        bs_s = _deriv_engine.black_scholes(current_spot, short_k, T, r, sigma, "PE")
        bs_l = _deriv_engine.black_scholes(current_spot, long_k, T, r, sigma, "PE")
        net_credit = max(1.0, round(bs_s["premium"] - bs_l["premium"], 2))
        spread_w = short_k - long_k
        max_profit = net_credit * lot_size
        max_loss = -(spread_w - net_credit) * lot_size
        margin_req = (spread_w - net_credit) * lot_size + 2500.0
        be = short_k - net_credit
        breakevens.append(round(be, 2))
        legs.append({"type": "SELL_PE", "strike": short_k, "premium": bs_s["premium"]})
        legs.append({"type": "BUY_PE", "strike": long_k, "premium": bs_l["premium"]})

        for s in spot_steps:
            val_short = max(0.0, short_k - s)
            val_long = max(0.0, long_k - s)
            pnl = (net_credit - (val_short - val_long)) * lot_size
            payoff_curve.append({"spot": s, "pnl": round(pnl, 2)})

    elif strat == "BEAR_CALL_SPREAD":
        short_k = prim_strike if strike is not None else atm_strike + interval
        long_k = short_k + interval
        bs_s = _deriv_engine.black_scholes(current_spot, short_k, T, r, sigma, "CE")
        bs_l = _deriv_engine.black_scholes(current_spot, long_k, T, r, sigma, "CE")
        net_credit = max(1.0, round(bs_s["premium"] - bs_l["premium"], 2))
        spread_w = long_k - short_k
        max_profit = net_credit * lot_size
        max_loss = -(spread_w - net_credit) * lot_size
        margin_req = (spread_w - net_credit) * lot_size + 2500.0
        be = short_k + net_credit
        breakevens.append(round(be, 2))
        legs.append({"type": "SELL_CE", "strike": short_k, "premium": bs_s["premium"]})
        legs.append({"type": "BUY_CE", "strike": long_k, "premium": bs_l["premium"]})

        for s in spot_steps:
            val_short = max(0.0, s - short_k)
            val_long = max(0.0, s - long_k)
            pnl = (net_credit - (val_short - val_long)) * lot_size
            payoff_curve.append({"spot": s, "pnl": round(pnl, 2)})

    elif strat == "LONG_FUTURES":
        margin_req = current_spot * lot_size * _deriv_engine.FUTURES_MARGIN_RATES.get(clean_und, 0.15)
        max_profit = float("inf")
        max_loss = -current_spot * lot_size
        breakevens.append(current_spot)
        legs.append({"type": "BUY_FUT", "strike": current_spot, "premium": 0.0})
        for s in spot_steps:
            pnl = (s - current_spot) * lot_size
            payoff_curve.append({"spot": s, "pnl": round(pnl, 2)})

    elif strat == "SHORT_FUTURES":
        margin_req = current_spot * lot_size * _deriv_engine.FUTURES_MARGIN_RATES.get(clean_und, 0.15)
        max_profit = current_spot * lot_size
        max_loss = float("-inf")
        breakevens.append(current_spot)
        legs.append({"type": "SELL_FUT", "strike": current_spot, "premium": 0.0})
        for s in spot_steps:
            pnl = (current_spot - s) * lot_size
            payoff_curve.append({"spot": s, "pnl": round(pnl, 2)})

    return {
        "underlying": clean_und,
        "strategy": strat,
        "current_spot": round(current_spot, 2),
        "days_to_expiry": round(dynamic_dte, 4),
        "lot_size": lot_size,
        "margin_required": round(margin_req, 2),
        "max_profit": None if math.isinf(max_profit) else round(max_profit, 2),
        "max_loss": None if math.isinf(max_loss) else round(max_loss, 2),
        "breakevens": breakevens,
        "legs": legs,
        "payoff_curve": payoff_curve
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
    clean = _sanitize_ticker(ticker)
    summary = await NewsFetcher.get_sentiment_summary(clean)
    return summary



