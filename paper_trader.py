"""
Paper Trading Engine — Phase 6 Upgrade.

Simulates live trading with full Risk Engine integration:
- Position sizing via Kelly Criterion (capped at 2% risk per trade)
- ATR + S/R based Entry / Target / Stop Loss
- Risk:Reward gating (rejects trades under 1.5:1)
- Trailing stop management
- Time-based exit enforcement
- Portfolio correlation checks
- Probability of Ruin tracking
"""

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
from ml.risk_engine import RiskEngine
from ml.trade_logger import TradeLogger
from ml.reinforcement_learner import ReinforcementLearner
from ml.drift_detector import DriftDetector
from ml.options_engine import OptionsEngine
from api.notifier import notifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("paper_trader")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TICKERS = ["^NSEI", "^NSEBANK"]
TIMEFRAME = "1h"
PERIOD = "60d"  # Enough context for EMAs, S/R, and Macro features

TRADES_FILE = "paper_trades.json"
ACCOUNT_FILE = "paper_account.json"
REPORT_FILE = "paper_trades_report.csv"

def load_config():
    if os.path.exists("config.json"):
        try:
            with open("config.json", 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Could not load config: {e}")
    return {
        "version": "v1.0.0",
        "stt_slippage_pct": 0.0005,
        "min_ai_confidence": 0.65,
        "max_portfolio_drawdown_pct": 0.10,
        "risk_per_trade_pct": 0.02,
        "min_risk_reward_ratio": 1.5,
        "retrain_interval_days": 7,
        "drift_check_interval_hours": 24
    }

CONFIG = load_config()

STT_SLIPPAGE_PCT = CONFIG.get("stt_slippage_pct", 0.0005)
STARTING_CAPITAL = 1000000.0
MIN_AI_CONFIDENCE = CONFIG.get("min_ai_confidence", 0.65)

# ---------------------------------------------------------------------------
# Account & Trade Persistence
# ---------------------------------------------------------------------------

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
        df.to_csv(REPORT_FILE, index=False)
        logger.info("Exported CSV report.")

# ---------------------------------------------------------------------------
# Data Fetching
# ---------------------------------------------------------------------------

def fetch_and_enrich(ticker: str) -> pd.DataFrame:
    """Download OHLCV data and enrich with macro, options, and psychology features."""
    df = yf.download(ticker, period=PERIOD, interval=TIMEFRAME, progress=False)
    if df.empty or len(df) < 50:
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]

    if 'adj close' in df.columns:
        df = df.rename(columns={'adj close': 'adj_close'})

    df = enrich_with_macro_and_options(df, ticker, period=PERIOD, interval=TIMEFRAME)
    df = enrich_with_psychology_features(df)

    # Calculate ATR
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    df['atr'] = true_range.rolling(14).mean().fillna(true_range.mean())

    return df

# ---------------------------------------------------------------------------
# Main Trading Loop
# ---------------------------------------------------------------------------

def run_loop():
    engine = SetupEngine()
    ai_brain = EnsembleModel(timeframe=TIMEFRAME)
    learner = ReinforcementLearner()
    detector = DriftDetector()
    opt_engine = OptionsEngine()
    
    last_drift_check = 0.0
    last_retrain = 0.0

    logger.info("=" * 60)
    logger.info("STARTING PAPER TRADING ENGINE (Phase 6 — Risk Engine)")
    logger.info("=" * 60)

    while True:
        logger.info(f"--- Waking up for {TIMEFRAME} scan ---")
        
        now = time.time()
        
        # Periodic Concept Drift Check
        if now - last_drift_check > CONFIG.get("drift_check_interval_hours", 24) * 3600:
            logger.info("Running scheduled Concept Drift check...")
            detector.check_for_drift()
            last_drift_check = now
            
        # Periodic RL Retraining
        if now - last_retrain > CONFIG.get("retrain_interval_days", 7) * 86400:
            logger.info("Running scheduled batch RL retraining...")
            learner.batch_learn_from_journal()
            last_retrain = now
            
        all_trades = load_open_trades()
        account = load_account()

        if account['status'] == 'SUSPENDED':
            logger.warning("ACCOUNT SUSPENDED DUE TO MAX DRAWDOWN. Stopping trader.")
            break

        # Initialize Risk Engine with historical trade data
        risk_engine = RiskEngine(historical_trades=all_trades)

        # =================================================================
        # PHASE 1: Update Open Trades (TP/SL/Trailing/Time Exit)
        # =================================================================
        updated_trades = []
        for trade in all_trades:
            if trade['status'] != 'OPEN':
                updated_trades.append(trade)
                continue

            ticker = trade.get('underlying_ticker', trade['ticker'])
            df = fetch_and_enrich(ticker)
            if df is None:
                updated_trades.append(trade)
                continue

            current_price = float(df['close'].iloc[-1])
            low = float(df['low'].iloc[-1])
            high = float(df['high'].iloc[-1])

            # --- Trailing Stop Update ---
            trade = RiskEngine.update_trailing_stop(trade, high, low)
            active_sl = trade.get("trailing_stop", trade["sl"])

            # --- Time-Based Exit Check ---
            bars_held = trade.get("bars_held", 0) + 1
            trade["bars_held"] = bars_held
            time_exit = RiskEngine.check_time_exit(trade, bars_held)

            # --- Check Exit Conditions ---
            exit_reason = None

            if time_exit:
                exit_reason = "TIME_EXIT"
                trade['exit_price'] = current_price
            elif trade['direction'] == 'LONG':
                if low <= active_sl:
                    exit_reason = "TRAILING_SL" if active_sl != trade['sl'] else "CLOSED_LOSS"
                    trade['exit_price'] = active_sl
                elif high >= trade['tp']:
                    exit_reason = "CLOSED_WIN"
                    trade['exit_price'] = trade['tp']
            elif trade['direction'] == 'SHORT':
                if high >= active_sl:
                    exit_reason = "TRAILING_SL" if active_sl != trade['sl'] else "CLOSED_LOSS"
                    trade['exit_price'] = active_sl
                elif low <= trade['tp']:
                    exit_reason = "CLOSED_WIN"
                    trade['exit_price'] = trade['tp']

            if exit_reason:
                trade['status'] = exit_reason

                # Calculate PnL
                if trade.get("is_options", False):
                    # Options PnL: calculate exit premium via BS using exit spot price
                    exit_spot = trade['exit_price']
                    iv = (df['macro_vix'].iloc[-1] / 100.0) if 'macro_vix' in df.columns else 0.15
                    # Approximate remaining time
                    days_held = bars_held if TIMEFRAME == "1d" else bars_held / 6.0
                    days_to_expiry = max(0.5, 7.0 - days_held)
                    T = days_to_expiry / 365.0
                    
                    bs_exit = opt_engine._black_scholes(
                        S=exit_spot,
                        K=trade["opt_strike"],
                        T=T,
                        r=0.06,
                        sigma=iv,
                        option_type=trade["opt_type"]
                    )
                    exit_premium = bs_exit["premium"]
                    trade["opt_exit_premium"] = exit_premium
                    
                    gross_pnl_pct = (exit_premium - trade["opt_entry_premium"]) / trade["opt_entry_premium"] if trade.get("opt_entry_premium", 0) > 0 else 0.0
                    cash_pnl = trade['invested'] * (gross_pnl_pct - STT_SLIPPAGE_PCT)
                    net_pnl_pct = gross_pnl_pct - STT_SLIPPAGE_PCT
                else:
                    # Standard Equity PnL
                    entry_p = trade.get('entry_price', 0)
                    if entry_p > 0:
                        if trade['direction'] == 'LONG':
                            gross_pnl_pct = (trade['exit_price'] - entry_p) / entry_p
                        else:
                            gross_pnl_pct = (entry_p - trade['exit_price']) / entry_p
                    else:
                        gross_pnl_pct = 0.0

                    net_pnl_pct = gross_pnl_pct - STT_SLIPPAGE_PCT
                    cash_pnl = trade['invested'] * net_pnl_pct

                trade['pnl_pct'] = net_pnl_pct
                trade['cash_pnl'] = cash_pnl
                trade['closed_at'] = str(df.index[-1])

                account['capital'] += cash_pnl
                if account['capital'] > account['peak_capital']:
                    account['peak_capital'] = account['capital']

                TradeLogger.log_exit(
                    trade_id=trade['id'],
                    ticker=ticker,
                    direction=trade['direction'],
                    exit_price=trade.get("opt_exit_premium", trade['exit_price']),
                    exit_reason=exit_reason,
                    pnl_pct=net_pnl_pct,
                    cash_pnl=cash_pnl,
                    bars_held=bars_held,
                    regime_at_exit=trade.get("regime", "unknown"),
                    capital_after_exit=account['capital'],
                    setup_signals_at_entry=trade.get("setup_signals", [])
                )
                
                notifier.send_exit_alert(trade, is_live=False)
                # Update RL loop
                if trade.get("setup_signals"):
                    learner.update_from_trade(
                        setup_signals=trade["setup_signals"],
                        regime=trade.get("regime", "unknown"),
                        pnl_pct=net_pnl_pct,
                        is_win=net_pnl_pct > 0
                    )

                logger.info(
                    f"[CLOSED] {ticker} | Reason: {exit_reason} | "
                    f"PnL: {net_pnl_pct*100:+.2f}% | Cash: ₹{cash_pnl:+,.2f} | "
                    f"Bars Held: {bars_held}"
                )

            updated_trades.append(trade)

        save_trades(updated_trades)

        # --- Drawdown Check (Kill-Switch) ---
        if account['capital'] <= account['peak_capital'] * 0.90:
            account['status'] = 'SUSPENDED'
            TradeLogger.log_kill_switch(
                reason=f"{CONFIG.get('max_portfolio_drawdown_pct', 0.10) * 100}% PORTFOLIO DRAWDOWN REACHED",
                capital=account['capital'],
                peak_capital=account['peak_capital'],
                weekly_pnl=0.0,  # Not strictly tracked here, using total drawdown
                config_version=CONFIG.get("version", "v1.0")
            )
            
            notifier.send_entry_alert(new_trade, is_live=False)
            logger.error("🚨 EMERGENCY STOP: 10% PORTFOLIO DRAWDOWN REACHED!")

        save_account(account)

        if account['status'] == 'SUSPENDED':
            break

        # =================================================================
        # PHASE 2: Scan for New Entries (with full Risk Engine)
        # =================================================================
        open_tickers = [t['ticker'] for t in updated_trades if t['status'] == 'OPEN']

        for ticker in TICKERS:
            if ticker in open_tickers:
                continue  # Already in a trade for this instrument

            df = fetch_and_enrich(ticker)
            if df is None:
                continue

            regime, setups = engine.evaluate_all(df, ticker)
            regime_str = regime.get('regime', 'unknown')
            
            # Fetch RL weights and pass to brain
            setup_weights = learner.get_setup_weights(regime_str)
            prediction = ai_brain.predict(regime, setups, setup_weights)

            signal = prediction.get("signal", "neutral")
            prob = prediction.get("probability", 0.0)

            # Only consider trades where AI is confident enough
            if prob < MIN_AI_CONFIDENCE or signal not in ("bullish", "bearish"):
                continue

            # --- Generate Full Trade Plan via Risk Engine ---
            trade_plan = risk_engine.generate_trade_plan(
                ticker=ticker,
                direction=signal,
                ai_probability=prob,
                df=df,
                capital=account['capital'],
                regime=regime.get('regime', 'unknown'),
                timeframe=TIMEFRAME,
                open_positions=updated_trades,
            )

            # Log the full trade plan
            logger.info(f"\n{trade_plan.reasoning}")

            # --- Execute or Reject ---
            is_options_trade = ticker in opt_engine.LOT_SIZES
            opt_plan = None
            
            if is_options_trade and trade_plan.is_approved:
                iv = (df['macro_vix'].iloc[-1] / 100.0) if 'macro_vix' in df.columns else None
                opt_plan = opt_engine.generate_options_plan(trade_plan, iv=iv)
                
                if not opt_plan.is_approved:
                    TradeLogger.log_rejection(
                        ticker=opt_plan.option_symbol,
                        direction=opt_plan.option_type,
                        reasons=opt_plan.rejection_reasons,
                        ai_probability=trade_plan.ai_probability,
                        regime=trade_plan.regime,
                        config_version=CONFIG.get("version", "v1.0")
                    )
                    logger.warning(
                        f"[REJECTED OPTION] {opt_plan.option_symbol} — "
                        f"{'; '.join(opt_plan.rejection_reasons)}"
                    )
                    continue
                logger.info(f"\n{opt_plan.reasoning}")
            else:
                if not trade_plan.is_approved:
                    TradeLogger.log_rejection(
                        ticker=ticker,
                        direction=trade_plan.direction,
                        reasons=trade_plan.rejection_reasons,
                        ai_probability=trade_plan.ai_probability,
                        regime=trade_plan.regime,
                        config_version=CONFIG.get("version", "v1.0")
                    )
                    logger.warning(
                        f"[REJECTED] {ticker} {trade_plan.direction} — "
                        f"{'; '.join(trade_plan.rejection_reasons)}"
                    )
                    continue
                logger.info(f"\n{trade_plan.reasoning}")

            # Convert setup signals to serializable dicts
            setup_signals_list = [{"name": s.name, "signal": s.signal, "confidence": float(s.confidence)} for s in setups]

            new_trade = {
                "id": str(datetime.datetime.now().timestamp()),
                "ticker": ticker if not is_options_trade else opt_plan.option_symbol,
                "underlying_ticker": ticker,
                "direction": trade_plan.direction,
                "quantity": trade_plan.position_size_qty if not is_options_trade else opt_plan.lots_to_buy * opt_plan.lot_size,
                "invested": trade_plan.position_value if not is_options_trade else opt_plan.total_premium_invested,
                "entry_price": trade_plan.entry_price, # Spot entry price for tracking Exits
                "tp": trade_plan.take_profit, # Spot TP
                "sl": trade_plan.stop_loss, # Spot SL
                "trailing_stop": trade_plan.stop_loss,
                "atr_at_entry": trade_plan.atr_at_entry,
                "probability": trade_plan.ai_probability,
                "risk_pct": trade_plan.risk_per_trade_pct,
                "risk_reward": trade_plan.risk_reward_ratio if not is_options_trade else opt_plan.risk_reward_ratio,
                "kelly_fraction": trade_plan.kelly_fraction,
                "probability_of_ruin": trade_plan.probability_of_ruin,
                "sl_method": trade_plan.sl_method,
                "tp_method": trade_plan.tp_method,
                "regime": trade_plan.regime,
                "max_hold_bars": trade_plan.max_hold_bars,
                "bars_held": 0,
                "status": "OPEN",
                "opened_at": str(df.index[-1]),
                "setup_signals": setup_signals_list,
                "setup_weights": setup_weights,
            }
            
            if is_options_trade:
                new_trade.update({
                    "is_options": True,
                    "opt_type": opt_plan.option_type,
                    "opt_strike": opt_plan.strike_price,
                    "opt_entry_premium": opt_plan.entry_premium,
                    "opt_delta": opt_plan.delta,
                    "opt_theta": opt_plan.theta
                })
            
            TradeLogger.log_entry(
                trade_id=new_trade["id"],
                ticker=new_trade["ticker"],
                direction=trade_plan.direction if not is_options_trade else "LONG", # we always BUY options
                entry_price=trade_plan.entry_price if not is_options_trade else opt_plan.entry_premium,
                stop_loss=trade_plan.stop_loss if not is_options_trade else opt_plan.stop_loss_premium,
                take_profit=trade_plan.take_profit if not is_options_trade else opt_plan.target_premium,
                quantity=new_trade["quantity"],
                invested=new_trade["invested"],
                risk_pct=trade_plan.risk_per_trade_pct,
                risk_reward=trade_plan.risk_reward_ratio,
                ai_probability=trade_plan.ai_probability,
                kelly_fraction=trade_plan.kelly_fraction,
                probability_of_ruin=trade_plan.probability_of_ruin,
                regime=trade_plan.regime,
                regime_adx=regime.get("adx", 0.0),
                sl_method=trade_plan.sl_method,
                tp_method=trade_plan.tp_method,
                timeframe=TIMEFRAME,
                atr_at_entry=trade_plan.atr_at_entry,
                setup_signals=setup_signals_list,
                setup_weights=setup_weights,
                config_version=CONFIG.get("version", "v1.0"),
                capital_at_entry=account['capital']
            )

            logger.info(
                f"[NEW ENTRY {trade_plan.direction}] {ticker} | "
                f"Entry: ₹{trade_plan.entry_price:,.2f} | "
                f"TP: ₹{trade_plan.take_profit:,.2f} | "
                f"SL: ₹{trade_plan.stop_loss:,.2f} | "
                f"R:R: {trade_plan.risk_reward_ratio:.2f}:1 | "
                f"Risk: {trade_plan.risk_per_trade_pct*100:.2f}% | "
                f"Qty: {trade_plan.position_size_qty} | "
                f"P(Ruin): {trade_plan.probability_of_ruin*100:.4f}%"
            )
            updated_trades.append(new_trade)
            save_trades(updated_trades)

        # --- Summary ---
        open_count = sum(1 for t in updated_trades if t.get('status') == 'OPEN')
        closed_wins = sum(1 for t in updated_trades if t.get('status') == 'CLOSED_WIN')
        closed_losses = sum(1 for t in updated_trades if t.get('status') in ('CLOSED_LOSS', 'TRAILING_SL'))
        total_closed = closed_wins + closed_losses
        win_rate = (closed_wins / total_closed * 100) if total_closed > 0 else 0.0

        logger.info(
            f"Scan complete. Capital: ₹{account['capital']:,.2f} | "
            f"Peak: ₹{account['peak_capital']:,.2f} | "
            f"Open: {open_count} | Won: {closed_wins} | Lost: {closed_losses} | "
            f"Win Rate: {win_rate:.1f}%"
        )

        # Wait an hour before next scan
        time.sleep(3600)


if __name__ == "__main__":
    run_loop()
