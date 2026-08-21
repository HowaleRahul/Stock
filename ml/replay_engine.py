"""
Historical Replay Engine — RL Self-Play Phase A.

Replays historical candles bar-by-bar through the full trading pipeline
(SetupEngine → EnsembleModel → RiskEngine → VirtualBroker) to generate
thousands of simulated trades at high speed.

This is the AlphaZero "self-play" loop:
1. Download 5 years of data for a ticker
2. Replay it one bar at a time
3. The AI makes trade decisions using the same logic as paper_trader
4. Every trade is journaled with full context
5. Every N trades, the RL learner reviews the journal and updates weights
6. The updated weights feed into the next batch of decisions

The result: the AI bootstraps thousands of trades of experience in minutes
instead of waiting months for live market data.
"""

from __future__ import annotations

import logging
import uuid
import time
from typing import Dict, Any, List, Optional

import numpy as np
import pandas as pd
import yfinance as yf

from setups.engine import SetupEngine
from ml.ensemble import EnsembleModel
from ml.risk_engine import RiskEngine
from ml.trade_logger import TradeLogger
from ml.reinforcement_learner import ReinforcementLearner
from ml.journal_analyzer import JournalAnalyzer
from ml.features import (
    enrich_with_macro_and_options,
    enrich_with_psychology_features,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("replay_engine")


class VirtualBroker:
    """
    Simulates a broker with a virtual wallet.
    Tracks capital, open positions, MTM PnL, margin, and trade history.
    """

    STT_SLIPPAGE_PCT = 0.0005  # 0.05% transaction cost per trade

    def __init__(self, starting_capital: float = 1_000_000.0):
        self.starting_capital = starting_capital
        self.capital = starting_capital
        self.peak_capital = starting_capital
        self.open_trades: List[Dict[str, Any]] = []
        self.closed_trades: List[Dict[str, Any]] = []
        self.total_trades = 0

    def get_balance(self) -> float:
        return self.capital

    def get_mtm_pnl(self, current_prices: Dict[str, float]) -> float:
        """Calculate total unrealized PnL across all open positions."""
        total_mtm = 0.0
        for trade in self.open_trades:
            ticker = trade.get("underlying_ticker", trade["ticker"])
            current = current_prices.get(ticker, trade["entry_price"])
            entry = trade["entry_price"]
            if entry <= 0:
                continue
            if trade["direction"] == "LONG":
                pnl = (current - entry) / entry
            else:
                pnl = (entry - current) / entry
            total_mtm += trade["invested"] * pnl
        return total_mtm

    def open_trade(self, trade: Dict[str, Any]) -> None:
        """Open a new position."""
        self.open_trades.append(trade)
        self.total_trades += 1

    def close_trade(
        self, trade_id: str, exit_price: float, exit_reason: str, bar_time: str
    ) -> Optional[Dict[str, Any]]:
        """Close a position and update capital."""
        for i, trade in enumerate(self.open_trades):
            if trade["id"] == trade_id:
                entry_price = trade["entry_price"]
                if entry_price <= 0:
                    self.open_trades.pop(i)
                    return None

                if trade["direction"] == "LONG":
                    gross_pnl_pct = (exit_price - entry_price) / entry_price
                else:
                    gross_pnl_pct = (entry_price - exit_price) / entry_price

                net_pnl_pct = gross_pnl_pct - self.STT_SLIPPAGE_PCT
                cash_pnl = trade["invested"] * net_pnl_pct

                trade["exit_price"] = exit_price
                trade["exit_reason"] = exit_reason
                trade["pnl_pct"] = net_pnl_pct
                trade["cash_pnl"] = cash_pnl
                trade["closed_at"] = bar_time
                trade["status"] = exit_reason

                self.capital += cash_pnl
                if self.capital > self.peak_capital:
                    self.peak_capital = self.capital

                self.closed_trades.append(trade)
                self.open_trades.pop(i)
                return trade
        return None

    @property
    def drawdown_pct(self) -> float:
        if self.peak_capital <= 0:
            return 0.0
        return (self.peak_capital - self.capital) / self.peak_capital

    @property
    def is_suspended(self) -> bool:
        return self.drawdown_pct >= 0.10  # 10% drawdown kill switch


class ReplayEngine:
    """
    Replays historical candle data through the full AI trading pipeline.

    Usage:
        engine = ReplayEngine()
        results = engine.replay("^NSEI", period="5y", timeframe="1d")
    """

    MIN_WARMUP_BARS = 100
    RL_UPDATE_INTERVAL = 50  # Review journal every 50 trades
    MIN_AI_CONFIDENCE = 0.55  # Lower threshold for replay to generate more trades

    def __init__(
        self,
        starting_capital: float = 1_000_000.0,
        log_callback=None,
    ):
        self.broker = VirtualBroker(starting_capital=starting_capital)
        self.engine = SetupEngine()
        self.ai_brain = EnsembleModel(timeframe="1d")
        self.learner = ReinforcementLearner()
        self.risk_engine = RiskEngine()
        self.log_callback = log_callback
        self._trade_counter = 0

    def _log(self, msg: str) -> None:
        logger.info(msg)
        if self.log_callback:
            self.log_callback(msg)

    def replay(
        self,
        ticker: str,
        period: str = "5y",
        timeframe: str = "1d",
        asset_class: str = "IN_EQUITY",
    ) -> Dict[str, Any]:
        """
        Download historical data and replay bar-by-bar.

        Args:
            ticker: Yahoo Finance ticker symbol
            period: Data period (e.g., "5y", "2y")
            timeframe: Candle interval (e.g., "1d", "1h")
            asset_class: "IN_EQUITY", "US_EQUITY", or "CRYPTO"

        Returns:
            Dict with replay results and statistics.
        """
        self._log(f"📥 Downloading {ticker} ({period}, {timeframe})...")

        df = yf.download(ticker, period=period, interval=timeframe, progress=False)
        if df.empty or len(df) < self.MIN_WARMUP_BARS + 20:
            self._log(f"❌ Not enough data for {ticker}. Need at least {self.MIN_WARMUP_BARS + 20} bars.")
            return {"status": "error", "reason": "insufficient_data"}

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.lower() for c in df.columns]

        # Enrich with macro and psychology features
        self._log(f"🔧 Enriching features for {ticker} ({asset_class})...")
        try:
            df = enrich_with_macro_and_options(df, ticker, asset_class=asset_class)
            df = enrich_with_psychology_features(df)
        except Exception as e:
            self._log(f"❌ Feature enrichment failed: {e}")
            return {"status": "error", "reason": str(e)}

        # Calculate ATR
        high_low = df["high"] - df["low"]
        high_close = np.abs(df["high"] - df["close"].shift())
        low_close = np.abs(df["low"] - df["close"].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        df["atr"] = true_range.rolling(14).mean().fillna(true_range.mean())

        total_bars = len(df)
        self._log(
            f"🔄 Starting replay: {total_bars} bars, "
            f"warmup={self.MIN_WARMUP_BARS}, "
            f"capital=₹{self.broker.capital:,.0f}"
        )

        # ---- BAR-BY-BAR REPLAY ----
        for bar_idx in range(self.MIN_WARMUP_BARS, total_bars):
            if self.broker.is_suspended:
                self._log("🚨 KILL SWITCH: 10% drawdown reached. Stopping replay.")
                break

            # The AI can only see data up to (and including) the current bar
            visible_df = df.iloc[: bar_idx + 1]
            current_bar = df.iloc[bar_idx]
            current_price = float(current_bar["close"])
            bar_high = float(current_bar["high"])
            bar_low = float(current_bar["low"])
            bar_time = str(df.index[bar_idx])

            # --- Phase 1: Check open trades for exits ---
            self._check_exits(bar_high, bar_low, current_price, bar_time, ticker)

            # --- Phase 2: Look for new entries ---
            # Only if no open trade for this ticker
            open_tickers = [t["ticker"] for t in self.broker.open_trades]
            if ticker not in open_tickers:
                self._check_entry(
                    visible_df, ticker, current_price, bar_time,
                    timeframe, asset_class
                )

            # --- Phase 3: Periodic RL self-review ---
            if (
                self._trade_counter > 0
                and self._trade_counter % self.RL_UPDATE_INTERVAL == 0
            ):
                self._run_self_review()

        # ---- POST-REPLAY: Force-close any remaining open trades ----
        final_price = float(df["close"].iloc[-1])
        final_time = str(df.index[-1])
        for trade in list(self.broker.open_trades):
            self.broker.close_trade(trade["id"], final_price, "REPLAY_END", final_time)

        # Final RL review
        if self._trade_counter > 0:
            self._run_self_review()

        return self._compile_results(ticker, timeframe, total_bars)

    def _check_exits(
        self,
        bar_high: float,
        bar_low: float,
        current_price: float,
        bar_time: str,
        ticker: str,
    ) -> None:
        """Check all open trades for TP/SL/trailing stop/time exits."""
        for trade in list(self.broker.open_trades):
            if trade.get("underlying_ticker", trade["ticker"]) != ticker:
                continue

            # Update trailing stop
            trade = RiskEngine.update_trailing_stop(trade, bar_high, bar_low)
            active_sl = trade.get("trailing_stop", trade["sl"])

            # Increment bars held
            bars_held = trade.get("bars_held", 0) + 1
            trade["bars_held"] = bars_held

            # Time exit check
            time_exit = RiskEngine.check_time_exit(trade, bars_held)

            exit_reason = None
            exit_price = current_price

            if time_exit:
                exit_reason = "TIME_EXIT"
            elif trade["direction"] == "LONG":
                if bar_low <= active_sl:
                    exit_reason = "TRAILING_SL" if active_sl != trade["sl"] else "CLOSED_LOSS"
                    exit_price = active_sl
                elif bar_high >= trade["tp"]:
                    exit_reason = "CLOSED_WIN"
                    exit_price = trade["tp"]
            elif trade["direction"] == "SHORT":
                if bar_high >= active_sl:
                    exit_reason = "TRAILING_SL" if active_sl != trade["sl"] else "CLOSED_LOSS"
                    exit_price = active_sl
                elif bar_low <= trade["tp"]:
                    exit_reason = "CLOSED_WIN"
                    exit_price = trade["tp"]

            if exit_reason:
                closed = self.broker.close_trade(
                    trade["id"], exit_price, exit_reason, bar_time
                )
                if closed:
                    self._trade_counter += 1
                    pnl = closed.get("pnl_pct", 0)

                    # Log to journal
                    TradeLogger.log_exit(
                        trade_id=closed["id"],
                        ticker=ticker,
                        direction=closed["direction"],
                        exit_price=exit_price,
                        exit_reason=exit_reason,
                        pnl_pct=pnl,
                        cash_pnl=closed.get("cash_pnl", 0),
                        bars_held=bars_held,
                        regime_at_exit=closed.get("regime", "unknown"),
                        capital_after_exit=self.broker.capital,
                        setup_signals_at_entry=closed.get("setup_signals", []),
                    )

                    # Update RL bandit
                    if closed.get("setup_signals"):
                        self.learner.update_from_trade(
                            setup_signals=closed["setup_signals"],
                            regime=closed.get("regime", "unknown"),
                            pnl_pct=pnl,
                            is_win=pnl > 0,
                        )

                    self._log(
                        f"  [{exit_reason}] PnL: {pnl*100:+.2f}% | "
                        f"Capital: ₹{self.broker.capital:,.0f} | "
                        f"Trade #{self._trade_counter}"
                    )

    def _check_entry(
        self,
        visible_df: pd.DataFrame,
        ticker: str,
        current_price: float,
        bar_time: str,
        timeframe: str,
        asset_class: str,
    ) -> None:
        """Evaluate setups and potentially open a new trade."""
        # Use only the last 300 bars for setup evaluation (performance)
        eval_df = visible_df.iloc[-300:]

        try:
            regime, setups = self.engine.evaluate_all(eval_df, ticker)
        except Exception as e:
            return

        regime_str = regime.get("regime", "unknown")
        setup_weights = self.learner.get_setup_weights(regime_str)
        prediction = self.ai_brain.predict(regime, setups, setup_weights)

        signal = prediction.get("signal", "neutral")
        prob = prediction.get("probability", 0.0)

        if prob < self.MIN_AI_CONFIDENCE or signal not in ("bullish", "bearish"):
            return

        # Generate trade plan
        trade_plan = self.risk_engine.generate_trade_plan(
            ticker=ticker,
            direction=signal,
            ai_probability=prob,
            df=eval_df,
            capital=self.broker.capital,
            regime=regime_str,
            timeframe=timeframe,
            open_positions=[],
        )

        if not trade_plan.is_approved:
            return

        # Convert setup signals to serializable dicts
        setup_signals_list = [
            {"name": s.name, "signal": s.signal, "confidence": float(s.confidence)}
            for s in setups
        ]

        # Fill at current bar's close (next bar open would be more realistic,
        # but we're filling at close for simplicity in replay)
        trade_id = str(uuid.uuid4())[:12]
        direction = "LONG" if signal == "bullish" else "SHORT"

        new_trade = {
            "id": trade_id,
            "ticker": ticker,
            "underlying_ticker": ticker,
            "direction": direction,
            "quantity": trade_plan.position_size_qty,
            "invested": trade_plan.position_value,
            "entry_price": trade_plan.entry_price,
            "tp": trade_plan.take_profit,
            "sl": trade_plan.stop_loss,
            "trailing_stop": trade_plan.stop_loss,
            "atr_at_entry": trade_plan.atr_at_entry,
            "probability": prob,
            "risk_pct": trade_plan.risk_per_trade_pct,
            "risk_reward": trade_plan.risk_reward_ratio,
            "kelly_fraction": trade_plan.kelly_fraction,
            "probability_of_ruin": trade_plan.probability_of_ruin,
            "sl_method": trade_plan.sl_method,
            "tp_method": trade_plan.tp_method,
            "regime": regime_str,
            "max_hold_bars": trade_plan.max_hold_bars,
            "bars_held": 0,
            "status": "OPEN",
            "opened_at": bar_time,
            "setup_signals": setup_signals_list,
            "setup_weights": setup_weights,
        }

        self.broker.open_trade(new_trade)

        # Log to journal
        TradeLogger.log_entry(
            trade_id=trade_id,
            ticker=ticker,
            direction=direction,
            entry_price=trade_plan.entry_price,
            stop_loss=trade_plan.stop_loss,
            take_profit=trade_plan.take_profit,
            quantity=trade_plan.position_size_qty,
            invested=trade_plan.position_value,
            risk_pct=trade_plan.risk_per_trade_pct,
            risk_reward=trade_plan.risk_reward_ratio,
            ai_probability=prob,
            kelly_fraction=trade_plan.kelly_fraction,
            probability_of_ruin=trade_plan.probability_of_ruin,
            regime=regime_str,
            regime_adx=regime.get("adx", 0.0),
            sl_method=trade_plan.sl_method,
            tp_method=trade_plan.tp_method,
            timeframe=timeframe,
            atr_at_entry=trade_plan.atr_at_entry,
            setup_signals=setup_signals_list,
            setup_weights=setup_weights,
            config_version="replay_v1",
            capital_at_entry=self.broker.capital,
        )

    def _run_self_review(self) -> None:
        """The AI reviews its own trade journal and updates its beliefs."""
        self._log(f"🧠 Self-Review triggered at trade #{self._trade_counter}...")

        analyzer = JournalAnalyzer()
        report = analyzer.analyze()

        insights = report.get("insights", [])
        summary = report.get("summary", {})

        if insights:
            self._log(f"   Found {len(insights)} insight(s):")
            for insight in insights[:5]:  # Log top 5
                self._log(f"   → [{insight['severity']}] {insight['recommendation']}")

        # Apply insights to RL learner
        self.learner.batch_learn_from_journal()

        win_rate = summary.get("win_rate", 0)
        sharpe = summary.get("sharpe_ratio", 0)
        self._log(
            f"   Portfolio: Win Rate={win_rate*100:.1f}%, "
            f"Sharpe={sharpe:.2f}, "
            f"Capital=₹{self.broker.capital:,.0f}"
        )

    def _compile_results(
        self, ticker: str, timeframe: str, total_bars: int
    ) -> Dict[str, Any]:
        """Compile final replay statistics."""
        total_closed = len(self.broker.closed_trades)
        wins = sum(1 for t in self.broker.closed_trades if t.get("pnl_pct", 0) > 0)
        win_rate = wins / total_closed if total_closed > 0 else 0.0

        pnls = [t.get("pnl_pct", 0) for t in self.broker.closed_trades]
        avg_pnl = np.mean(pnls) if pnls else 0.0
        total_return = (
            (self.broker.capital - self.broker.starting_capital)
            / self.broker.starting_capital
            * 100
        )

        results = {
            "status": "complete",
            "ticker": ticker,
            "timeframe": timeframe,
            "total_bars": total_bars,
            "total_trades": total_closed,
            "wins": wins,
            "losses": total_closed - wins,
            "win_rate": round(win_rate * 100, 2),
            "avg_pnl_pct": round(float(avg_pnl * 100), 4),
            "total_return_pct": round(total_return, 2),
            "starting_capital": self.broker.starting_capital,
            "ending_capital": round(self.broker.capital, 2),
            "peak_capital": round(self.broker.peak_capital, 2),
            "max_drawdown_pct": round(self.broker.drawdown_pct * 100, 2),
            "rl_weights": self.learner.get_deterministic_weights(),
        }

        self._log("=" * 60)
        self._log("REPLAY COMPLETE")
        self._log(f"  Ticker: {ticker} | Bars: {total_bars}")
        self._log(f"  Trades: {total_closed} (W:{wins} / L:{total_closed - wins})")
        self._log(f"  Win Rate: {results['win_rate']}%")
        self._log(f"  Total Return: {results['total_return_pct']}%")
        self._log(f"  Capital: ₹{self.broker.starting_capital:,.0f} → ₹{self.broker.capital:,.0f}")
        self._log(f"  Max Drawdown: {results['max_drawdown_pct']}%")
        self._log("=" * 60)

        return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Historical Replay Engine")
    parser.add_argument("--ticker", default="^NSEI", help="Ticker to replay")
    parser.add_argument("--period", default="5y", help="Data period")
    parser.add_argument("--timeframe", default="1d", help="Candle interval")
    parser.add_argument("--capital", type=float, default=1_000_000.0, help="Starting capital")
    parser.add_argument(
        "--asset-class",
        default="IN_EQUITY",
        choices=["IN_EQUITY", "US_EQUITY", "CRYPTO"],
        help="Asset class",
    )
    args = parser.parse_args()

    engine = ReplayEngine(starting_capital=args.capital)
    results = engine.replay(
        ticker=args.ticker,
        period=args.period,
        timeframe=args.timeframe,
        asset_class=args.asset_class,
    )

    import json
    print("\n" + json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
