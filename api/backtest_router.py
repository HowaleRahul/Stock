import os
import yfinance as yf
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
import pandas as pd
from setups.engine import SetupEngine

router = APIRouter(prefix="/api/v1/backtest", tags=["Backtest"])

class BacktestResult(BaseModel):
    win_rate: float
    total_trades: int
    total_pnl_pct: float
    max_drawdown_pct: float
    trades: list

@router.get("/run", response_model=BacktestResult)
async def run_backtest(
    ticker: str = Query(..., description="Ticker to backtest"),
    timeframe: str = Query("1d", description="Timeframe (e.g. 1h, 1d)"),
    setup: str = Query(..., description="Setup name (e.g. sma_crossover)")
):
    try:
        period = "5y" if timeframe == "1d" else "60d"
        df = yf.download(ticker, period=period, interval=timeframe, progress=False)
        if df.empty:
            raise HTTPException(status_code=404, detail="No data found for ticker.")

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]
        
        df.rename(columns={'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'}, inplace=True)
        
        from setups.indicators import (
            calculate_sma_crossover, calculate_rsi_divergence, 
            calculate_macd_cross, calculate_bollinger_breakout
        )
        
        if setup == "sma_crossover":
            df = calculate_sma_crossover(df)
            signal_col = "sma_signal"
        elif setup == "rsi_divergence":
            df = calculate_rsi_divergence(df)
            signal_col = "rsi_signal"
        elif setup == "macd_cross":
            df = calculate_macd_cross(df)
            signal_col = "macd_signal"
        elif setup == "bollinger_breakout":
            df = calculate_bollinger_breakout(df)
            signal_col = "bb_signal"
        else:
            raise HTTPException(status_code=400, detail="Unknown setup")

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
                pnl = (price - entry_price) / entry_price if direction == "bullish" else (entry_price - price) / entry_price
                
                exit_signal = (direction == "bullish" and row.get(signal_col) == -1) or \
                              (direction == "bearish" and row.get(signal_col) == 1) or \
                              pnl <= -0.03 or pnl >= 0.06
                              
                if exit_signal:
                    in_trade = False
                    capital *= (1 + pnl)
                    if capital > peak_capital:
                        peak_capital = capital
                    dd = (peak_capital - capital) / peak_capital
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

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
