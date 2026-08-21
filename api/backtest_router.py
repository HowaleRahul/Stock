import os
import re
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
    if not re.match(r"^[A-Z0-9\.\-\^\=]+$", cleaned):
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
    df = yf.download(ticker, period=period, interval=timeframe, progress=False)
    if df.empty:
        raise ValueError("No data found for ticker.")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]

    df.rename(columns={
        'Open': 'open', 'High': 'high', 'Low': 'low',
        'Close': 'close', 'Volume': 'volume'
    }, inplace=True)

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
