"""
LIVE Execution Engine — Phase 9
HARD SEPARATION FROM PAPER TRADING.

This engine connects to the real broker API.
It will aggressively crash and refuse to run if the environment is not set to LIVE.
"""

import asyncio
import json
import logging
import os
import datetime
import pandas as pd
from dotenv import load_dotenv

from setups.engine import SetupEngine
from ml.ensemble import EnsembleModel
from ml.risk_engine import RiskEngine
from ml.options_engine import OptionsEngine
from ml.drift_detector import DriftDetector
from api.notifier import notifier
from api.broker import BrokerAPI
import yfinance as yf

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("live_trader")

CONFIG_PATH = "config.json"
TIMEFRAME = "1h"
TICKERS = ["^NSEI", "^NSEBANK"]

def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        logger.warning("config.json missing. Loading default config.")
        return {}
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

from sqlalchemy import select
from api.db import async_session_factory
from models.models import Trade

# ... inside run_live_loop_async

async def get_active_trades():
    async with async_session_factory() as session:
        stmt = select(Trade).where(Trade.is_open == True)
        res = await session.execute(stmt)
        return list(res.scalars().all())

async def close_trade(trade_id, exit_price):
    async with async_session_factory() as session:
        stmt = select(Trade).where(Trade.id == trade_id)
        res = await session.execute(stmt)
        trade = res.scalar_one_or_none()
        if trade:
            trade.is_open = False
            trade.exit_price = exit_price
            trade.exit_time = datetime.datetime.utcnow()
            
            pnl = (exit_price - trade.entry_price) / trade.entry_price
            if trade.direction == "bearish":
                pnl = -pnl
            trade.pnl_pct = pnl * 100
            
            await session.commit()

async def open_trade(trade_record):
    async with async_session_factory() as session:
        new_trade = Trade(
            order_id=trade_record["order_id"],
            ticker=trade_record["ticker"],
            direction=trade_record["direction"],
            entry_price=trade_record["entry_price"],
            quantity=trade_record["quantity"],
            invested=trade_record["invested"],
            take_profit=trade_record.get("tp"),
            stop_loss=trade_record.get("sl"),
            is_open=True,
        )
        session.add(new_trade)
        await session.commit()

async def run_live_loop_async():
    logger.info("Initializing LIVE Trader...")
    
    if os.getenv("I_AM_READY_TO_LOSE_REAL_MONEY") != "True":
        logger.critical("🛑 FATAL: Attempted to run live_trader.py without explicit .env confirmation.")
        return
        
    api_key = os.getenv("BROKER_API_KEY")
    api_secret = os.getenv("BROKER_API_SECRET")
    totp = os.getenv("BROKER_TOTP_SECRET")
    
    broker = BrokerAPI(api_key, api_secret, totp)
    if not broker.connect():
        logger.critical("Broker connection failed. Halting live trader.")
        return

    engine = SetupEngine()
    ai_brain = EnsembleModel(timeframe=TIMEFRAME)
    risk_engine = RiskEngine()
    opt_engine = OptionsEngine()
    
    logger.info("🟢 LIVE TRADER ACTIVE. Real capital is now at risk.")
    
    while True:
        try:
            active_live_orders = await get_active_trades()
            
            for ticker in TICKERS:
                df = yf.download(ticker, period="1mo", interval=TIMEFRAME, progress=False)
                
                if df.empty or len(df) < 50:
                    continue
                    
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [col[0] for col in df.columns]
                df.rename(columns={'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'}, inplace=True)
                
                current_price = float(df['close'].iloc[-1])
                
                for trade in active_live_orders:
                    if trade.ticker == ticker or trade.ticker.startswith(ticker):
                        if current_price <= trade.stop_loss or current_price >= trade.take_profit:
                            logger.info(f"Closing live position: {trade.ticker}")
                            await close_trade(trade.id, current_price)
                            notifier.send_exit_alert({"ticker": trade.ticker}, is_live=True)

                config = load_config()
                regime, setups = engine.evaluate_all(df, ticker)
                prediction_dict = ai_brain.predict(regime, setups)
                ai_signal = prediction_dict.get("signal", "neutral")
                confidence = prediction_dict.get("probability", 0.0)
                
                if ai_signal in ["bullish", "bearish"] and confidence >= 0.55:
                    trade_plan = risk_engine.generate_trade_plan(
                        ticker=ticker, direction=ai_signal, ai_probability=confidence,
                        df=df, capital=1000000, regime=regime, timeframe=TIMEFRAME
                    )
                    
                    if trade_plan.is_approved:
                        opt_plan = opt_engine.generate_options_plan(trade_plan, iv=0.15)
                        if opt_plan.is_approved:
                            order_id = broker.place_order(ticker=opt_plan.option_symbol, quantity=opt_plan.lots_to_buy * opt_plan.lot_size, direction=opt_plan.option_type)
                            live_trade_record = {
                                "order_id": order_id, "ticker": opt_plan.option_symbol, "direction": ai_signal,
                                "quantity": opt_plan.lots_to_buy * opt_plan.lot_size, "entry_price": opt_plan.entry_premium,
                                "invested": opt_plan.total_premium_invested, "sl": opt_plan.original_plan.stop_loss,
                                "tp": opt_plan.original_plan.take_profit, "is_options": True
                            }
                            await open_trade(live_trade_record)
                            notifier.send_entry_alert(live_trade_record, is_live=True)
                            logger.info(f"LIVE ORDER EXECUTED: {order_id}")
            
            await asyncio.sleep(300)
            
        except Exception as e:
            logger.error(f"Live Loop Exception: {e}", exc_info=True)
            await asyncio.sleep(60)

def run_live_loop():
    asyncio.run(run_live_loop_async())

if __name__ == "__main__":
    run_live_loop()
