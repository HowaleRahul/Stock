"""
LIVE Execution Engine — Phase 9
HARD SEPARATION FROM PAPER TRADING.

This engine connects to the real broker API.
It will aggressively crash and refuse to run if the environment is not set to LIVE.
"""

import time
import json
import logging
import os
import datetime
import pandas as pd
from dotenv import load_dotenv

from setups.engine import SetupEngine
from ml.ensemble import EnsembleModel
from ml.risk_engine import RiskEngine, TradePlan
from ml.options_engine import OptionsEngine
from ml.drift_detector import DriftDetector
from api.notifier import notifier
from api.broker import BrokerAPI

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("live_trader")

CONFIG_PATH = "config.json"
TIMEFRAME = "1h"

def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError("config.json missing. Cannot run live.")
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

def run_live_loop():
    logger.info("Initializing LIVE Trader...")
    
    config = load_config()
    
    # ---------------------------------------------------------
    # 1. STRICT ENVIRONMENT HARD-CHECK
    # ---------------------------------------------------------
    # We do NOT use the config.json flag. It is too easy to accidentally toggle in a UI.
    # We require an explicit environment variable set on the server/machine.
    if os.getenv("I_AM_READY_TO_LOSE_REAL_MONEY") != "True":
        logger.critical("🛑 FATAL: Attempted to run live_trader.py without explicit .env confirmation.")
        logger.critical("Set I_AM_READY_TO_LOSE_REAL_MONEY=True in your .env to unlock live trading.")
        notifier.send_system_alert("Attempted to start live_trader.py without .env confirmation. Process terminated.", "CRITICAL")
        return
        
    # ---------------------------------------------------------
    # 2. BROKER INITIALIZATION
    # ---------------------------------------------------------
    api_key = os.getenv("BROKER_API_KEY")
    api_secret = os.getenv("BROKER_API_SECRET")
    totp = os.getenv("BROKER_TOTP_SECRET")
    
    broker = BrokerAPI(api_key, api_secret, totp)
    if not broker.connect():
        logger.critical("Broker connection failed. Halting live trader.")
        notifier.send_system_alert("Live trader failed to connect to Broker API.", "CRITICAL")
        return

    # Initialize AI Components
    engine = SetupEngine()
    ai_brain = EnsembleModel(timeframe=TIMEFRAME)
    risk_engine = RiskEngine()
    opt_engine = OptionsEngine()
    detector = DriftDetector()
    
    # Track local state mapping (so we know which live orders correspond to which AI signals)
    active_live_orders = {}
    
    logger.info("🟢 LIVE TRADER ACTIVE. Real capital is now at risk.")
    notifier.send_system_alert("LIVE Trading Engine Started.", "WARNING")
    
    # Main Loop (Simplified for scaffolding)
    while True:
        try:
            # 1. Fetch live data (In reality this would be WebSockets, we simulate polling here)
            # Using yfinance just as a placeholder for live tick data
            import yfinance as yf
            ticker = "^NSEI"
            df = yf.download(ticker, period="1mo", interval=TIMEFRAME, progress=False)
            
            if df.empty or len(df) < 50:
                time.sleep(60)
                continue
                
            # Flatten multi-index if necessary
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [col[0] for col in df.columns]
                
            # Rename for consistency
            df.rename(columns={'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'}, inplace=True)
            
            current_price = float(df['close'].iloc[-1])
            
            # 2. Check for Exits on active live orders
            closed_orders = []
            for order_id, trade in active_live_orders.items():
                # In real life, we would check broker.get_positions() and broker.get_orders()
                # For this scaffolding, we simulate the exit check locally
                sl = trade.get("sl")
                tp = trade.get("tp")
                
                if current_price <= sl or current_price >= tp:
                    logger.info(f"Closing live position: {trade['ticker']}")
                    # broker.place_order(trade['ticker'], trade['quantity'], "SELL" if trade['direction']=="LONG" else "BUY")
                    closed_orders.append(order_id)
                    notifier.send_exit_alert(trade, is_live=True)
                    
            for oid in closed_orders:
                del active_live_orders[oid]

            # 3. Generate New Signals
            config = load_config() # Reload config to pick up dashboard changes
            active_setups = config.get("active_setups", [])
            
            setups = engine.scan(df, active_setups)
            ai_signal, confidence, regime = ai_brain.predict(df, setups)
            
            if ai_signal in ["bullish", "bearish"] and confidence >= 0.55:
                # 4. Risk Engine
                capital = 1000000 # Mock live capital
                trade_plan = risk_engine.generate_trade_plan(
                    ticker=ticker,
                    direction=ai_signal,
                    ai_probability=confidence,
                    df=df,
                    capital=capital,
                    regime=regime,
                    timeframe=TIMEFRAME
                )
                
                if trade_plan.is_approved:
                    # 5. Options Translation
                    iv = 0.15 # Mock
                    opt_plan = opt_engine.generate_options_plan(trade_plan, iv=iv)
                    
                    if opt_plan.is_approved:
                        # 6. LIVE EXECUTION
                        order_id = broker.place_order(
                            ticker=opt_plan.option_symbol,
                            quantity=opt_plan.lots_to_buy * opt_plan.lot_size,
                            direction=opt_plan.option_type
                        )
                        
                        live_trade_record = {
                            "order_id": order_id,
                            "ticker": opt_plan.option_symbol,
                            "direction": "LONG", # Options buy
                            "quantity": opt_plan.lots_to_buy * opt_plan.lot_size,
                            "entry_price": opt_plan.entry_premium,
                            "invested": opt_plan.total_premium_invested,
                            "sl": opt_plan.original_plan.stop_loss, # tracked against spot
                            "tp": opt_plan.original_plan.take_profit,
                            "is_options": True
                        }
                        
                        active_live_orders[order_id] = live_trade_record
                        notifier.send_entry_alert(live_trade_record, is_live=True)
                        logger.info(f"LIVE ORDER EXECUTED: {order_id}")
            
            # Sleep until next check
            time.sleep(300) # 5 minutes
            
        except Exception as e:
            logger.error(f"Live Loop Exception: {e}", exc_info=True)
            notifier.send_system_alert(f"Live Loop Exception: {e}", "CRITICAL")
            time.sleep(60)

if __name__ == "__main__":
    run_live_loop()
