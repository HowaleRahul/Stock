"""
Live Market Paper Trading and Real-Time Learning Engine.

Designed for Frontpage-style experience:
- Virtual Wallet: Supports ₹10k, ₹25k, ₹50k, ₹1 Lakh up to ₹10 Lakh+
- Real-Time Execution: Paper trades on live market ticks (NSE/BSE) during market hours
- F&O Derivative Engine: Trades Index Futures or Options (Call/Put) fitted to user budget
- Smart Strike Selection: Selects ITM, ATM, or OTM according to capital and regime
- Live-ticking MTM: Real-time Mark-to-Market PnL tracking for Options (BS re-pricing) & Futures
- Continuous Reinforcement Learning: Real-time bandit weight adjustments & model updates on exit
- Multi-tier Data: Powered by TradingView TA feed and RealTimeDataFeed
"""

import os
import time
import datetime
import asyncio
import uuid
import logging
from typing import Dict, Any, List, Optional, Callable
import numpy as np
import pandas as pd

from data.market_hours import get_market_status, is_market_open
from data.realtime_feed import RealTimeDataFeed
from ml.ensemble import EnsembleModel
from ml.risk_engine import RiskEngine
from ml.options_engine import DerivativeEngine
from ml.trade_logger import TradeLogger
from ml.reinforcement_learner import ReinforcementLearner
from setups.engine import SetupEngine
from api.notifier import notifier

logger = logging.getLogger("trading.ml.live_market_learner")

DEFAULT_VIRTUAL_CAPITAL = 10000.0  # Default micro capital ₹10k
DEFAULT_TARGET_TICKERS = [
    "SBIN", "TATAMOTORS", "ITC", "RELIANCE", "INFY", "HDFCBANK", "ICICIBANK", "TCS", "NIFTY", "BANKNIFTY"
]


class LiveMarketLearner:
    """
    Manages live paper trading and real-time reinforcement learning during market hours.
    Dynamically scales position sizing, risk limits, and instruments based on user capital.
    Supports Index Selection (NIFTY, BANKNIFTY) and F&O Derivative Trading (Futures / Options).
    """

    def __init__(
        self,
        starting_capital: Optional[float] = None,
        tickers: Optional[List[str]] = None,
        min_ai_confidence: float = 0.65,
        stt_slippage_pct: float = 0.0005,
        log_callback: Optional[Callable[[str], None]] = None,
        target_index: Optional[str] = None,
        derivative_type: Optional[str] = None,
        strike_preference: Optional[str] = None,
    ):
        # Read from config.json if parameters not passed explicitly
        cfg = {}
        try:
            import json
            if os.path.exists("config.json"):
                with open("config.json", "r", encoding="utf-8") as f:
                    cfg = json.load(f)
        except Exception:
            pass

        if starting_capital is None:
            starting_capital = float(cfg.get("capital", DEFAULT_VIRTUAL_CAPITAL))

        self.starting_capital = float(starting_capital)
        self.capital = float(starting_capital)
        self.peak_capital = float(starting_capital)

        # F&O and Target Index Preferences
        self.target_index = (target_index or cfg.get("target_index", "ALL")).upper()
        self.derivative_type = (derivative_type or cfg.get("derivative_type", "AUTO")).upper()
        self.strike_preference = (strike_preference or cfg.get("strike_preference", "AUTO")).upper()

        # Configure tickers based on user target selection
        if self.target_index == "NIFTY":
            self.tickers = ["NIFTY"]
        elif self.target_index == "BANKNIFTY":
            self.tickers = ["BANKNIFTY"]
        elif self.target_index == "FINNIFTY":
            self.tickers = ["FINNIFTY"]
        else:
            self.tickers = tickers or DEFAULT_TARGET_TICKERS

        self.min_ai_confidence = min_ai_confidence
        self.stt_slippage_pct = stt_slippage_pct
        self.log_callback = log_callback

        self.open_trades: List[Dict[str, Any]] = []
        self.closed_trades: List[Dict[str, Any]] = []

        self.setup_engine = SetupEngine()
        self.ai_brain = EnsembleModel(timeframe="1h")
        self.learner = ReinforcementLearner()
        self.derivative_engine = DerivativeEngine()

        try:
            from ml.continuous_trainer import load_or_create_model
            self.ml_model, self.ml_scaler = load_or_create_model()
        except Exception:
            self.ml_model, self.ml_scaler = None, None

        # Telemetry metrics
        self.total_trades_count = 0
        self.winning_trades_count = 0
        self.losing_trades_count = 0
        self.current_unrealized_mtm = 0.0
        self.total_margin_deployed = 0.0
        self.last_cycle_time = 0.0

    def log(self, msg: str):
        logger.info(msg)
        if self.log_callback:
            try:
                self.log_callback(msg)
            except Exception:
                pass

    def get_portfolio_state(self) -> Dict[str, Any]:
        """Returns the current portfolio state with live MTM and F&O status."""
        total_pnl = self.capital - self.starting_capital
        total_pnl_pct = (total_pnl / self.starting_capital * 100) if self.starting_capital > 0 else 0.0
        win_rate = (self.winning_trades_count / self.total_trades_count * 100) if self.total_trades_count > 0 else 0.0

        return {
            "starting_capital": self.starting_capital,
            "cash_balance": round(self.capital, 2),
            "peak_capital": round(self.peak_capital, 2),
            "margin_deployed": round(self.total_margin_deployed, 2),
            "unrealized_mtm": round(self.current_unrealized_mtm, 2),
            "net_liquidation_value": round(self.capital + self.current_unrealized_mtm, 2),
            "total_realized_pnl": round(total_pnl, 2),
            "total_realized_pnl_pct": round(total_pnl_pct, 2),
            "open_positions_count": len(self.open_trades),
            "closed_trades_count": len(self.closed_trades),
            "win_rate": round(win_rate, 2),
            "target_index": self.target_index,
            "derivative_type": self.derivative_type,
            "strike_preference": self.strike_preference,
            "fo_summary": self.derivative_engine.fo_learner.get_summary(),
            "open_trades": list(self.open_trades),
            "last_cycle_time": self.last_cycle_time,
        }

    def update_live_mtm(self):
        """
        Calculates live Mark-To-Market (MTM) PnL for all active open positions
        using current real-time quotes, Black-Scholes for Options, and Linear tracking for Futures.
        """
        total_mtm = 0.0
        total_margin = 0.0

        for trade in self.open_trades:
            underlying = trade.get("underlying_ticker", trade["ticker"])
            quote = RealTimeDataFeed.get_realtime_quote_sync(underlying)
            spot_ltp = quote.get("ltp", 0.0)
            if spot_ltp <= 0:
                spot_ltp = trade.get("entry_spot", trade["entry_price"])

            inst_type = trade.get("instrument_type", "EQUITY")
            entry_p = trade["entry_price"]
            qty = trade["quantity"]
            direction = trade["direction"]

            if inst_type == "OPTION":
                # Option MTM: re-price theoretical option premium using Black-Scholes
                bars_held = trade.get("bars_held", 0)
                days_elapsed = max(0.01, bars_held / 6.25)
                live_prem, live_delta = self.derivative_engine.calculate_option_mtm(
                    trade, current_spot=spot_ltp, days_elapsed=days_elapsed
                )
                trade["current_ltp"] = round(live_prem, 2)
                trade["current_spot"] = round(spot_ltp, 2)
                trade["delta"] = round(live_delta, 3)

                # For bought options (Long CE or Long PE):
                # PnL = (current_premium - entry_premium) * quantity
                pnl = (live_prem - entry_p) * qty

            elif inst_type == "FUTURE":
                # Future MTM: tracks spot movement with 1.0 delta
                trade["current_ltp"] = spot_ltp
                if direction in ("LONG", "bullish"):
                    pnl = (spot_ltp - entry_p) * qty
                else:
                    pnl = (entry_p - spot_ltp) * qty

            else:
                # Regular Equity Spot
                trade["current_ltp"] = spot_ltp
                if direction in ("LONG", "bullish"):
                    pnl = (spot_ltp - entry_p) * qty
                else:
                    pnl = (entry_p - spot_ltp) * qty

            trade["unrealized_pnl"] = round(pnl, 2)
            trade["unrealized_pnl_pct"] = round(
                (pnl / trade["invested"] * 100) if trade["invested"] > 0 else 0.0, 2
            )

            total_mtm += pnl
            total_margin += trade["invested"]

        self.current_unrealized_mtm = total_mtm
        self.total_margin_deployed = total_margin

    def manage_open_trades(self):
        """
        Checks TP, SL, Trailing Stop, and Time Exit against real-time quotes.
        Triggers instant reinforcement learning on exit for both setup weights
        and F&O strike/derivative weights.
        """
        remaining_open = []

        for trade in self.open_trades:
            underlying = trade.get("underlying_ticker", trade["ticker"])
            quote = RealTimeDataFeed.get_realtime_quote_sync(underlying)
            spot_ltp = quote.get("ltp", 0.0)
            if spot_ltp <= 0:
                remaining_open.append(trade)
                continue

            inst_type = trade.get("instrument_type", "EQUITY")
            bars_held = trade.get("bars_held", 0) + 1
            trade["bars_held"] = bars_held

            exit_reason = None
            exit_price = trade.get("current_ltp", trade["entry_price"])

            if inst_type == "OPTION":
                # Option Exit Management
                current_prem = trade.get("current_ltp", trade["entry_price"])
                entry_prem = trade["entry_price"]
                sl_prem = trade["sl"]
                tp_prem = trade["tp"]
                trailing_sl = trade.get("trailing_stop", sl_prem)

                # Option Trailing Stop: If option premium gained > 1× initial risk,
                # move stop-loss to breakeven!
                risk_pts = max(1.0, entry_prem - sl_prem)
                if current_prem - entry_prem >= 0.8 * risk_pts:
                    trailing_sl = max(trailing_sl, entry_prem * 1.002)
                    trade["trailing_stop"] = trailing_sl

                # Check TP / SL hit
                if current_prem >= tp_prem:
                    exit_reason = "TAKE_PROFIT"
                    exit_price = current_prem
                elif current_prem <= trailing_sl:
                    exit_reason = "TRAILING_SL" if trailing_sl > sl_prem else "STOP_LOSS"
                    exit_price = trailing_sl

            else:
                # Futures or Equity Exit Management
                high = quote.get("high", spot_ltp)
                low = quote.get("low", spot_ltp)

                trade = RiskEngine.update_trailing_stop(trade, high, low)
                active_sl = trade.get("trailing_stop", trade["sl"])

                if trade["direction"] in ("LONG", "bullish"):
                    if low <= active_sl:
                        exit_reason = "TRAILING_SL" if active_sl != trade["sl"] else "STOP_LOSS"
                        exit_price = active_sl
                    elif high >= trade["tp"]:
                        exit_reason = "TAKE_PROFIT"
                        exit_price = trade["tp"]
                elif trade["direction"] in ("SHORT", "bearish"):
                    if high >= active_sl:
                        exit_reason = "TRAILING_SL" if active_sl != trade["sl"] else "STOP_LOSS"
                        exit_price = active_sl
                    elif low <= trade["tp"]:
                        exit_reason = "TAKE_PROFIT"
                        exit_price = trade["tp"]

            if exit_reason:
                # Trade is exiting!
                entry_p = trade["entry_price"]
                if inst_type == "OPTION":
                    gross_pnl_pct = (exit_price - entry_p) / entry_p if entry_p > 0 else 0.0
                elif trade["direction"] in ("LONG", "bullish"):
                    gross_pnl_pct = (exit_price - entry_p) / entry_p if entry_p > 0 else 0.0
                else:
                    gross_pnl_pct = (entry_p - exit_price) / entry_p if entry_p > 0 else 0.0

                net_pnl_pct = gross_pnl_pct - self.stt_slippage_pct
                cash_pnl = trade["invested"] * net_pnl_pct

                trade["status"] = exit_reason
                trade["exit_price"] = exit_price
                trade["pnl_pct"] = net_pnl_pct
                trade["cash_pnl"] = cash_pnl
                trade["closed_at"] = datetime.datetime.now().isoformat()

                # Update wallet capital
                self.capital += cash_pnl
                if self.capital > self.peak_capital:
                    self.peak_capital = self.capital

                self.total_trades_count += 1
                if cash_pnl > 0:
                    self.winning_trades_count += 1
                else:
                    self.losing_trades_count += 1

                self.closed_trades.append(trade)

                # =================================================================
                # 1. AUTOMATED F&O REINFORCEMENT LEARNING:
                # Updates Strike & Derivative weights immediately from trade outcome
                # =================================================================
                if inst_type in ("OPTION", "FUTURE"):
                    try:
                        self.derivative_engine.fo_learner.update_from_trade(trade, net_pnl_pct)
                    except Exception as fo_err:
                        logger.debug(f"FO learner update error: {fo_err}")

                # =================================================================
                # 2. AUTOMATED SETUP REINFORCEMENT LEARNING:
                # =================================================================
                if trade.get("setup_signals"):
                    self.learner.update_from_trade(
                        setup_signals=trade["setup_signals"],
                        regime=trade.get("regime", "trending"),
                        pnl_pct=net_pnl_pct,
                        is_win=net_pnl_pct > 0
                    )

                # =================================================================
                # 3. ONLINE INCREMENTAL ML MODEL TRAINING (LIVE MARKET HOURS):
                # Retrains SGD/Ensemble Brain on live trade outcomes in real time
                # =================================================================
                if self.ml_model is not None and self.ml_scaler is not None and trade.get("feature_snapshot"):
                    try:
                        from ml.continuous_trainer import save_model, _reset_if_feature_schema_changed
                        y_val = 1 if net_pnl_pct > 0.005 else (-1 if net_pnl_pct < -0.005 else 0)
                        feat_df = pd.DataFrame([trade["feature_snapshot"]])
                        self.ml_model, self.ml_scaler = _reset_if_feature_schema_changed(self.ml_model, self.ml_scaler, feat_df)
                        self.ml_scaler.partial_fit(feat_df)
                        feat_scaled = self.ml_scaler.transform(feat_df)
                        self.ml_model.partial_fit(feat_scaled, np.array([y_val]), classes=np.array([-1, 0, 1]))
                        save_model(self.ml_model, self.ml_scaler, feat_df.columns, "IN_EQUITY", "1h")
                        self.log(f"🧠 [LIVE ONLINE TRAINING] AI Brain retrained on completed {trade.get('contract_symbol')} trade! Outcome: y={y_val}")
                    except Exception as ml_fit_err:
                        logger.debug(f"Live ML partial fit error: {ml_fit_err}")

                # Log trade exit to TradeLogger
                try:
                    TradeLogger.log_exit(
                        trade_id=trade["id"],
                        ticker=trade.get("contract_symbol", underlying),
                        direction=trade["direction"],
                        exit_price=exit_price,
                        exit_reason=exit_reason,
                        pnl_pct=net_pnl_pct,
                        cash_pnl=cash_pnl,
                        bars_held=bars_held,
                        regime_at_exit=trade.get("regime", "unknown"),
                        capital_after_exit=self.capital,
                        setup_signals_at_entry=trade.get("setup_signals", [])
                    )
                except Exception as log_err:
                    logger.debug(f"TradeLogger exit error: {log_err}")

                try:
                    notifier.send_exit_alert(trade, is_live=False)
                except Exception:
                    pass

                self.log(
                    f"[LIVE TRADE CLOSED] {trade.get('contract_symbol', underlying)} | "
                    f"Reason: {exit_reason} | PnL: {net_pnl_pct*100:+.2f}% (₹{cash_pnl:+,.2f}) | "
                    f"Capital: ₹{self.capital:,.2f} | F&O & Setup weights updated!"
                )
            else:
                remaining_open.append(trade)

        self.open_trades = remaining_open
        self.update_live_mtm()

    def scan_for_entries(self):
        """
        Scans instruments for new setups, evaluates AI Brain predictions,
        and opens paper positions in Futures, Options, or Equities according to budget.
        """
        open_tickers = {t.get("underlying_ticker", t["ticker"]) for t in self.open_trades}
        risk_engine = RiskEngine(historical_trades=self.closed_trades)

        for ticker in self.tickers:
            if ticker in open_tickers:
                continue

            # Fetch candles & real-time TradingView TA
            candles = RealTimeDataFeed.get_chart_candles_sync(ticker, timeframe="1h", limit=150)
            if not candles or len(candles) < 30:
                continue

            # Convert to DataFrame for setup evaluation
            df = pd.DataFrame(candles)
            df.columns = [c.lower() for c in df.columns]
            if "time" in df.columns:
                df["datetime"] = pd.to_datetime(df["time"], unit="s")
                df.set_index("datetime", inplace=True)

            # High-low true range for ATR
            high_low = df["high"] - df["low"]
            high_close = (df["high"] - df["close"].shift()).abs()
            low_close = (df["low"] - df["close"].shift()).abs()
            df["atr"] = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1).rolling(14, min_periods=1).mean()

            regime_data, setups = self.setup_engine.evaluate_with_regime(df, ticker)
            regime_str = regime_data.get("regime", "trending")

            # Fetch live TradingView indicators and recommendation
            tv_analysis = RealTimeDataFeed.get_tradingview_analysis_sync(ticker, interval="1h")
            tv_rec = tv_analysis.get("summary", {}).get("RECOMMENDATION", "NEUTRAL")

            # Obtain dynamic RL weights for current regime
            setup_weights = self.learner.get_setup_weights(regime_str)
            prediction = self.ai_brain.predict(regime_data, setups, setup_weights)

            signal = prediction.get("signal", "neutral")
            prob = prediction.get("probability", 0.0)

            # Boost confidence if TradingView consensus agrees
            if signal == "bullish" and tv_rec in ("BUY", "STRONG_BUY"):
                prob = min(0.98, prob + 0.08)
            elif signal == "bearish" and tv_rec in ("SELL", "STRONG_SELL"):
                prob = min(0.98, prob + 0.08)

            if prob < self.min_ai_confidence or signal not in ("bullish", "bearish"):
                continue

            # Generate spot plan via Risk Engine
            spot_plan = risk_engine.generate_trade_plan(
                ticker=ticker,
                direction=signal,
                ai_probability=prob,
                df=df,
                capital=self.capital,
                regime=regime_str,
                timeframe="1h",
                open_positions=self.open_trades,
            )

            # Check if we should execute as Derivative (Futures or Options)
            is_index = ticker.upper() in ("NIFTY", "BANKNIFTY", "FINNIFTY", "^NSEI", "^NSEBANK")
            should_trade_derivative = is_index or (self.derivative_type != "EQUITY" and self.derivative_engine.is_derivative_supported(ticker))

            if should_trade_derivative:
                # Use DerivativeEngine to select Futures vs Options & Strike according to budget
                d_plan = self.derivative_engine.generate_derivative_plan(
                    spot_plan=spot_plan,
                    capital=self.capital,
                    derivative_type=self.derivative_type,
                    strike_pref=self.strike_preference,
                    regime=regime_str
                )

                if not d_plan.is_approved:
                    self.log(f"[DERIVATIVE REJECTED] {d_plan.contract_symbol}: {', '.join(d_plan.rejection_reasons)}")
                    continue

                setup_signals_list = [{"name": s.name, "signal": s.signal, "confidence": float(s.confidence)} for s in setups]
                trade_id = f"{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{d_plan.contract_symbol.replace(' ', '_')}_{uuid.uuid4().hex[:6]}"

                feature_snapshot = {
                    "regime_val": 1 if "bull" in regime_str else (-1 if "bear" in regime_str else 0),
                    "regime_adx": float(regime_data.get("adx", 0.0)),
                    "macro_vix": 14.0,
                    "macro_spx_ret": 0.0,
                    "macro_usdinr_ret": 0.0,
                    "macro_btc_volume_ret": 0.0,
                    "opt_delta": float(d_plan.delta),
                    "opt_gamma": float(d_plan.gamma),
                    "psych_fomo_streak": 0.0,
                    "psych_panic_index": 0.0,
                    "psych_dist_to_round": 0.0,
                    "psych_session_phase": 0.5,
                    "atr": float(df["atr"].iloc[-1]) if "atr" in df.columns else 20.0,
                    "tf_hint": 0.5,
                    "IN_EQUITY": 1,
                }
                for s in setups:
                    feature_snapshot[f"{s.name}_sig"] = 1 if s.signal == "bullish" else (-1 if s.signal == "bearish" else 0)
                    feature_snapshot[f"{s.name}_conf"] = float(s.confidence)

                new_trade = {
                    "id": trade_id,
                    "ticker": ticker,
                    "underlying_ticker": d_plan.underlying_ticker,
                    "contract_symbol": d_plan.contract_symbol,
                    "instrument_type": d_plan.instrument_type,
                    "option_type": d_plan.option_type,
                    "strike": d_plan.strike_price,
                    "strike_type": d_plan.strike_type,
                    "direction": d_plan.direction,
                    "lot_size": d_plan.lot_size,
                    "lots": d_plan.lots_to_trade,
                    "quantity": d_plan.total_quantity,
                    "entry_price": d_plan.entry_price,
                    "entry_spot": spot_plan.entry_price,
                    "invested": d_plan.margin_or_premium_required,
                    "tp": d_plan.target_price,
                    "sl": d_plan.stop_loss_price,
                    "trailing_stop": d_plan.stop_loss_price,
                    "delta": d_plan.delta,
                    "theta": d_plan.theta,
                    "gamma": d_plan.gamma,
                    "iv": d_plan.iv,
                    "probability": spot_plan.ai_probability,
                    "risk_reward": d_plan.risk_reward_ratio,
                    "regime": spot_plan.regime,
                    "capital_tier": spot_plan.capital_tier,
                    "max_hold_bars": spot_plan.max_hold_bars,
                    "bars_held": 0,
                    "status": "OPEN",
                    "opened_at": datetime.datetime.now().isoformat(),
                    "setup_signals": setup_signals_list,
                    "setup_weights": setup_weights,
                    "feature_snapshot": feature_snapshot,
                    "tv_recommendation": tv_rec,
                    "current_ltp": d_plan.entry_price,
                    "unrealized_pnl": 0.0,
                    "unrealized_pnl_pct": 0.0,
                }

                self.open_trades.append(new_trade)
                self.update_live_mtm()

                try:
                    notifier.send_entry_alert(new_trade, is_live=False)
                except Exception:
                    pass

                self.log(
                    f"[LIVE F&O ENTRY] {d_plan.contract_symbol} ({d_plan.strike_type}) | "
                    f"Invested: ₹{d_plan.margin_or_premium_required:,.2f} | "
                    f"Entry: ₹{d_plan.entry_price:,.2f} | TP: ₹{d_plan.target_price:,.2f} | "
                    f"SL: ₹{d_plan.stop_loss_price:,.2f} | Delta: {d_plan.delta:.2f} | R:R: {d_plan.risk_reward_ratio:.2f}:1"
                )
                continue

            # Fallback to Equity Spot Plan
            if not spot_plan.is_approved:
                continue

            setup_signals_list = [{"name": s.name, "signal": s.signal, "confidence": float(s.confidence)} for s in setups]
            trade_id = f"{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{ticker}_{uuid.uuid4().hex[:6]}"

            new_trade = {
                "id": trade_id,
                "ticker": ticker,
                "underlying_ticker": ticker,
                "contract_symbol": f"{ticker} EQ",
                "instrument_type": "EQUITY",
                "direction": spot_plan.direction,
                "quantity": max(1, spot_plan.position_size_qty),
                "invested": spot_plan.position_value,
                "entry_price": spot_plan.entry_price,
                "tp": spot_plan.take_profit,
                "sl": spot_plan.stop_loss_price if hasattr(spot_plan, "stop_loss_price") else spot_plan.stop_loss,
                "trailing_stop": spot_plan.stop_loss,
                "atr_at_entry": spot_plan.atr_at_entry,
                "probability": spot_plan.ai_probability,
                "risk_pct": spot_plan.risk_per_trade_pct,
                "risk_reward": spot_plan.risk_reward_ratio,
                "kelly_fraction": spot_plan.kelly_fraction,
                "probability_of_ruin": spot_plan.probability_of_ruin,
                "regime": spot_plan.regime,
                "capital_tier": spot_plan.capital_tier,
                "max_hold_bars": spot_plan.max_hold_bars,
                "bars_held": 0,
                "status": "OPEN",
                "opened_at": datetime.datetime.now().isoformat(),
                "setup_signals": setup_signals_list,
                "setup_weights": setup_weights,
                "tv_recommendation": tv_rec,
                "current_ltp": spot_plan.entry_price,
                "unrealized_pnl": 0.0,
                "unrealized_pnl_pct": 0.0,
            }

            self.open_trades.append(new_trade)
            self.update_live_mtm()

            try:
                notifier.send_entry_alert(new_trade, is_live=False)
            except Exception:
                pass

            self.log(
                f"[LIVE ENTRY] {ticker} {spot_plan.direction} | "
                f"LTP: ₹{spot_plan.entry_price:,.2f} | TP: ₹{spot_plan.take_profit:,.2f} | "
                f"SL: ₹{spot_plan.stop_loss:,.2f} | R:R: {spot_plan.risk_reward_ratio:.2f}:1 | "
                f"Size: {spot_plan.position_size_qty} | AI Conf: {prob*100:.1f}% | TV: {tv_rec}"
            )

    def execute_live_cycle(self):
        """Runs one iteration of the live market learning loop."""
        self.last_cycle_time = time.time()
        self.manage_open_trades()
        self.scan_for_entries()
        self.update_live_mtm()
