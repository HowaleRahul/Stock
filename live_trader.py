"""
LIVE Execution Engine — Phase 9
HARD SEPARATION FROM PAPER TRADING.

This engine connects to the real broker API.
It will aggressively crash and refuse to run if the environment is not set to LIVE.
Includes strict parity with paper trading:
- DrawdownCircuitBreaker gate & trade outcome recording
- MultiAgentConsensusEngine adversarial debate gate
- Macro & options enrichment with dynamic India VIX IV
- Fail-closed security validation
- Robust database session recovery with rollback and disk fallback
"""

import asyncio
import json
import logging
import os
import datetime
import tempfile
import types
from typing import Dict, Any, List, Optional
import pandas as pd
from dotenv import load_dotenv

from setups.engine import SetupEngine
from ml.ensemble import EnsembleModel
from ml.risk_engine import RiskEngine
from ml.options_engine import OptionsEngine
from ml.drift_detector import DriftDetector
from ml.circuit_breaker import DrawdownCircuitBreaker
from ml.multi_agent_consensus import MultiAgentConsensusEngine
from ml.features import enrich_with_macro_and_options, enrich_with_psychology_features
from ml.assets import get_fo_name
from api.notifier import notifier
from api.broker import BrokerAPI
from api.config_store import load_config_atomic, CONFIG_PATH
import yfinance as yf
from sqlalchemy import select
from api.db import async_session_factory
from models.models import Trade

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("live_trader")

TIMEFRAME = "1h"
PERIOD = "60d"
TICKERS = ["^NSEI", "^NSEBANK", "^BSESN"]
LIVE_TRADES_FILE = "live_trades.json"


def load_config() -> dict:
    try:
        return load_config_atomic(CONFIG_PATH)
    except Exception as e:
        logger.warning(f"Error loading config via config_store: {e}. Falling back to default.")
        return {}


def _load_live_trades_disk() -> List[Dict[str, Any]]:
    if not os.path.exists(LIVE_TRADES_FILE):
        return []
    try:
        with open(LIVE_TRADES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception as e:
        logger.error(f"Failed to read disk live_trades: {e}")
        return []


def _save_live_trades_disk(trades: List[Dict[str, Any]]) -> None:
    directory = os.path.dirname(os.path.abspath(LIVE_TRADES_FILE)) or "."
    temp_path = None
    try:
        fd, temp_path = tempfile.mkstemp(dir=directory, prefix=".live_trades-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(trades, f, indent=4)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, LIVE_TRADES_FILE)
    except Exception as e:
        logger.error(f"Failed to persist disk live_trades: {e}")
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


async def get_active_trades():
    try:
        async with async_session_factory() as session:
            try:
                stmt = select(Trade).where(Trade.is_open == True)
                res = await session.execute(stmt)
                return list(res.scalars().all())
            except Exception:
                await session.rollback()
                raise
    except Exception as exc:
        logger.warning(f"Database session failed in get_active_trades: {exc}; falling back to disk state.")
        disk_trades = _load_live_trades_disk()
        res = []
        for dt in disk_trades:
            if dt.get("is_open", True):
                res.append(types.SimpleNamespace(
                    id=dt.get("id", dt.get("order_id")),
                    order_id=dt.get("order_id"),
                    ticker=dt.get("ticker"),
                    direction=dt.get("direction"),
                    entry_price=dt.get("entry_price"),
                    quantity=dt.get("quantity"),
                    invested=dt.get("invested"),
                    take_profit=dt.get("tp"),
                    stop_loss=dt.get("sl"),
                    is_open=True,
                    entry_time=None
                ))
        return res


async def close_trade(trade_id, exit_price, broker=None):
    closed_rec = None
    # 1. Attempt database close with automatic rollback
    try:
        async with async_session_factory() as session:
            try:
                stmt = select(Trade).where((Trade.id == trade_id) | (Trade.order_id == str(trade_id)))
                res = await session.execute(stmt)
                trade = res.scalar_one_or_none()
                if trade:
                    is_option = " " in (trade.ticker or "")
                    trade_action = getattr(trade, "action", None) or ("SELL" if "SELL" in (trade.ticker or "").upper() else "BUY")
                    if broker and getattr(broker, "is_connected", False):
                        try:
                            if is_option:
                                exit_dir = "BUY" if trade_action == "SELL" else "SELL"
                                exchange = "BFO" if "SENSEX" in (trade.ticker or "").upper() else "NFO"
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
                    if is_option and trade_action == "SELL":
                        pnl = -pnl
                    elif not is_option and str(trade.direction).upper() in {"BEARISH", "SHORT", "SELL"}:
                        pnl = -pnl
                    trade.pnl_pct = pnl * 100
                    cash_pnl = trade.invested * pnl if trade.invested else 0.0

                    await session.commit()
                    closed_rec = {
                        "id": trade.id,
                        "order_id": trade.order_id,
                        "ticker": trade.ticker,
                        "direction": trade.direction,
                        "entry_price": trade.entry_price,
                        "exit_price": exit_price,
                        "status": "CLOSED_TP" if pnl > 0 else "CLOSED_SL",
                        "pnl_pct": pnl,
                        "cash_pnl": cash_pnl,
                    }
            except Exception:
                await session.rollback()
                raise
    except Exception as db_err:
        logger.warning(f"Database error in close_trade for {trade_id}: {db_err}; syncing with disk state.")

    # 2. Synchronize disk fallback state
    disk_trades = _load_live_trades_disk()
    for dt in disk_trades:
        if str(dt.get("id")) == str(trade_id) or str(dt.get("order_id")) == str(trade_id):
            dt["is_open"] = False
            dt["exit_price"] = exit_price
            dt["exit_time"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            entry_p = float(dt.get("entry_price", 1.0))
            pnl = (exit_price - entry_p) / entry_p if entry_p > 0 else 0.0
            is_option = " " in (dt.get("ticker") or "")
            dt_action = str(dt.get("action", "SELL" if "SELL" in (dt.get("ticker") or "").upper() else "BUY")).upper()
            if is_option and dt_action == "SELL":
                pnl = -pnl
            elif not is_option and str(dt.get("direction", "")).upper() in {"BEARISH", "SHORT", "SELL"}:
                pnl = -pnl
            dt["pnl_pct"] = pnl * 100
            cash_pnl = float(dt.get("invested", 0.0)) * pnl
            dt["cash_pnl"] = cash_pnl
            if closed_rec is None:
                if broker and getattr(broker, "is_connected", False):
                    try:
                        if is_option:
                            exit_dir = "BUY" if dt_action == "SELL" else "SELL"
                        else:
                            exit_dir = "SELL" if str(dt.get("direction")).upper() in {"LONG", "BULLISH", "BUY"} else "BUY"
                        exchange = "BFO" if "SENSEX" in str(dt.get("ticker")).upper() else ("NFO" if is_option else "NSE")
                        broker.place_order(ticker=dt.get("ticker"), quantity=dt.get("quantity", 1), direction=exit_dir, exchange=exchange)
                    except Exception as b_err:
                        logger.error(f"Broker exit failed in disk fallback: {b_err}")
                closed_rec = {
                    "id": dt.get("id"),
                    "order_id": dt.get("order_id"),
                    "ticker": dt.get("ticker"),
                    "direction": dt.get("direction"),
                    "entry_price": entry_p,
                    "exit_price": exit_price,
                    "status": "CLOSED_TP" if pnl > 0 else "CLOSED_SL",
                    "pnl_pct": pnl,
                    "cash_pnl": cash_pnl,
                }
    _save_live_trades_disk(disk_trades)
    return closed_rec


async def open_trade(trade_record):
    # 1. Update disk fallback
    disk_trades = _load_live_trades_disk()
    order_id = str(trade_record.get("order_id"))
    record_copy = dict(trade_record)
    record_copy["is_open"] = True
    record_copy["entry_time"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    disk_trades = [t for t in disk_trades if str(t.get("order_id")) != order_id]
    disk_trades.append(record_copy)
    _save_live_trades_disk(disk_trades)

    # 2. Persist to database with rollback
    try:
        async with async_session_factory() as session:
            try:
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
            except Exception:
                await session.rollback()
                raise
    except Exception as exc:
        logger.warning(f"Database error in open_trade: {exc}; persisted to disk fallback.")


async def run_live_loop_async():
    logger.info("Initializing LIVE Trader...")

    # Strict Fail-Closed Verification
    if os.getenv("I_AM_READY_TO_LOSE_REAL_MONEY") != "True":
        logger.critical("🛑 FATAL: Attempted to run live_trader.py without explicit I_AM_READY_TO_LOSE_REAL_MONEY=True confirmation.")
        return

    broker_mode = os.getenv("BROKER_MODE", "disabled").lower()
    if broker_mode != "live":
        logger.critical(f"🛑 FATAL: BROKER_MODE is '{broker_mode}', not 'live'. Refusing live execution.")
        return

    whitelisted_ip = os.getenv("WHITELISTED_IP")
    if not whitelisted_ip:
        logger.critical("🛑 FATAL: WHITELISTED_IP is not configured; refusing live execution.")
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
    circuit_breaker = DrawdownCircuitBreaker()

    logger.info("🟢 LIVE TRADER ACTIVE. Real capital is now at risk.")

    while True:
        try:
            active_live_orders = await get_active_trades()
            config = load_config()
            min_ai_confidence = float(config.get("min_ai_confidence", 0.65))
            configured_capital = float(config.get("capital", 100000.0))
            actual_capital = broker.get_balance() if hasattr(broker, 'get_balance') else configured_capital

            # Drawdown Circuit Breaker Gate
            circuit_decision = circuit_breaker.evaluate(current_capital=actual_capital)
            if not circuit_decision.is_allowed:
                logger.warning(
                    f"🚫 [CIRCUIT BREAKER GATE] Live entries suspended: {circuit_decision.reason} | "
                    f"Status: {circuit_decision.status} | Consecutive Losses: {circuit_decision.consecutive_losses}"
                )

            for ticker in TICKERS:
                clean_sym = ticker.replace("^", "")
                df = await asyncio.to_thread(
                    yf.download, ticker, period=PERIOD, interval=TIMEFRAME, progress=False
                )

                if df is None or df.empty or len(df) < 50:
                    continue

                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df.columns = [c.lower() for c in df.columns]

                if 'adj close' in df.columns:
                    df = df.rename(columns={'adj close': 'adj_close'})

                # Parity: enrich with macro, options, psychology and ATR
                df = await asyncio.to_thread(enrich_with_macro_and_options, df, ticker, period=PERIOD, interval=TIMEFRAME)
                df = enrich_with_psychology_features(df)

                high_low = df['high'] - df['low']
                high_close = (df['high'] - df['close'].shift()).abs()
                low_close = (df['low'] - df['close'].shift()).abs()
                ranges = pd.concat([high_low, high_close, low_close], axis=1)
                df['atr'] = ranges.max(axis=1).rolling(14, min_periods=1).mean()

                current_price = float(df['close'].iloc[-1])
                fo_name = get_fo_name(ticker)

                # Check exits for open orders
                for trade in active_live_orders:
                    is_match = (
                        (trade.ticker == ticker)
                        or trade.ticker.startswith(ticker)
                        or trade.ticker.startswith(clean_sym)
                        or trade.ticker.startswith(fo_name)
                    )
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
                                        iv = (df['macro_vix'].iloc[-1] / 100.0) if ('macro_vix' in df.columns and not pd.isna(df['macro_vix'].iloc[-1]) and df['macro_vix'].iloc[-1] > 0) else 0.15
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
                                    circuit_breaker.record_trade_outcome(
                                        pnl_pct=closed_rec.get("pnl_pct", 0.0),
                                        cash_pnl=closed_rec.get("cash_pnl", 0.0)
                                    )

                # Gate: If circuit breaker is not allowed, refuse new trade entries
                if not circuit_decision.is_allowed:
                    continue

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
                    already_active = any(
                        (
                            t.ticker == ticker
                            or (t.ticker and (t.ticker.startswith(clean_sym) or t.ticker.startswith(fo_name)))
                        )
                        for t in active_live_orders
                    )
                    if already_active:
                        logger.info(f"Position already active for {fo_name} ({ticker}); skipping duplicate entry.")
                        continue

                    # Multi-Agent Adversarial Debate & Consensus confirmation (TradingAgents)
                    current_close = float(df['close'].iloc[-1])
                    live_opts, live_sent = MultiAgentConsensusEngine.fetch_live_context(ticker, spot=current_close)
                    consensus = MultiAgentConsensusEngine.evaluate(
                        ticker=ticker,
                        regime_data=regime,
                        setup_signals=setups,
                        options_data=live_opts,
                        sentiment_data=live_sent
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

                    trade_plan = risk_engine.generate_trade_plan(
                        ticker=ticker, direction=ai_signal, ai_probability=confidence,
                        df=df, capital=actual_capital, regime=regime.get('regime', 'unknown'), timeframe=TIMEFRAME
                    )

                    if trade_plan.is_approved:
                        dynamic_iv = (df['macro_vix'].iloc[-1] / 100.0) if ('macro_vix' in df.columns and not pd.isna(df['macro_vix'].iloc[-1]) and df['macro_vix'].iloc[-1] > 0) else opt_engine.fetch_live_iv(ticker=ticker)
                        opt_plan = opt_engine.generate_derivative_plan(
                            spot_plan=trade_plan,
                            capital=actual_capital,
                            derivative_type=CONFIG.get("derivative_type", "AUTO"),
                            strike_pref=CONFIG.get("strike_preference", "AUTO"),
                            regime=regime.get("regime", "trending"),
                            iv=dynamic_iv
                        )
                        if opt_plan.is_approved:
                            exchange = "BFO" if "SENSEX" in opt_plan.contract_symbol else "NFO"
                            order_dir = opt_plan.action.upper() if opt_plan.instrument_type == "OPTION" else ("BUY" if opt_plan.direction == "LONG" else "SELL")
                            order_id = broker.place_order(
                                ticker=opt_plan.contract_symbol,
                                quantity=opt_plan.total_quantity,
                                direction=order_dir,
                                exchange=exchange,
                            )
                            live_trade_record = {
                                "order_id": order_id,
                                "ticker": opt_plan.contract_symbol,
                                "underlying_ticker": ticker,
                                "direction": ai_signal,
                                "action": opt_plan.action,
                                "strategy_type": opt_plan.strategy_type,
                                "instrument_type": opt_plan.instrument_type,
                                "quantity": opt_plan.total_quantity,
                                "entry_price": opt_plan.entry_price,
                                "invested": opt_plan.margin_or_premium_required,
                                "sl": opt_plan.original_spot_plan.stop_loss,
                                "tp": opt_plan.original_spot_plan.take_profit,
                                "is_options": opt_plan.instrument_type in ("OPTION", "SPREAD"),
                                "hedge_strike_price": opt_plan.hedge_strike_price,
                                "hedge_entry_price": opt_plan.hedge_entry_price,
                                "net_credit": opt_plan.net_credit
                            }
                            await open_trade(live_trade_record)
                            notifier.send_entry_alert(live_trade_record, is_live=True)
                            logger.info(f"LIVE ORDER EXECUTED: {order_id} ({order_dir} {opt_plan.contract_symbol})")

            await asyncio.sleep(300)

        except Exception as e:
            logger.error(f"Live Loop Exception: {e}", exc_info=True)
            await asyncio.sleep(60)


def run_live_loop():
    asyncio.run(run_live_loop_async())


if __name__ == "__main__":
    run_live_loop()
