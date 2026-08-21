"""
Journal Analyzer — RL Self-Play Phase B.

Reads the trade journal and performs meta-pattern detection to produce
actionable insights that the ReinforcementLearner can use to update
setup weights, suppress failing strategies, and recalibrate risk sizing.

This is the "brain review" step — the AI reviewing its own trading journal
to learn from its mistakes, exactly like a human trader reviews their P&L.
"""

from __future__ import annotations

import logging
import math
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict

import numpy as np

from ml.trade_logger import TradeLogger

logger = logging.getLogger("trading.journal_analyzer")


class JournalInsight:
    """A single actionable recommendation from the journal analysis."""

    def __init__(
        self,
        insight_type: str,
        severity: str,
        setup_name: str,
        regime: str,
        metric_name: str,
        metric_value: float,
        recommendation: str,
        action: str = "suppress",
        action_value: float = 0.5,
    ):
        self.insight_type = insight_type  # "setup_failure", "risk_calibration", "time_pattern"
        self.severity = severity          # "critical", "warning", "info"
        self.setup_name = setup_name
        self.regime = regime
        self.metric_name = metric_name
        self.metric_value = metric_value
        self.recommendation = recommendation
        self.action = action              # "suppress", "boost", "adjust_risk"
        self.action_value = action_value  # multiplier or new value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.insight_type,
            "severity": self.severity,
            "setup": self.setup_name,
            "regime": self.regime,
            "metric": self.metric_name,
            "value": round(self.metric_value, 4),
            "recommendation": self.recommendation,
            "action": self.action,
            "action_value": round(self.action_value, 4),
        }

    def __repr__(self):
        return f"[{self.severity.upper()}] {self.recommendation}"


class JournalAnalyzer:
    """
    Analyzes the trade journal to detect meta-patterns and produce insights.

    Key analyses:
    1. Setup x Regime Profitability Matrix
    2. Failure Pattern Detection (systematic losers)
    3. Position Sizing Calibration (Kelly accuracy check)
    4. Time-Based Patterns (session performance)
    5. Consecutive Loss Streak Detection
    """

    # Thresholds
    MIN_TRADES_FOR_ANALYSIS = 10
    WIN_RATE_SUPPRESS_THRESHOLD = 0.40   # Below 40% → suppress
    WIN_RATE_BOOST_THRESHOLD = 0.70      # Above 70% → boost
    MAX_CONSECUTIVE_LOSSES = 5
    RUIN_PROBABILITY_THRESHOLD = 0.05    # 5%
    MIN_RISK_REWARD_THRESHOLD = 1.0

    def __init__(self):
        self._entries = TradeLogger.get_all_entries()
        self._exits = TradeLogger.get_all_exits()
        self._entry_map = {e["trade_id"]: e for e in self._entries}

    def analyze(self) -> Dict[str, Any]:
        """
        Run all analyses and return a comprehensive report.

        Returns:
            Dict with keys: "insights", "profitability_matrix", "summary"
        """
        insights: List[JournalInsight] = []

        # Build the profitability matrix
        matrix = self._build_profitability_matrix()

        # Detect failure patterns
        insights.extend(self._detect_failure_patterns(matrix))

        # Check position sizing calibration
        insights.extend(self._check_risk_calibration())

        # Detect consecutive loss streaks
        insights.extend(self._detect_loss_streaks())

        # Time-based patterns
        insights.extend(self._detect_time_patterns())

        # Summary stats
        summary = self._compute_summary()

        logger.info(
            f"[JournalAnalyzer] Analysis complete. "
            f"Total trades: {summary.get('total_trades', 0)}, "
            f"Insights generated: {len(insights)}"
        )

        return {
            "insights": [i.to_dict() for i in insights],
            "profitability_matrix": matrix,
            "summary": summary,
        }

    # ------------------------------------------------------------------
    # 1. Setup x Regime Profitability Matrix
    # ------------------------------------------------------------------

    def _build_profitability_matrix(self) -> Dict[str, Dict[str, Dict[str, float]]]:
        """
        For each (setup, regime) pair, compute:
        - win_rate, avg_pnl, sharpe, avg_bars_held, trade_count
        """
        # Group trades by (setup, regime)
        buckets: Dict[str, Dict[str, List[float]]] = defaultdict(
            lambda: defaultdict(list)
        )
        bars_buckets: Dict[str, Dict[str, List[int]]] = defaultdict(
            lambda: defaultdict(list)
        )

        for exit_rec in self._exits:
            trade_id = exit_rec.get("trade_id")
            entry_rec = self._entry_map.get(trade_id, {})
            regime = entry_rec.get("regime", "unknown")
            pnl = exit_rec.get("pnl_pct", 0)
            bars = exit_rec.get("bars_held", 0)

            setup_signals = entry_rec.get("setup_signals", [])
            for sig in setup_signals:
                name = sig.get("name", "")
                signal = sig.get("signal", "neutral")
                if signal != "neutral" and name:
                    buckets[name][regime].append(pnl)
                    bars_buckets[name][regime].append(bars)

        # Compute metrics
        matrix = {}
        for setup_name, regimes in buckets.items():
            matrix[setup_name] = {}
            for regime, pnl_list in regimes.items():
                n = len(pnl_list)
                if n == 0:
                    continue

                wins = sum(1 for p in pnl_list if p > 0)
                win_rate = wins / n
                avg_pnl = np.mean(pnl_list)
                std_pnl = np.std(pnl_list) if n > 1 else 1.0
                sharpe = (avg_pnl / std_pnl) if std_pnl > 0 else 0.0
                avg_bars = np.mean(bars_buckets[setup_name][regime]) if bars_buckets[setup_name][regime] else 0

                matrix[setup_name][regime] = {
                    "win_rate": round(win_rate, 4),
                    "avg_pnl": round(float(avg_pnl), 6),
                    "sharpe": round(float(sharpe), 4),
                    "avg_bars_held": round(float(avg_bars), 1),
                    "trade_count": n,
                }

        return matrix

    # ------------------------------------------------------------------
    # 2. Failure Pattern Detection
    # ------------------------------------------------------------------

    def _detect_failure_patterns(
        self, matrix: Dict[str, Dict[str, Dict[str, float]]]
    ) -> List[JournalInsight]:
        """Identify setups that are systematically losing money in specific regimes."""
        insights = []

        for setup_name, regimes in matrix.items():
            for regime, stats in regimes.items():
                n = stats["trade_count"]
                if n < self.MIN_TRADES_FOR_ANALYSIS:
                    continue

                win_rate = stats["win_rate"]

                # Critical: win rate below suppression threshold
                if win_rate < self.WIN_RATE_SUPPRESS_THRESHOLD:
                    insights.append(
                        JournalInsight(
                            insight_type="setup_failure",
                            severity="critical",
                            setup_name=setup_name,
                            regime=regime,
                            metric_name="win_rate",
                            metric_value=win_rate,
                            recommendation=(
                                f"{setup_name} has only {win_rate*100:.0f}% win rate "
                                f"in '{regime}' regime ({n} trades). "
                                f"Suppress confidence by 70%."
                            ),
                            action="suppress",
                            action_value=0.3,  # multiply confidence by 0.3
                        )
                    )
                # Info: excellent win rate → boost
                elif win_rate > self.WIN_RATE_BOOST_THRESHOLD:
                    insights.append(
                        JournalInsight(
                            insight_type="setup_boost",
                            severity="info",
                            setup_name=setup_name,
                            regime=regime,
                            metric_name="win_rate",
                            metric_value=win_rate,
                            recommendation=(
                                f"{setup_name} has {win_rate*100:.0f}% win rate "
                                f"in '{regime}' regime ({n} trades). Boosting weight."
                            ),
                            action="boost",
                            action_value=1.3,  # multiply confidence by 1.3
                        )
                    )

                # Check average PnL — high win rate but negative avg PnL means
                # the wins are too small relative to losses
                avg_pnl = stats["avg_pnl"]
                if win_rate > 0.50 and avg_pnl < 0:
                    insights.append(
                        JournalInsight(
                            insight_type="risk_mismatch",
                            severity="warning",
                            setup_name=setup_name,
                            regime=regime,
                            metric_name="avg_pnl",
                            metric_value=avg_pnl,
                            recommendation=(
                                f"{setup_name} wins {win_rate*100:.0f}% of trades "
                                f"in '{regime}' but avg PnL is {avg_pnl*100:.2f}%. "
                                f"Stop-losses are too wide relative to take-profits."
                            ),
                            action="adjust_risk",
                            action_value=0.0,  # signal to tighten SL
                        )
                    )

        return insights

    # ------------------------------------------------------------------
    # 3. Risk Calibration Check
    # ------------------------------------------------------------------

    def _check_risk_calibration(self) -> List[JournalInsight]:
        """Check if position sizing and Kelly fraction are well-calibrated."""
        insights = []

        if len(self._exits) < self.MIN_TRADES_FOR_ANALYSIS:
            return insights

        pnl_list = [e.get("pnl_pct", 0) for e in self._exits]
        wins = [p for p in pnl_list if p > 0]
        losses = [p for p in pnl_list if p <= 0]

        if not wins or not losses:
            return insights

        avg_win = np.mean(wins)
        avg_loss = abs(np.mean(losses))

        # Check if average loss exceeds average win (bad R:R despite possible high win rate)
        if avg_loss > 0 and avg_win > 0:
            actual_rr = avg_win / avg_loss
            if actual_rr < self.MIN_RISK_REWARD_THRESHOLD:
                insights.append(
                    JournalInsight(
                        insight_type="risk_calibration",
                        severity="warning",
                        setup_name="PORTFOLIO",
                        regime="all",
                        metric_name="actual_risk_reward",
                        metric_value=actual_rr,
                        recommendation=(
                            f"Actual R:R is {actual_rr:.2f}:1 "
                            f"(avg win: {avg_win*100:.2f}%, avg loss: {avg_loss*100:.2f}%). "
                            f"Either tighten stop-losses or widen take-profit targets."
                        ),
                        action="adjust_risk",
                        action_value=actual_rr,
                    )
                )

        # Check probability of ruin from entries
        ruin_probs = [
            e.get("probability_of_ruin", 0) for e in self._entries
            if e.get("probability_of_ruin", 0) > 0
        ]
        if ruin_probs:
            avg_ruin = np.mean(ruin_probs)
            if avg_ruin > self.RUIN_PROBABILITY_THRESHOLD:
                insights.append(
                    JournalInsight(
                        insight_type="risk_calibration",
                        severity="critical",
                        setup_name="PORTFOLIO",
                        regime="all",
                        metric_name="avg_probability_of_ruin",
                        metric_value=avg_ruin,
                        recommendation=(
                            f"Average probability of ruin is {avg_ruin*100:.2f}%, "
                            f"exceeding the {self.RUIN_PROBABILITY_THRESHOLD*100}% threshold. "
                            f"Reduce risk_per_trade from 2% to 1%."
                        ),
                        action="adjust_risk",
                        action_value=0.01,  # new risk_per_trade value
                    )
                )

        return insights

    # ------------------------------------------------------------------
    # 4. Consecutive Loss Streak Detection
    # ------------------------------------------------------------------

    def _detect_loss_streaks(self) -> List[JournalInsight]:
        """Detect dangerous consecutive loss streaks."""
        insights = []

        if len(self._exits) < 5:
            return insights

        # Sort exits by timestamp
        sorted_exits = sorted(self._exits, key=lambda x: x.get("timestamp", ""))

        max_streak = 0
        current_streak = 0
        for exit_rec in sorted_exits:
            if exit_rec.get("pnl_pct", 0) <= 0:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0

        if max_streak >= self.MAX_CONSECUTIVE_LOSSES:
            insights.append(
                JournalInsight(
                    insight_type="loss_streak",
                    severity="critical",
                    setup_name="PORTFOLIO",
                    regime="all",
                    metric_name="max_consecutive_losses",
                    metric_value=float(max_streak),
                    recommendation=(
                        f"Detected {max_streak} consecutive losses. "
                        f"Recommend reducing position size by 50% until "
                        f"the next 3 trades are winners."
                    ),
                    action="adjust_risk",
                    action_value=0.5,  # halve position size
                )
            )

        return insights

    # ------------------------------------------------------------------
    # 5. Time-Based Patterns
    # ------------------------------------------------------------------

    def _detect_time_patterns(self) -> List[JournalInsight]:
        """Detect performance differences by time of day or day of week."""
        insights = []

        if len(self._exits) < 20:
            return insights

        # Group by day of week from entry timestamp
        day_buckets: Dict[str, List[float]] = defaultdict(list)

        for exit_rec in self._exits:
            trade_id = exit_rec.get("trade_id")
            entry_rec = self._entry_map.get(trade_id, {})
            ts_str = entry_rec.get("timestamp", "")
            pnl = exit_rec.get("pnl_pct", 0)

            if ts_str:
                try:
                    from datetime import datetime
                    ts = datetime.fromisoformat(ts_str)
                    day_name = ts.strftime("%A")
                    day_buckets[day_name].append(pnl)
                except (ValueError, TypeError):
                    pass

        # Find best and worst days
        day_stats = {}
        for day, pnls in day_buckets.items():
            if len(pnls) >= 5:
                wins = sum(1 for p in pnls if p > 0)
                day_stats[day] = {
                    "win_rate": wins / len(pnls),
                    "avg_pnl": np.mean(pnls),
                    "count": len(pnls),
                }

        if len(day_stats) >= 3:
            worst_day = min(day_stats, key=lambda d: day_stats[d]["win_rate"])
            best_day = max(day_stats, key=lambda d: day_stats[d]["win_rate"])

            ws = day_stats[worst_day]
            bs = day_stats[best_day]

            if ws["win_rate"] < 0.35 and ws["count"] >= 5:
                insights.append(
                    JournalInsight(
                        insight_type="time_pattern",
                        severity="warning",
                        setup_name="PORTFOLIO",
                        regime="all",
                        metric_name=f"{worst_day}_win_rate",
                        metric_value=ws["win_rate"],
                        recommendation=(
                            f"Worst trading day: {worst_day} "
                            f"({ws['win_rate']*100:.0f}% win rate, {ws['count']} trades). "
                            f"Consider reducing position sizes on {worst_day}s."
                        ),
                        action="suppress",
                        action_value=0.7,
                    )
                )

            if bs["win_rate"] > 0.70 and bs["count"] >= 5:
                insights.append(
                    JournalInsight(
                        insight_type="time_pattern",
                        severity="info",
                        setup_name="PORTFOLIO",
                        regime="all",
                        metric_name=f"{best_day}_win_rate",
                        metric_value=bs["win_rate"],
                        recommendation=(
                            f"Best trading day: {best_day} "
                            f"({bs['win_rate']*100:.0f}% win rate, {bs['count']} trades). "
                            f"Consider increasing position sizes on {best_day}s."
                        ),
                        action="boost",
                        action_value=1.2,
                    )
                )

        return insights

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def _compute_summary(self) -> Dict[str, Any]:
        """Overall portfolio summary from the journal."""
        if not self._exits:
            return {"total_trades": 0, "message": "No closed trades yet."}

        total = len(self._exits)
        pnls = [e.get("pnl_pct", 0) for e in self._exits]
        wins = sum(1 for p in pnls if p > 0)
        cash_pnls = [e.get("cash_pnl", 0) for e in self._exits]

        win_rate = wins / total if total > 0 else 0.0
        total_cash_pnl = sum(cash_pnls)
        avg_pnl = np.mean(pnls)
        std_pnl = np.std(pnls) if total > 1 else 1.0
        sharpe = (avg_pnl / std_pnl) if std_pnl > 0 else 0.0

        # Max drawdown from capital curve
        capitals = [e.get("capital_after_exit", 0) for e in self._exits if e.get("capital_after_exit")]
        max_dd = 0.0
        if capitals:
            peak = capitals[0]
            for c in capitals:
                if c > peak:
                    peak = c
                dd = (peak - c) / peak if peak > 0 else 0
                if dd > max_dd:
                    max_dd = dd

        return {
            "total_trades": total,
            "win_rate": round(win_rate, 4),
            "total_cash_pnl": round(total_cash_pnl, 2),
            "avg_pnl_pct": round(float(avg_pnl * 100), 4),
            "sharpe_ratio": round(float(sharpe), 4),
            "max_drawdown_pct": round(float(max_dd * 100), 2),
        }
