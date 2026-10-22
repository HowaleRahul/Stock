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
TICKERS = ["^NSEI", "^NSEBANK", "^BSESN"]

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

async def close_trade(trade_id, exit_price, broker=None):
    async with async_session_factory() as session:
        stmt = select(Trade).where(Trade.id == trade_id)
        res = await session.execute(stmt)
        trade = res.scalar_one_or_none()
        if trade:
            is_option = " " in (trade.ticker or "")
            # If a live broker is connected, submit the closing order
            if broker and getattr(broker, "is_connected", False):
                try:
                    # For options, long premium positions are always closed by selling.
                    # For equities, exit is SELL for LONG, BUY for SHORT.
                    if is_option:
                        exit_dir = "SELL"
                        exchange = "NFO"
                    else:
                        exit_dir = "SELL" if str(trade.direction).upper() in {"LONG", "BULLISH", "BUY"} else "BUY"
                        exchange = "NSE"

                    broker.place_order(
                        ticker=trade.ticker,
                        quantity=trade.quantity,
                        direction=exit_dir,
                        exchange=exchange,
                    )
                    logger.info(f"Submitted live exit order ({exit_dir}) to broker for {trade.ticker}")
                except Exception as broker_err:
                    logger.error(f"Failed to submit broker exit order for {trade.ticker}: {broker_err}")

            trade.is_open = False
            trade.exit_price = exit_price
            trade.exit_time = datetime.datetime.now(datetime.timezone.utc)
            
            pnl = (exit_price - trade.entry_price) / trade.entry_price if trade.entry_price > 0 else 0.0
            # For options, profit is always (exit - entry). Only invert for short equity trades.
            if not is_option and str(trade.direction).upper() in {"BEARISH", "SHORT", "SELL"}:
                pnl = -pnl
            trade.pnl_pct = pnl * 100
            cash_pnl = trade.invested * pnl if trade.invested else 0.0
            
            await session.commit()
            return {
                "id": trade.id,
                "ticker": trade.ticker,
                "direction": trade.direction,
                "entry_price": trade.entry_price,
                "exit_price": exit_price,
                "status": "CLOSED_TP" if pnl > 0 else "CLOSED_SL",
                "pnl_pct": pnl,
                "cash_pnl": cash_pnl,
            }
        return None

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
            config = load_config()
            min_ai_confidence = float(config.get("min_ai_confidence", 0.65))
            configured_capital = float(config.get("capital", 100000.0))
            
            for ticker in TICKERS:
                clean_sym = ticker.replace("^", "")
                df = await asyncio.to_thread(
                    yf.download, ticker, period="1mo", interval=TIMEFRAME, progress=False
                )
                
                if df is None or df.empty or len(df) < 50:
                    continue
                    
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [col[0] for col in df.columns]
                df.rename(columns={'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'}, inplace=True)
                
                current_price = float(df['close'].iloc[-1])
                
                for trade in active_live_orders:
                    is_match = (trade.ticker == ticker) or trade.ticker.startswith(ticker) or trade.ticker.startswith(clean_sym)
                    if is_match:
                        if trade.stop_loss is not None and trade.take_profit is not None:
                            direction = str(trade.direction).upper()
                            if direction in {"LONG", "BULLISH", "BUY"}:
                                should_exit = current_price <= trade.stop_loss or current_price >= trade.take_profit
                            elif direction in {"SHORT", "BEARISH", "SELL"}:
                                should_exit = current_price >= trade.stop_loss or current_price <= trade.take_profit
                            else:
                                logger.error("Unknown persisted trade direction %r; refusing automatic exit.", trade.direction)
                                should_exit = False
                            if should_exit:
                                logger.info(f"Closing live position: {trade.ticker}")
                                parts = (trade.ticker or "").split()
                                is_option = len(parts) == 3 and parts[2] in ("CE", "PE")
                                if is_option:
                                    try:
                                        strike = float(parts[1])
                                        opt_type = parts[2]
                                        iv = (df['macro_vix'].iloc[-1] / 100.0) if 'macro_vix' in df.columns else 0.15
                                        entry_t = trade.entry_time if trade.entry_time else datetime.datetime.now(datetime.timezone.utc)
                                        if entry_t.tzinfo is None:
                                            entry_t = entry_t.replace(tzinfo=datetime.timezone.utc)
                                        days_held = max(0.0, (datetime.datetime.now(datetime.timezone.utc) - entry_t).total_seconds() / 86400.0)
                                        days_to_expiry = max(0.5, 7.0 - days_held)
                                        T = days_to_expiry / 365.0
                                        bs_res = opt_engine._black_scholes(S=current_price, K=strike, T=T, r=0.06, sigma=iv, option_type=opt_type)
                                        opt_exit_price = max(0.05, bs_res["premium"])
                                    except Exception as calc_err:
                                        logger.error(f"Error calculating option exit premium: {calc_err}")
                                        opt_exit_price = trade.entry_price
                                    closed_rec = await close_trade(trade.id, opt_exit_price, broker=broker)
                                else:
                                    closed_rec = await close_trade(trade.id, current_price, broker=broker)
                                if closed_rec:
                                    notifier.send_exit_alert(closed_rec, is_live=True)

                regime, setups = engine.evaluate_with_regime(df, ticker)
                prediction_dict = ai_brain.predict(
                    regime,
                    setups,
                    asset_class="IN_INDEX_FO",
                    df=df,
                )
                ai_signal = prediction_dict.get("signal", "neutral")
                confidence = prediction_dict.get("probability", 0.0)
                
                if ai_signal in ["bullish", "bearish"] and confidence >= min_ai_confidence:
                    actual_capital = broker.get_balance() if hasattr(broker, 'get_balance') else configured_capital
                    trade_plan = risk_engine.generate_trade_plan(
                        ticker=ticker, direction=ai_signal, ai_probability=confidence,
                        df=df, capital=actual_capital, regime=regime.get('regime', 'unknown'), timeframe=TIMEFRAME
                    )
                    
                    if trade_plan.is_approved:
                        opt_plan = opt_engine.generate_options_plan(trade_plan, iv=0.15)
                        if opt_plan.is_approved:
                            order_id = broker.place_order(
                                ticker=opt_plan.option_symbol,
                                quantity=opt_plan.lots_to_buy * opt_plan.lot_size,
                                direction="BUY",
                                exchange="NFO",
                            )
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
