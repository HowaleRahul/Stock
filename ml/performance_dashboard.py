"""
Performance Dashboard — Phase 7: Rolling statistics per setup, per regime.

Computes:
- Rolling win-rate per setup
- Average R:R per setup
- Sharpe ratio per setup
- Per-regime performance breakdown
- Equity curve statistics
"""

from __future__ import annotations

import logging
import math
from typing import Dict, Any, List, Optional
from collections import defaultdict

import numpy as np

from ml.trade_logger import TradeLogger

logger = logging.getLogger("trading.dashboard")


class PerformanceDashboard:
    """
    Analyzes the trade journal to produce real-time performance metrics.
    
    All metrics are computed from actual paper-trade outcomes, not backtests.
    This is the system's ground truth.
    """

    def __init__(self):
        self._entries = TradeLogger.get_all_entries()
        self._exits = TradeLogger.get_all_exits()
        self._entry_map = {e["trade_id"]: e for e in self._entries}

    def refresh(self):
        """Reload data from the journal."""
        self._entries = TradeLogger.get_all_entries()
        self._exits = TradeLogger.get_all_exits()
        self._entry_map = {e["trade_id"]: e for e in self._entries}

    # -------------------------------------------------------------------
    # Overall Portfolio Stats
    # -------------------------------------------------------------------

    def portfolio_summary(self) -> Dict[str, Any]:
        """Overall portfolio performance summary."""
        if not self._exits:
            return {"total_trades": 0, "message": "No closed trades yet."}

        total = len(self._exits)
        wins = [e for e in self._exits if e.get("pnl_pct", 0) > 0]
        losses = [e for e in self._exits if e.get("pnl_pct", 0) <= 0]

        win_rate = len(wins) / total if total > 0 else 0.0
        pnl_list = [e.get("pnl_pct", 0) for e in self._exits]
        cash_pnl_list = [e.get("cash_pnl", 0) for e in self._exits]

        avg_win = float(np.mean([e["pnl_pct"] for e in wins])) if wins else 0.0
        avg_loss = float(np.mean([abs(e["pnl_pct"]) for e in losses])) if losses else 0.0
        avg_rr = avg_win / avg_loss if avg_loss > 0 else 0.0

        # Sharpe Ratio (annualized, assuming 252 trading days)
        if len(pnl_list) >= 2:
            pnl_arr = np.array(pnl_list)
            sharpe = float(np.mean(pnl_arr) / np.std(pnl_arr) * np.sqrt(252)) if np.std(pnl_arr) > 0 else 0.0
        else:
            sharpe = 0.0

        # Max consecutive losses
        max_consec_loss = 0
        current_streak = 0
        for p in pnl_list:
            if p <= 0:
                current_streak += 1
                max_consec_loss = max(max_consec_loss, current_streak)
            else:
                current_streak = 0

        # Profit Factor
        gross_profit = sum(e["cash_pnl"] for e in wins) if wins else 0.0
        gross_loss = sum(abs(e["cash_pnl"]) for e in losses) if losses else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        return {
            "total_trades": total,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate, 4),
            "avg_win_pct": round(avg_win * 100, 4),
            "avg_loss_pct": round(avg_loss * 100, 4),
            "avg_rr": round(avg_rr, 2),
            "sharpe_ratio": round(sharpe, 4),
            "profit_factor": round(profit_factor, 4),
            "total_cash_pnl": round(sum(cash_pnl_list), 2),
            "max_consecutive_losses": max_consec_loss,
        }

    # -------------------------------------------------------------------
    # Per-Setup Performance
    # -------------------------------------------------------------------

    def per_setup_performance(self) -> Dict[str, Dict[str, Any]]:
        """
        Break down performance by which setups fired at entry time.
        
        For each setup, computes:
        - Win rate when this setup was bullish/bearish
        - Average R:R
        - Contribution to overall P&L (Sharpe)
        """
        setup_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl_list": [], "rr_list": []})

        for exit_rec in self._exits:
            trade_id = exit_rec.get("trade_id")
            entry_rec = self._entry_map.get(trade_id, {})
            setup_signals = entry_rec.get("setup_signals", [])

            pnl = exit_rec.get("pnl_pct", 0)
            is_win = pnl > 0

            for setup in setup_signals:
                name = setup.get("name", "Unknown")
                signal = setup.get("signal", "neutral")
                conf = setup.get("confidence", 0)

                # Only count setups that actually fired (non-neutral with confidence)
                if signal == "neutral" or conf <= 0:
                    continue

                stats = setup_stats[name]
                if is_win:
                    stats["wins"] += 1
                else:
                    stats["losses"] += 1
                stats["pnl_list"].append(pnl)

        result = {}
        for name, stats in setup_stats.items():
            total = stats["wins"] + stats["losses"]
            pnl_arr = np.array(stats["pnl_list"]) if stats["pnl_list"] else np.array([0.0])

            win_rate = stats["wins"] / total if total > 0 else 0.0
            avg_pnl = float(np.mean(pnl_arr))
            sharpe = float(np.mean(pnl_arr) / np.std(pnl_arr) * np.sqrt(252)) if len(pnl_arr) >= 2 and np.std(pnl_arr) > 0 else 0.0

            result[name] = {
                "total_trades": total,
                "wins": stats["wins"],
                "losses": stats["losses"],
                "win_rate": round(win_rate, 4),
                "avg_pnl_pct": round(avg_pnl * 100, 4),
                "sharpe": round(sharpe, 4),
            }

        return dict(sorted(result.items(), key=lambda x: x[1]["sharpe"], reverse=True))

    # -------------------------------------------------------------------
    # Per-Regime Performance
    # -------------------------------------------------------------------

    def per_regime_performance(self) -> Dict[str, Dict[str, Any]]:
        """Break down performance by market regime at entry time."""
        regime_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl_list": []})

        for exit_rec in self._exits:
            trade_id = exit_rec.get("trade_id")
            entry_rec = self._entry_map.get(trade_id, {})
            regime = entry_rec.get("regime", "unknown")

            pnl = exit_rec.get("pnl_pct", 0)
            is_win = pnl > 0

            stats = regime_stats[regime]
            if is_win:
                stats["wins"] += 1
            else:
                stats["losses"] += 1
            stats["pnl_list"].append(pnl)

        result = {}
        for regime, stats in regime_stats.items():
            total = stats["wins"] + stats["losses"]
            pnl_arr = np.array(stats["pnl_list"]) if stats["pnl_list"] else np.array([0.0])
            win_rate = stats["wins"] / total if total > 0 else 0.0

            result[regime] = {
                "total_trades": total,
                "wins": stats["wins"],
                "losses": stats["losses"],
                "win_rate": round(win_rate, 4),
                "avg_pnl_pct": round(float(np.mean(pnl_arr)) * 100, 4),
                "total_pnl_pct": round(float(np.sum(pnl_arr)) * 100, 4),
            }

        return result

    # -------------------------------------------------------------------
    # Rolling Win Rate (last N trades)
    # -------------------------------------------------------------------

    def rolling_win_rate(self, window: int = 20) -> List[float]:
        """Calculate rolling win rate over the last N trades."""
        if len(self._exits) < window:
            return []

        pnl_list = [1 if e.get("pnl_pct", 0) > 0 else 0 for e in self._exits]
        rolling = []
        for i in range(window, len(pnl_list) + 1):
            w = pnl_list[i - window:i]
            rolling.append(sum(w) / window)
        return rolling

    # -------------------------------------------------------------------
    # Full Report (for display)
    # -------------------------------------------------------------------

    def generate_report(self) -> str:
        """Generate a human-readable performance report."""
        summary = self.portfolio_summary()

        if summary.get("total_trades", 0) == 0:
            return "No closed trades yet. The system is waiting for trade outcomes to build performance data."

        lines = [
            "=" * 60,
            "PERFORMANCE DASHBOARD",
            "=" * 60,
            "",
            "--- PORTFOLIO SUMMARY ---",
            f"  Total Trades:           {summary['total_trades']}",
            f"  Wins / Losses:          {summary['wins']} / {summary['losses']}",
            f"  Win Rate:               {summary['win_rate']*100:.1f}%",
            f"  Avg Win:                {summary['avg_win_pct']:+.2f}%",
            f"  Avg Loss:               {summary['avg_loss_pct']:+.2f}%",
            f"  Avg R:R:                {summary['avg_rr']:.2f}:1",
            f"  Sharpe Ratio:           {summary['sharpe_ratio']:.2f}",
            f"  Profit Factor:          {summary['profit_factor']:.2f}",
            f"  Total Cash P&L:         {summary['total_cash_pnl']:+,.2f}",
            f"  Max Consec. Losses:     {summary['max_consecutive_losses']}",
            "",
        ]

        # Per-setup breakdown
        setup_perf = self.per_setup_performance()
        if setup_perf:
            lines.append("--- PER-SETUP PERFORMANCE (Ranked by Sharpe) ---")
            for name, stats in setup_perf.items():
                lines.append(
                    f"  {name:25s} | Trades: {stats['total_trades']:3d} | "
                    f"WR: {stats['win_rate']*100:5.1f}% | "
                    f"Avg PnL: {stats['avg_pnl_pct']:+.2f}% | "
                    f"Sharpe: {stats['sharpe']:+.2f}"
                )
            lines.append("")

        # Per-regime breakdown
        regime_perf = self.per_regime_performance()
        if regime_perf:
            lines.append("--- PER-REGIME PERFORMANCE ---")
            for regime, stats in regime_perf.items():
                lines.append(
                    f"  {regime:20s} | Trades: {stats['total_trades']:3d} | "
                    f"WR: {stats['win_rate']*100:5.1f}% | "
                    f"Avg PnL: {stats['avg_pnl_pct']:+.2f}% | "
                    f"Total PnL: {stats['total_pnl_pct']:+.2f}%"
                )
            lines.append("")

        lines.append("=" * 60)
        return "\n".join(lines)
