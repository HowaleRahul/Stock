import os
import re
import logging
import yfinance as yf
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
import pandas as pd

from api.auth import get_api_key, rate_limiter

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
    if not re.match(r"^[A-Z0-9\.\-\^\=]+$", cleaned):
        raise HTTPException(status_code=400, detail="Invalid characters in ticker.")
    return cleaned


class BacktestResult(BaseModel):
    win_rate: float
    total_trades: int
    total_pnl_pct: float
    max_drawdown_pct: float
    trades: list


def _download_and_backtest(ticker: str, timeframe: str, setup: str) -> dict:
    """Blocking function that runs in a thread pool."""
    period = "5y" if timeframe == "1d" else "60d"
    df = yf.download(ticker, period=period, interval=timeframe, progress=False)
    if df.empty:
        raise ValueError("No data found for ticker.")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]

    df.rename(columns={
        'Open': 'open', 'High': 'high', 'Low': 'low',
        'Close': 'close', 'Volume': 'volume'
    }, inplace=True)

    from setups.indicators import (
        calculate_sma_crossover, calculate_rsi_divergence,
        calculate_macd_cross, calculate_bollinger_breakout
    )

    setup_map = {
        "sma_crossover": (calculate_sma_crossover, "sma_signal"),
        "rsi_divergence": (calculate_rsi_divergence, "rsi_signal"),
        "macd_cross": (calculate_macd_cross, "macd_signal"),
        "bollinger_breakout": (calculate_bollinger_breakout, "bb_signal"),
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
        if in_trade:
            price = row['close']
            # Guard division by zero
            if entry_price == 0:
                in_trade = False
                continue
            pnl = (price - entry_price) / entry_price if direction == "bullish" else (entry_price - price) / entry_price

            exit_signal = (direction == "bullish" and row.get(signal_col) == -1) or \
                          (direction == "bearish" and row.get(signal_col) == 1) or \
                          pnl <= -0.03 or pnl >= 0.06

            if exit_signal:
                in_trade = False
                capital *= (1 + pnl)
                if capital > peak_capital:
                    peak_capital = capital
                dd = (peak_capital - capital) / peak_capital if peak_capital > 0 else 0
                if dd > max_dd:
                    max_dd = dd

                trades.append({
                    "entry_time": str(entry_time),
                    "exit_time": str(idx),
                    "direction": direction,
                    "entry_price": float(entry_price),
                    "exit_price": float(price),
                    "pnl_pct": float(pnl * 100)
                })
        else:
            if row.get(signal_col) == 1:
                in_trade = True
                direction = "bullish"
                entry_price = row['close']
                entry_time = idx
            elif row.get(signal_col) == -1:
                in_trade = True
                direction = "bearish"
                entry_price = row['close']
                entry_time = idx

    wins = len([t for t in trades if t["pnl_pct"] > 0])
    win_rate = (wins / len(trades) * 100) if trades else 0.0
    total_pnl = ((capital - 10000.0) / 10000.0) * 100

    return {
        "win_rate": win_rate,
        "total_trades": len(trades),
        "total_pnl_pct": total_pnl,
        "max_drawdown_pct": max_dd * 100,
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
