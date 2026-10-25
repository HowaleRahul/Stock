import os
import re
import math
import logging
import yfinance as yf
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
import pandas as pd

from api.auth import get_api_key, rate_limiter
from setups.indicators import bollinger_bands, ema, macd, rsi, sma

logger = logging.getLogger("trading.api.backtest")

router = APIRouter(
    prefix="/api/v1/backtest",
    tags=["Backtest"],
    dependencies=[Depends(get_api_key)],
)


def _validate_ticker(ticker: str) -> str:
    """Validate and sanitize ticker input."""
    if not ticker or not isinstance(ticker, str):
        raise HTTPException(status_code=400, detail="Ticker cannot be empty.")
    cleaned = ticker.upper().strip().replace("\x00", "")
    if not cleaned or len(cleaned) > 64:
        raise HTTPException(status_code=400, detail="Invalid ticker length.")
    if ".." in cleaned or "/" in cleaned or "\\" in cleaned:
        raise HTTPException(status_code=400, detail="Invalid ticker: forbidden characters detected.")
    if not re.match(r"^[A-Z0-9\._\-\^\=]+$", cleaned):
        raise HTTPException(status_code=400, detail="Invalid characters in ticker.")
    return cleaned


class BacktestResult(BaseModel):
    win_rate: float
    total_trades: int
    total_pnl_pct: float
    max_drawdown_pct: float
    trades: list


def _add_signal_column(df: pd.DataFrame, signal_name: str, values: pd.Series) -> pd.DataFrame:
    """Attach a normalized {-1, 0, 1} signal column without mutating caller data."""
    result = df.copy()
    result[signal_name] = values.fillna(0).astype(int)
    return result


def _calculate_sma_crossover(df: pd.DataFrame) -> pd.DataFrame:
    fast = sma(df["close"], 20)
    slow = sma(df["close"], 50)
    signal = pd.Series(0, index=df.index, dtype=int)
    signal[(fast > slow) & (fast.shift(1) <= slow.shift(1))] = 1
    signal[(fast < slow) & (fast.shift(1) >= slow.shift(1))] = -1
    return _add_signal_column(df, "sma_signal", signal)


def _calculate_rsi_divergence(df: pd.DataFrame) -> pd.DataFrame:
    values = rsi(df["close"], 14)
    signal = pd.Series(0, index=df.index, dtype=int)
    signal[(values < 30) & (values.shift(1) >= 30)] = 1
    signal[(values > 70) & (values.shift(1) <= 70)] = -1
    return _add_signal_column(df, "rsi_signal", signal)


def _calculate_macd_cross(df: pd.DataFrame) -> pd.DataFrame:
    macd_line, signal_line, _ = macd(df["close"])
    signal = pd.Series(0, index=df.index, dtype=int)
    signal[(macd_line > signal_line) & (macd_line.shift(1) <= signal_line.shift(1))] = 1
    signal[(macd_line < signal_line) & (macd_line.shift(1) >= signal_line.shift(1))] = -1
    return _add_signal_column(df, "macd_signal", signal)


def _calculate_bollinger_breakout(df: pd.DataFrame) -> pd.DataFrame:
    upper, _, lower = bollinger_bands(df["close"], 20, 2.0)
    signal = pd.Series(0, index=df.index, dtype=int)
    signal[(df["close"] > upper) & (df["close"].shift(1) <= upper.shift(1))] = 1
    signal[(df["close"] < lower) & (df["close"].shift(1) >= lower.shift(1))] = -1
    return _add_signal_column(df, "bb_signal", signal)


def _download_and_backtest(ticker: str, timeframe: str, setup: str) -> dict:
    """Blocking function that runs in a thread pool."""
    period = "5y" if timeframe == "1d" else "60d"

    # Normalize Indian ticker symbol for Yahoo Finance
    clean_sym = ticker.upper().strip()
    yf_ticker = clean_sym
    if clean_sym in ("NIFTY", "NIFTY 50"):
        yf_ticker = "^NSEI"
    elif clean_sym in ("BANKNIFTY", "NIFTY BANK"):
        yf_ticker = "^NSEBANK"
    elif clean_sym in ("SENSEX", "^BSESN"):
        yf_ticker = "^BSESN"
    elif not clean_sym.startswith("^") and not clean_sym.endswith((".NS", ".BO")) and clean_sym not in ("BTC-USD", "SPY"):
        yf_ticker = f"{clean_sym}.NS"

    df = yf.download(yf_ticker, period=period, interval=timeframe, progress=False)
    if df.empty:
        # Fallback to direct ticker if suffixed symbol returned empty
        df = yf.download(clean_sym, period=period, interval=timeframe, progress=False)
        if df.empty:
            raise ValueError(f"No data found for ticker {ticker}.")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]

    df.rename(columns={
        'Open': 'open', 'High': 'high', 'Low': 'low',
        'Close': 'close', 'Volume': 'volume'
    }, inplace=True)

    # Drop any bars with missing price data
    df = df.dropna(subset=['close', 'high', 'low', 'open'])

    # In live market hours, update latest bar with real-time LTP
    try:
        from data.realtime_feed import RealTimeDataFeed
        quote = RealTimeDataFeed.get_realtime_quote_sync(clean_sym)
        if quote and quote.get("ltp", 0.0) > 0 and not df.empty:
            ltp = float(quote["ltp"])
            idx_last = df.index[-1]
            if ltp > df.at[idx_last, "high"]:
                df.at[idx_last, "high"] = ltp
            if ltp < df.at[idx_last, "low"]:
                df.at[idx_last, "low"] = ltp
            df.at[idx_last, "close"] = ltp
    except Exception:
        pass

    if len(df) < 50:
        raise ValueError(f"Insufficient historical data for {ticker} (only {len(df)} bars returned, at least 50 required).")


    setup_map = {
        "sma_crossover": (_calculate_sma_crossover, "sma_signal"),
        "rsi_divergence": (_calculate_rsi_divergence, "rsi_signal"),
        "macd_cross": (_calculate_macd_cross, "macd_signal"),
        "bollinger_breakout": (_calculate_bollinger_breakout, "bb_signal"),
    }

    if setup not in setup_map:
        raise ValueError(f"Unknown setup: {setup}")

    calc_fn, signal_col = setup_map[setup]
    df = calc_fn(df)

    trades = []
    in_trade = False
    entry_price = 0.0
    entry_time = None
    direction = ""

    capital = 10000.0
    peak_capital = capital
    max_dd = 0.0

    for idx, row in df.iterrows():
        close_val = row.get('close')
        if pd.isna(close_val):
            continue
        price = float(close_val)

        if in_trade:
            # Guard division by zero or invalid entry price
            if entry_price <= 0 or not math.isfinite(entry_price):
                in_trade = False
                continue
            pnl = (price - entry_price) / entry_price if direction == "bullish" else (entry_price - price) / entry_price
            if not math.isfinite(pnl):
                pnl = 0.0

            exit_signal = (direction == "bullish" and row.get(signal_col) == -1) or \
                          (direction == "bearish" and row.get(signal_col) == 1) or \
                          pnl <= -0.03 or pnl >= 0.06

            if exit_signal:
                in_trade = False
                capital = max(0.0, capital * (1 + pnl))
                if capital > peak_capital:
                    peak_capital = capital
                dd = (peak_capital - capital) / peak_capital if peak_capital > 0 else 0
                if dd > max_dd:
                    max_dd = dd

                trades.append({
                    "entry_time": str(entry_time),
                    "exit_time": str(idx),
                    "direction": direction,
                    "entry_price": round(float(entry_price), 2),
                    "exit_price": round(float(price), 2),
                    "pnl_pct": round(float(pnl * 100), 2)
                })
        else:
            if price > 0 and math.isfinite(price):
                if row.get(signal_col) == 1:
                    in_trade = True
                    direction = "bullish"
                    entry_price = price
                    entry_time = idx
                elif row.get(signal_col) == -1:
                    in_trade = True
                    direction = "bearish"
                    entry_price = price
                    entry_time = idx

    wins = len([t for t in trades if t["pnl_pct"] > 0])
    win_rate = (wins / len(trades) * 100) if trades else 0.0
    total_pnl = ((capital - 10000.0) / 10000.0) * 100
    if not math.isfinite(total_pnl):
        total_pnl = 0.0
    if not math.isfinite(win_rate):
        win_rate = 0.0
    if not math.isfinite(max_dd):
        max_dd = 0.0

    return {
        "win_rate": round(win_rate, 2),
        "total_trades": len(trades),
        "total_pnl_pct": round(total_pnl, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "trades": trades
    }


@router.get("/run", response_model=BacktestResult)
async def run_backtest(
    ticker: str = Query(..., description="Ticker to backtest"),
    timeframe: str = Query("1d", description="Timeframe (e.g. 1h, 1d)"),
    setup: str = Query(..., description="Setup name (e.g. sma_crossover)"),
    _rate_limit: bool = Depends(rate_limiter(10))
):
    ticker_clean = _validate_ticker(ticker)

    valid_timeframes = {"1h", "1d"}
    if timeframe not in valid_timeframes:
        raise HTTPException(status_code=400, detail=f"Invalid timeframe. Must be one of: {valid_timeframes}")

    valid_setups = {"sma_crossover", "rsi_divergence", "macd_cross", "bollinger_breakout"}
    if setup not in valid_setups:
        raise HTTPException(status_code=400, detail=f"Invalid setup. Must be one of: {valid_setups}")

    try:
        result = await run_in_threadpool(_download_and_backtest, ticker_clean, timeframe, setup)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Backtest failed for {ticker_clean}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Backtest failed. Please try again.")
