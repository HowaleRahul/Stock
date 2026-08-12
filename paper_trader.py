import time
import datetime
import json
import os
import yfinance as yf
import pandas as pd
import numpy as np
import logging

from ml.features import (
    enrich_with_macro_and_options,
    enrich_with_psychology_features
)
from setups.engine import SetupEngine
from ml.ensemble import EnsembleModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("paper_trader")

TICKERS = ["^NSEI", "^NSEBANK"]
TIMEFRAME = "1h"
PERIOD = "60d" # Enough context for EMAs and Macros

TRADES_FILE = "paper_trades.json"
ACCOUNT_FILE = "paper_account.json"

STT_SLIPPAGE_PCT = 0.0005 # 0.05% combined friction
STARTING_CAPITAL = 1000000.0
MAX_RISK_PCT = 0.05

def load_account():
    if os.path.exists(ACCOUNT_FILE):
        with open(ACCOUNT_FILE, 'r') as f:
            return json.load(f)
    return {"capital": STARTING_CAPITAL, "peak_capital": STARTING_CAPITAL, "status": "ACTIVE"}

def save_account(account):
    with open(ACCOUNT_FILE, 'w') as f:
        json.dump(account, f, indent=4)

def load_open_trades():
    if os.path.exists(TRADES_FILE):
        with open(TRADES_FILE, 'r') as f:
            return json.load(f)
    return []

def save_trades(trades):
    with open(TRADES_FILE, 'w') as f:
        json.dump(trades, f, indent=4)
        
    if trades:
        df = pd.DataFrame(trades)
        df.to_csv("paper_trades_report.csv", index=False)
        logger.info("Exported CSV report.")

def fetch_and_enrich(ticker: str) -> pd.DataFrame:
    df = yf.download(ticker, period=PERIOD, interval=TIMEFRAME, progress=False)
    if df.empty or len(df) < 50:
        return None
    
    # Flatten multi-index
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    
    if 'adj close' in df.columns:
        df = df.rename(columns={'adj close': 'adj_close'})
        
    df = enrich_with_macro_and_options(df, ticker, period=PERIOD, interval=TIMEFRAME)
    df = enrich_with_psychology_features(df)
    
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    df['atr'] = true_range.rolling(14).mean().fillna(true_range.mean())
    
    return df

def run_loop():
    engine = SetupEngine()
    ai_brain = EnsembleModel(timeframe=TIMEFRAME)
    
    logger.info("Starting Live Paper Trading Engine...")
    
    while True:
        logger.info(f"--- Waking up for {TIMEFRAME} scan ---")
        open_trades = load_open_trades()
        account = load_account()
        
        if account['status'] == 'SUSPENDED':
            logger.warning("ACCOUNT SUSPENDED DUE TO MAX DRAWDOWN. Stopping trader.")
            break
            
        # 1. Update Open Trades (Check for TP/SL hits)
        active_trades = []
        for trade in open_trades:
            if trade['status'] != 'OPEN':
                active_trades.append(trade)
                continue
                
            ticker = trade['ticker']
            df = fetch_and_enrich(ticker)
            if df is None:
                active_trades.append(trade)
                continue
                
            current_price = float(df['close'].iloc[-1])
            low = float(df['low'].iloc[-1])
            high = float(df['high'].iloc[-1])
            
            # Check conditions
            if trade['direction'] == 'LONG':
                if low <= trade['sl']:
                    trade['status'] = 'CLOSED_LOSS'
                    trade['exit_price'] = trade['sl']
                elif high >= trade['tp']:
                    trade['status'] = 'CLOSED_WIN'
                    trade['exit_price'] = trade['tp']
            elif trade['direction'] == 'SHORT':
                if high >= trade['sl']:
                    trade['status'] = 'CLOSED_LOSS'
                    trade['exit_price'] = trade['sl']
                elif low <= trade['tp']:
                    trade['status'] = 'CLOSED_WIN'
                    trade['exit_price'] = trade['tp']
            
            if trade['status'] != 'OPEN':
                # Calculate Net PnL
                if trade['direction'] == 'LONG':
                    gross_pnl_pct = (trade['exit_price'] - trade['entry_price']) / trade['entry_price']
                else:
                    gross_pnl_pct = (trade['entry_price'] - trade['exit_price']) / trade['entry_price']
                    
                net_pnl_pct = gross_pnl_pct - STT_SLIPPAGE_PCT
                cash_pnl = trade['invested'] * net_pnl_pct
                
                trade['pnl_pct'] = net_pnl_pct
                trade['cash_pnl'] = cash_pnl
                trade['closed_at'] = str(df.index[-1])
                
                account['capital'] += cash_pnl
                if account['capital'] > account['peak_capital']:
                    account['peak_capital'] = account['capital']
                    
                logger.info(f"[CLOSED] {ticker} | PnL: {net_pnl_pct*100:.2f}% | Cash: {cash_pnl:.2f} | Reason: {trade['status']}")
            
            active_trades.append(trade)
            
        save_trades(active_trades)
        
        # Check Drawdown
        if account['capital'] <= account['peak_capital'] * 0.90:
            account['status'] = 'SUSPENDED'
            logger.error("EMERGENCY STOP: 10% DRAWDOWN REACHED!")
            
        save_account(account)
        
        if account['status'] == 'SUSPENDED':
            break
            
        # 2. Scan for New Entries
        open_tickers = [t['ticker'] for t in active_trades if t['status'] == 'OPEN']
        
        for ticker in TICKERS:
            if ticker in open_tickers:
                continue # Already in a trade
                
            df = fetch_and_enrich(ticker)
            if df is None: continue
            
            regime, setups = engine.evaluate_all(df, ticker)
            
            # Use AlphaZero Brain
            prediction = ai_brain.predict(regime, setups)
            
            signal = prediction.get("prediction", "neutral")
            prob = prediction.get("probability", 0.0)
            
            # If AI is highly confident (e.g. probability > 65%), we enter.
            if prob > 0.65 and signal in ["bullish", "bearish"]:
                entry_price = float(df['close'].iloc[-1])
                current_atr = float(df['atr'].iloc[-1])
                
                # Kelly Criterion sizing approximation
                risk_pct = min(MAX_RISK_PCT, ((prob - 0.50) / 0.50) * MAX_RISK_PCT)
                capital_at_risk = account['capital'] * risk_pct
                
                stop_loss_distance = 1.0 * current_atr
                if stop_loss_distance <= 0:
                    continue
                    
                # Quantity calculated such that if SL is hit, we lose exactly `capital_at_risk`
                quantity = int(capital_at_risk / stop_loss_distance)
                if quantity == 0:
                    continue
                    
                invested_capital = quantity * entry_price
                if invested_capital > account['capital']: # Can't invest more than we have (assuming no margin)
                    quantity = int(account['capital'] / entry_price)
                    invested_capital = quantity * entry_price
                
                if signal == "bullish":
                    direction = "LONG"
                    entry_price = entry_price * (1 + STT_SLIPPAGE_PCT)
                    tp_price = entry_price + (2.0 * current_atr)
                    sl_price = entry_price - (1.0 * current_atr)
                else:
                    direction = "SHORT"
                    entry_price = entry_price * (1 - STT_SLIPPAGE_PCT)
                    tp_price = entry_price - (2.0 * current_atr)
                    sl_price = entry_price + (1.0 * current_atr)
                
                new_trade = {
                    "id": str(datetime.datetime.now().timestamp()),
                    "ticker": ticker,
                    "direction": direction,
                    "quantity": quantity,
                    "invested": invested_capital,
                    "entry_price": entry_price,
                    "tp": tp_price,
                    "sl": sl_price,
                    "atr_at_entry": current_atr,
                    "probability": prob,
                    "risk_pct": risk_pct,
                    "regime": regime['regime'],
                    "status": "OPEN",
                    "opened_at": str(df.index[-1])
                }
                
                logger.info(f"[NEW ENTRY {direction}] {ticker} | Entry: {entry_price:.2f} | Risk: {risk_pct*100:.2f}% | Qty: {quantity}")
                active_trades.append(new_trade)
                save_trades(active_trades)
                
        # Wait an hour before next scan
        logger.info(f"Scan complete. Current Capital: {account['capital']:.2f} | Peak: {account['peak_capital']:.2f}")
        time.sleep(3600)

if __name__ == "__main__":
    run_loop()
