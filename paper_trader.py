"""
F&O Paper Trading Engine — Futures & Options Only.

ALL trades are executed as F&O contracts (Futures or Options) on NSE indices.
No equity/cash segment trading.

Features:
- Index signal analysis → DerivativeEngine → F&O trade plan
- Position sizing via Kelly Criterion (capped at 2% risk per trade)
- ATR + S/R based Entry / Target / Stop Loss on underlying index
- Smart instrument selection: Futures vs Options based on capital & regime
- Black-Scholes option MTM re-pricing with Greeks
- Trailing stop management on underlying spot
- Time-based exit enforcement (weekly expiry awareness)
- Portfolio correlation checks (NIFTY-BANKNIFTY)
- F&O Contextual Bandit RL for strike/instrument optimization
"""

import time
import datetime
import asyncio
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
from ml.risk_engine import RiskEngine, IndianFOFrictionModel, is_intraday_square_off_time
from ml.trade_logger import TradeLogger
from ml.reinforcement_learner import ReinforcementLearner
from ml.drift_detector import DriftDetector
from ml.options_engine import DerivativeEngine, get_days_to_expiry
from ml.circuit_breaker import DrawdownCircuitBreaker
from ml.agent_reflection import AgentReflector
from ml.multi_agent_consensus import MultiAgentConsensusEngine
from ml.assets import get_fo_name
from api.notifier import notifier
from data.market_hours import get_market_status, is_market_open
from papertrade.persistence import (
    ensure_schema,
    load_account as load_account_db,
    load_open_trades as load_open_trades_db,
    persist_portfolio,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("paper_trader")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TICKERS = ["^NSEI", "^NSEBANK", "^BSESN"]  # F&O underlying indices only (NIFTY, BANKNIFTY, SENSEX)
TIMEFRAME = "1h"
PERIOD = "60d"  # Enough context for EMAs, S/R, and Macro features

TRADES_FILE = "paper_trades.json"
ACCOUNT_FILE = "paper_account.json"
REPORT_FILE = "paper_trades_report.csv"


def get_scanning_tickers():
    """Returns F&O underlying index tickers only from config."""
    cfg = load_config()
    return list(cfg.get("watchlist", TICKERS))

def load_config():
    if os.path.exists("config.json"):
        try:
            with open("config.json", 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Could not load config: {e}")
    return {
        "version": "v2.0.0-fo",
        "stt_slippage_pct": 0.0005,
        "min_ai_confidence": 0.65,
        "max_portfolio_drawdown_pct": 0.10,
        "risk_per_trade_pct": 0.02,
        "min_risk_reward_ratio": 1.5,
        "retrain_interval_days": 7,
        "drift_check_interval_hours": 24,
        "fo_mode": True,
        "derivative_type": "AUTO",
        "strike_preference": "AUTO"
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
    tmp_path = f"{ACCOUNT_FILE}.tmp"
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(account, f, indent=4)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, ACCOUNT_FILE)
    except Exception as e:
        logger.error(f"Failed to save account file atomically: {e}")
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

def load_open_trades():
    if os.path.exists(TRADES_FILE):
        with open(TRADES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_trades(trades):
    tmp_path = f"{TRADES_FILE}.tmp"
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(trades, f, indent=4)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, TRADES_FILE)
        if trades:
            df = pd.DataFrame(trades)
            tmp_report = f"{REPORT_FILE}.tmp"
            df.to_csv(tmp_report, index=False)
            os.replace(tmp_report, REPORT_FILE)
            logger.info("Exported CSV report.")
    except Exception as e:
        logger.error(f"Failed to save trades file atomically: {e}")
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

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
    true_range = ranges.max(axis=1)
    df['atr'] = true_range.rolling(14, min_periods=1).mean()

    return df

# ---------------------------------------------------------------------------
# Main Trading Loop
# ---------------------------------------------------------------------------

async def run_loop():
    engine = SetupEngine()
    ai_brain = EnsembleModel(timeframe=TIMEFRAME)
    learner = ReinforcementLearner()
    detector = DriftDetector()
    opt_engine = DerivativeEngine()
    circuit_breaker = DrawdownCircuitBreaker()
    agent_reflector = AgentReflector()

    await ensure_schema()
    
    last_drift_check = 0.0
    last_retrain = 0.0

    logger.info("=" * 60)
    logger.info("STARTING PAPER TRADING ENGINE (Phase 6 — Risk Engine)")
    logger.info("=" * 60)

    while True:
        m_status = get_market_status("NSE")
        logger.info(f"--- Waking up for {TIMEFRAME} scan | NSE Session: {m_status['session']} ({m_status['message']}) ---")
        
        now = time.time()
        journal_events = []
        
        # Periodic Concept Drift Check
        if now - last_drift_check > CONFIG.get("drift_check_interval_hours", 24) * 3600:
            logger.info("Running scheduled Concept Drift check...")
            detector.check_for_drift()
            last_drift_check = now
            
        # Periodic RL Retraining + Self-Review
        if now - last_retrain > CONFIG.get("retrain_interval_days", 7) * 86400:
            logger.info("Running scheduled batch RL self-review...")
            review_report = learner.full_self_review()
            journal_events.append({
                "event": "RL_DECISIONS",
                "timestamp": datetime.datetime.now().isoformat(),
                "payload": review_report,
            })
            actions = review_report.get("actions_taken", [])
            if actions:
                logger.info(f"🧠 Self-Review applied {len(actions)} weight adjustments.")
            last_retrain = now
            
        all_trades = await load_open_trades_db()
        account = await load_account_db(STARTING_CAPITAL)

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
            df = await asyncio.to_thread(fetch_and_enrich, ticker)
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
            # 1. Intraday MIS Square-Off Rule (15:15 IST)
            candle_time = None
            if hasattr(df, "index") and len(df) > 0 and isinstance(df.index, pd.DatetimeIndex):
                try:
                    candle_time = df.index[-1].to_pydatetime() if hasattr(df.index[-1], "to_pydatetime") else df.index[-1]
                except Exception:
                    candle_time = None

            exit_reason = None
            if (candle_time is not None and is_intraday_square_off_time(candle_time)) or (is_market_open() and is_intraday_square_off_time()):
                exit_reason = "INTRADAY_SQUARE_OFF"
                trade['exit_price'] = current_price
            elif time_exit:
                exit_reason = "TIME_EXIT"
                trade['exit_price'] = current_price
            elif trade['direction'] == 'LONG':
                if low <= active_sl:
                    exit_reason = "TRAILING_SL" if active_sl != trade['sl'] else "CLOSED_LOSS"
                    bar_open = float(df['open'].iloc[-1])
                    trade['exit_price'] = min(active_sl, bar_open)
                elif high >= trade['tp']:
                    exit_reason = "CLOSED_WIN"
                    bar_open = float(df['open'].iloc[-1])
                    trade['exit_price'] = max(trade['tp'], bar_open) if bar_open > trade['tp'] else trade['tp']
            elif trade['direction'] == 'SHORT':
                if high >= active_sl:
                    exit_reason = "TRAILING_SL" if active_sl != trade['sl'] else "CLOSED_LOSS"
                    bar_open = float(df['open'].iloc[-1])
                    trade['exit_price'] = max(active_sl, bar_open)
                elif low <= trade['tp']:
                    exit_reason = "CLOSED_WIN"
                    bar_open = float(df['open'].iloc[-1])
                    trade['exit_price'] = min(trade['tp'], bar_open) if bar_open < trade['tp'] else trade['tp']

            if exit_reason:
                trade['status'] = exit_reason

                # Calculate PnL with Real-World Indian F&O Friction Model
                if trade.get("is_options", False):
                    # Options PnL: calculate exit premium via BS using exit spot price
                    exit_spot = trade['exit_price']
                    iv = (df['macro_vix'].iloc[-1] / 100.0) if 'macro_vix' in df.columns else opt_engine.fetch_live_iv(ticker=ticker)
                    # Approximate remaining time using exact dynamic DTE
                    days_held = bars_held if TIMEFRAME == "1d" else bars_held / 6.25
                    initial_dte = float(trade.get("days_to_expiry") or opt_engine.get_days_to_expiry(ticker))
                    days_to_expiry = max(0.001, initial_dte - days_held)
                    T = days_to_expiry / 365.0
                    act = str(trade.get("action", "BUY")).upper()
                    strat = str(trade.get("strategy_type", "DIRECTIONAL")).upper()
                    qty = trade.get("total_quantity") or trade.get("quantity") or opt_engine.get_lot_size(ticker)

                    if strat in ("CREDIT_SPREAD", "IRON_CONDOR") or trade.get("instrument_type") in ("SPREAD", "IRON_CONDOR"):
                        short_k = trade.get("opt_strike", 0.0)
                        long_k = trade.get("hedge_strike_price", 0.0)
                        opt_t = trade.get("opt_type", "PE")
                        bs_short = opt_engine._black_scholes(exit_spot, short_k, T, opt_engine.RISK_FREE_RATE, iv, opt_t if opt_t in ("CE", "PE") else "PE")
                        bs_long = opt_engine._black_scholes(exit_spot, long_k, T, opt_engine.RISK_FREE_RATE, iv, opt_t if opt_t in ("CE", "PE") else "PE")
                        p_short_exit = bs_short["premium"]
                        p_long_exit = bs_long["premium"]
                        p_short_entry = trade.get("opt_entry_premium", 0.0)
                        p_long_entry = trade.get("hedge_entry_price", 0.0)

                        f_calc = IndianFOFrictionModel.calculate_spread_friction(
                            short_entry_prem=p_short_entry,
                            short_exit_prem=p_short_exit,
                            long_entry_prem=p_long_entry,
                            long_exit_prem=p_long_exit,
                            quantity=qty
                        )
                        cash_pnl = f_calc.net_pnl
                        trade["opt_exit_premium"] = max(0.05, round(p_short_exit - p_long_exit, 2))
                    else:
                        bs_exit = opt_engine._black_scholes(
                            S=exit_spot,
                            K=trade["opt_strike"],
                            T=T,
                            r=opt_engine.RISK_FREE_RATE,
                            sigma=iv,
                            option_type=trade["opt_type"]
                        )
                        exit_premium = bs_exit["premium"]
                        trade["opt_exit_premium"] = exit_premium
                        entry_prem = trade.get("opt_entry_premium", trade.get("entry_price", exit_premium))

                        if act == "SELL":
                            f_calc = IndianFOFrictionModel.calculate_options_friction(
                                buy_premium=exit_premium,
                                sell_premium=entry_prem,
                                quantity=qty,
                                action="SELL"
                            )
                        else:
                            f_calc = IndianFOFrictionModel.calculate_options_friction(
                                buy_premium=entry_prem,
                                sell_premium=exit_premium,
                                quantity=qty,
                                action="BUY"
                            )
                        cash_pnl = f_calc.net_pnl

                    invested = trade.get('invested', 1.0)
                    net_pnl_pct = (cash_pnl / invested) if invested > 0 else 0.0
                    gross_pnl_pct = (f_calc.gross_pnl / invested) if invested > 0 else 0.0

                elif trade.get("instrument_type") == "FUTURE":
                    # Futures PnL: points difference * total_quantity minus regulatory friction
                    entry_p = trade.get('entry_price', 0)
                    exit_p = trade.get('exit_price', 0)
                    qty = trade.get('total_quantity') or trade.get('quantity', 1)
                    if entry_p > 0:
                        f_calc = IndianFOFrictionModel.calculate_futures_friction(
                            entry_price=entry_p,
                            exit_price=exit_p,
                            quantity=qty,
                            direction=trade['direction']
                        )
                        cash_pnl = f_calc.net_pnl
                        invested = trade.get('invested', 1.0)
                        net_pnl_pct = (cash_pnl / invested) if invested > 0 else 0.0
                        gross_pnl_pct = (f_calc.gross_pnl / invested) if invested > 0 else 0.0
                    else:
                        cash_pnl = 0.0
                        net_pnl_pct = 0.0
                        gross_pnl_pct = 0.0
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

                if trade.get("invested_deducted"):
                    account['capital'] += (trade.get('invested', 0.0) + cash_pnl)
                else:
                    account['capital'] += cash_pnl

                if account['capital'] > account['peak_capital']:
                    account['peak_capital'] = account['capital']

                exit_record = TradeLogger.log_exit(
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
                journal_events.append(exit_record)
                
                notifier.send_exit_alert(trade, is_live=False)

                # Update RL loop with risk-adjusted reward shaping (R-multiples)
                if trade.get("setup_signals"):
                    learner.update_from_trade(
                        setup_signals=trade["setup_signals"],
                        regime=trade.get("regime", "unknown"),
                        pnl_pct=net_pnl_pct,
                        is_win=net_pnl_pct > 0,
                        risk_pct=trade.get("risk_pct", 0.02)
                    )

                # Update F&O strike contextual bandit (FOLearner)
                if trade.get("is_fo") or trade.get("is_options"):
                    try:
                        opt_engine.fo_learner.update_from_trade(trade, net_pnl_pct=net_pnl_pct)
                    except Exception as fo_err:
                        logger.debug(f"FOLearner update error: {fo_err}")

                # Post-Trade Reflection Memory (TradingAgents architecture)
                try:
                    reflection = agent_reflector.reflect_on_trade(
                        trade=trade,
                        pnl_pct=net_pnl_pct,
                        cash_pnl=cash_pnl,
                        exit_reason=exit_reason,
                        bars_held=bars_held
                    )
                    logger.info(f"🧠 [AGENT REFLECTION] {reflection.lesson}")
                except Exception as ref_err:
                    logger.debug(f"Agent reflection error: {ref_err}")

                # Record outcome into Drawdown Circuit Breaker
                circuit_breaker.record_trade_outcome(pnl_pct=net_pnl_pct, cash_pnl=cash_pnl)

                logger.info(
                    f"[CLOSED] {ticker} | Reason: {exit_reason} | "
                    f"PnL: {net_pnl_pct*100:+.2f}% | Cash: ₹{cash_pnl:+,.2f} | "
                    f"Bars Held: {bars_held}"
                )
            else:
                # Calculate mark-to-market unrealized PnL for active trade
                if trade.get("is_options", False):
                    iv = (df['macro_vix'].iloc[-1] / 100.0) if 'macro_vix' in df.columns else opt_engine.fetch_live_iv(ticker=ticker)
                    days_held = bars_held if TIMEFRAME == "1d" else bars_held / 6.25
                    curr_prem, curr_delta = opt_engine.calculate_option_mtm(
                        trade=trade,
                        current_spot=current_price,
                        days_elapsed=days_held,
                        iv=iv
                    )
                    entry_prem = trade.get("opt_entry_premium", 0.0)
                    act = str(trade.get("action", "BUY")).upper()
                    strat = str(trade.get("strategy_type", "DIRECTIONAL")).upper()
                    qty = trade.get("total_quantity") or trade.get("quantity") or opt_engine.get_lot_size(ticker)

                    if strat in ("CREDIT_SPREAD", "IRON_CONDOR") or trade.get("instrument_type") in ("SPREAD", "IRON_CONDOR"):
                        gross_cash = (entry_prem - curr_prem) * qty
                    elif act == "SELL":
                        gross_cash = (entry_prem - curr_prem) * qty
                    else:
                        gross_cash = (curr_prem - entry_prem) * qty
                    trade["unrealized_pnl"] = gross_cash - (trade['invested'] * STT_SLIPPAGE_PCT)
                else:
                    entry_p = trade.get('entry_price', 0)
                    if entry_p > 0:
                        gross = (current_price - entry_p) / entry_p if trade['direction'] == 'LONG' else (entry_p - current_price) / entry_p
                        trade["unrealized_pnl"] = trade['invested'] * (gross - STT_SLIPPAGE_PCT)
                    else:
                        trade["unrealized_pnl"] = 0.0

            updated_trades.append(trade)

        save_trades(updated_trades)
        await persist_portfolio(account, updated_trades, journal_events)
        journal_events.clear()

        # Dynamically reload runtime configuration
        current_config = load_config()

        # --- Mark-to-Market Drawdown Check (Kill-Switch) ---
        total_unrealized_pnl = sum(t.get("unrealized_pnl", 0.0) for t in updated_trades if t['status'] == 'OPEN')
        mtm_equity = account['capital'] + total_unrealized_pnl

        if mtm_equity > account['peak_capital']:
            account['peak_capital'] = mtm_equity

        max_drawdown = float(current_config.get('max_portfolio_drawdown_pct', 0.10))
        if mtm_equity <= account['peak_capital'] * (1 - max_drawdown):
            account['status'] = 'SUSPENDED'
            kill_switch_record = TradeLogger.log_kill_switch(
                reason=f"{max_drawdown * 100:.1f}% PORTFOLIO MTM DRAWDOWN REACHED",
                capital=mtm_equity,
                peak_capital=account['peak_capital'],
                weekly_pnl=0.0,
                config_version=current_config.get("version", "v1.0")
            )
            journal_events.append(kill_switch_record)
            
            notifier.send_system_alert(
                f"Portfolio mark-to-market drawdown reached {max_drawdown * 100:.2f}%. Trading suspended.",
                level="CRITICAL",
            )
            logger.error(f"🚨 EMERGENCY STOP: {max_drawdown * 100:.2f}% PORTFOLIO DRAWDOWN REACHED!")

        save_account(account)
        await persist_portfolio(account, updated_trades, journal_events)
        journal_events.clear()

        if account['status'] == 'SUSPENDED':
            break

        # =================================================================
        # PHASE 2: Scan for New Entries (with full Risk Engine & Gates)
        # =================================================================
        # Drawdown Circuit Breaker Gate (claude-trading-skills)
        circuit_decision = circuit_breaker.evaluate(current_capital=account['capital'])
        if not circuit_decision.is_allowed:
            logger.warning(
                f"🚫 [CIRCUIT BREAKER GATE] New trades suspended: {circuit_decision.reason} | "
                f"Status: {circuit_decision.status} | Consecutive Losses: {circuit_decision.consecutive_losses}"
            )
            await asyncio.sleep(3600)
            continue

        open_tickers = [t.get('underlying_ticker', t['ticker']) for t in updated_trades if t['status'] == 'OPEN']

        for ticker in get_scanning_tickers():
            if ticker in open_tickers:
                continue  # Already in a trade for this instrument

            df = await asyncio.to_thread(fetch_and_enrich, ticker)
            if df is None:
                continue

            regime, setups = engine.evaluate_with_regime(df, ticker)
            regime_str = regime.get('regime', 'unknown')
            
            # Fetch RL weights and pass to brain
            setup_weights = learner.get_setup_weights(regime_str)
            prediction = ai_brain.predict(
                regime,
                setups,
                setup_weights=setup_weights,
                asset_class="IN_INDEX_FO",
                df=df,
            )

            signal = prediction.get("signal", "neutral")
            prob = prediction.get("probability", 0.0)

            # Only consider trades where AI is confident enough
            min_conf = float(current_config.get("min_ai_confidence", MIN_AI_CONFIDENCE))
            if prob < min_conf or signal not in ("bullish", "bearish"):
                continue

            # Multi-Agent Adversarial Debate & Consensus confirmation (TradingAgents)
            # Wire live NSE PCR, Max-Pain, GEX regime, and FII/DII net flows
            current_close = float(df['close'].iloc[-1])
            live_opts, live_sent = MultiAgentConsensusEngine.fetch_live_context(ticker, spot=current_close)
            min_consensus = float(current_config.get("min_consensus_weight", 1.2))
            consensus = MultiAgentConsensusEngine.evaluate(
                ticker=ticker,
                regime_data=regime,
                setup_signals=setups,
                options_data=live_opts,
                sentiment_data=live_sent,
                min_conviction_threshold=min_consensus,
            )
            is_rejected = (
                consensus.recommended_action.startswith("STAND ASIDE")
                or consensus.consensus_signal == "neutral"
                or "REJECT" in consensus.chief_risk_ruling.upper()
            )
            if is_rejected:
                logger.info(
                    f"🚫 [MULTI-AGENT REJECT] {ticker}: Chief Risk ruling: {consensus.chief_risk_ruling}. "
                    f"Action: {consensus.recommended_action}. Consensus: {consensus.consensus_signal} ({consensus.consensus_confidence:.2f})"
                )
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

            # --- Execute F&O Trade via DerivativeEngine ---
            # ALL trades go through F&O — no equity/cash segment
            if not trade_plan.is_approved:
                rejection_record = TradeLogger.log_rejection(
                    ticker=ticker,
                    direction=trade_plan.direction,
                    reasons=trade_plan.rejection_reasons,
                    ai_probability=trade_plan.ai_probability,
                    regime=trade_plan.regime,
                    config_version=CONFIG.get("version", "v2.0.0-fo")
                )
                journal_events.append(rejection_record)
                logger.warning(
                    f"[REJECTED SPOT PLAN] {ticker} {trade_plan.direction} — "
                    f"{'; '.join(trade_plan.rejection_reasons)}"
                )
                continue

            logger.info(f"\n{trade_plan.reasoning}")

            # Generate F&O derivative plan
            iv = (df['macro_vix'].iloc[-1] / 100.0) if 'macro_vix' in df.columns else None
            derivative_type = current_config.get("derivative_type", "AUTO")
            strike_pref = current_config.get("strike_preference", "AUTO")

            fo_plan = opt_engine.generate_derivative_plan(
                spot_plan=trade_plan,
                capital=account['capital'],
                derivative_type=derivative_type,
                strike_pref=strike_pref,
                regime=regime_str,
                iv=iv,
            )

            if not fo_plan.is_approved:
                rejection_record = TradeLogger.log_rejection(
                    ticker=fo_plan.contract_symbol,
                    direction=fo_plan.direction,
                    reasons=fo_plan.rejection_reasons,
                    ai_probability=trade_plan.ai_probability,
                    regime=trade_plan.regime,
                    config_version=CONFIG.get("version", "v2.0.0-fo")
                )
                journal_events.append(rejection_record)
                logger.warning(
                    f"[REJECTED F&O] {fo_plan.contract_symbol} — "
                    f"{'; '.join(fo_plan.rejection_reasons)}"
                )
                continue

            logger.info(f"\n{fo_plan.reasoning}")

            # Convert setup signals to serializable dicts
            setup_signals_list = [{"name": s.name, "signal": s.signal, "confidence": float(s.confidence)} for s in setups]

            import uuid
            new_trade = {
                "id": f"{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{ticker.replace('^', '')}_{uuid.uuid4().hex[:6]}",
                "ticker": fo_plan.contract_symbol,
                "underlying_ticker": ticker,
                "direction": fo_plan.direction,
                "instrument_type": fo_plan.instrument_type,
                "quantity": fo_plan.total_quantity,
                "invested": fo_plan.margin_or_premium_required,
                "entry_price": trade_plan.entry_price,  # Spot entry for tracking
                "tp": trade_plan.take_profit,            # Spot TP
                "sl": trade_plan.stop_loss,              # Spot SL
                "trailing_stop": trade_plan.stop_loss,
                "atr_at_entry": trade_plan.atr_at_entry,
                "probability": trade_plan.ai_probability,
                "risk_pct": trade_plan.risk_per_trade_pct,
                "risk_reward": fo_plan.risk_reward_ratio,
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
                # F&O specific fields
                "is_fo": True,
                "is_options": fo_plan.instrument_type in ("OPTION", "SPREAD", "IRON_CONDOR"),
                "instrument_type": fo_plan.instrument_type,
                "action": fo_plan.action,
                "strategy_type": fo_plan.strategy_type,
                "opt_type": fo_plan.option_type,
                "opt_strike": fo_plan.strike_price,
                "hedge_strike_price": fo_plan.hedge_strike_price,
                "hedge_entry_price": fo_plan.hedge_entry_price,
                "net_credit": fo_plan.net_credit,
                "opt_entry_premium": fo_plan.entry_price if fo_plan.instrument_type in ("OPTION", "SPREAD", "IRON_CONDOR") else 0.0,
                "opt_delta": fo_plan.delta,
                "opt_theta": fo_plan.theta,
                "strike_type": fo_plan.strike_type,
                "lot_size": fo_plan.lot_size,
                "lots_to_trade": fo_plan.lots_to_trade,
                "invested_deducted": True,
            }
            
            # Realistically deduct margin / premium from free portfolio cash
            account['capital'] = max(0.0, account['capital'] - new_trade["invested"])
            
            entry_record = TradeLogger.log_entry(
                trade_id=new_trade["id"],
                ticker=new_trade["ticker"],
                direction=fo_plan.direction,
                entry_price=fo_plan.entry_price,
                stop_loss=fo_plan.stop_loss_price,
                take_profit=fo_plan.target_price,
                quantity=new_trade["quantity"],
                invested=new_trade["invested"],
                risk_pct=trade_plan.risk_per_trade_pct,
                risk_reward=fo_plan.risk_reward_ratio,
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
                config_version=CONFIG.get("version", "v2.0.0-fo"),
                capital_at_entry=account['capital']
            )
            journal_events.append(entry_record)

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
            notifier.send_entry_alert(new_trade, is_live=False)

        await persist_portfolio(account, updated_trades, journal_events)
        journal_events.clear()

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
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(run_loop())
