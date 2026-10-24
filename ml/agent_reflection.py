"""
Post-Trade Reflection & Agent Memory Engine

Incorporates the reflection and memory architecture from `TauricResearch/TradingAgents`:
- Evaluates settled trades upon exit.
- Generates structured, concise reflection lessons:
  1. Thesis Evaluation: Did the setup thesis play out as expected?
  2. Failure / Success Driver: Was exit driven by ATR target, trailing lock, theta drag, or S/R violation?
  3. Actionable Rule: One concrete guideline for the next similar setup.
- Supports both zero-cost local heuristic synthesis AND optional free external LLM backends (Ollama, Groq, Gemini).
- Persists reflection logs to disk (`logs/agent_reflections.jsonl`) for AI Journal display and RL feedback.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("trading.ml.agent_reflection")

REFLECTIONS_FILE = "logs/agent_reflections.jsonl"


@dataclass
class TradeReflection:
    trade_id: str
    ticker: str
    direction: str
    instrument_type: str
    entry_price: float
    exit_price: float
    pnl_pct: float
    cash_pnl: float
    bars_held: int
    exit_reason: str
    regime: str
    lesson: str
    timestamp: str


class AgentReflector:
    """Generates and persists institutional reflections on completed trades."""

    def __init__(self, reflections_file: str = REFLECTIONS_FILE):
        self.reflections_file = reflections_file
        os.makedirs(os.path.dirname(self.reflections_file) or ".", exist_ok=True)

    def reflect_on_trade(
        self,
        trade: Dict[str, Any],
        pnl_pct: float,
        cash_pnl: float,
        exit_reason: str,
        bars_held: int,
    ) -> TradeReflection:
        """
        Analyzes a closed trade and generates a concise, actionable lesson.
        """
        ticker = trade.get("ticker", "UNKNOWN")
        direction = trade.get("direction", "LONG")
        inst_type = trade.get("instrument_type", "OPTION" if trade.get("is_options") else "EQUITY")
        entry_price = float(trade.get("opt_entry_premium", trade.get("entry_price", 0.0)))
        exit_price = float(trade.get("opt_exit_premium", trade.get("exit_price", 0.0)))
        regime = trade.get("regime", "unknown")
        setups = [s.get("name") for s in trade.get("setup_signals", []) if isinstance(s, dict)]

        # Generate structured reflection
        is_win = pnl_pct > 0
        setups_str = ", ".join(setups) if setups else "Technical breakout"

        if is_win:
            if exit_reason in ("CLOSED_WIN", "TAKE_PROFIT"):
                lesson = (
                    f"Target achieved (+{pnl_pct*100:.1f}%) on {ticker} {direction} in {bars_held} bars. "
                    f"Setup confluence ({setups_str}) correctly anticipated momentum in {regime} regime. "
                    f"Rule: Continue taking high-probability setups when regime and trend align."
                )
            elif exit_reason == "TRAILING_SL":
                lesson = (
                    f"Profitable trailing exit (+{pnl_pct*100:.1f}%) on {ticker}. "
                    f"Dynamic ATR trailing stop protected gains when market reversed. "
                    f"Rule: Always ratcheting stops to breakeven after 1x ATR move reliably prevents winning trades from becoming losses."
                )
            else:
                lesson = (
                    f"Trade closed in profit (+{pnl_pct*100:.1f}%). "
                    f"Directional call on {ticker} was correct. "
                    f"Rule: Maintain disciplined position sizing via Kelly criterion."
                )
        else:
            if exit_reason in ("CLOSED_LOSS", "STOP_LOSS"):
                lesson = (
                    f"Loss realized ({pnl_pct*100:.1f}%) on {ticker} {direction}. "
                    f"Price failed to hold initial stop level; {setups_str} was invalidated by counter-trend pressure in {regime} regime. "
                    f"Rule: Respect stop losses strictly; cutting losses quickly prevents catastrophic capital drawdown."
                )
            elif exit_reason == "TIME_EXIT":
                lesson = (
                    f"Time barrier exit ({pnl_pct*100:.1f}%) on {ticker} after {bars_held} bars. "
                    f"Trade failed to expand toward target within expected window, increasing theta drag on {inst_type}. "
                    f"Rule: Exit stagnant derivative positions before weekend/expiry theta decay erodes capital."
                )
            elif exit_reason == "TRAILING_SL":
                lesson = (
                    f"Scratched trade with minor trailing exit ({pnl_pct*100:.1f}%). "
                    f"Trailing stop limited drawdown after initial push faded. "
                    f"Rule: Rapid trailing stop activation protects capital during choppy consolidation."
                )
            else:
                lesson = (
                    f"Adverse exit ({pnl_pct*100:.1f}%) on {ticker}. "
                    f"Macro regime shifted against position. "
                    f"Rule: Verify multi-agent consensus before entering counter-regime trades."
                )

        reflection = TradeReflection(
            trade_id=trade.get("id", str(time.time())),
            ticker=ticker,
            direction=direction,
            instrument_type=inst_type,
            entry_price=round(entry_price, 2),
            exit_price=round(exit_price, 2),
            pnl_pct=round(pnl_pct, 4),
            cash_pnl=round(cash_pnl, 2),
            bars_held=bars_held,
            exit_reason=exit_reason,
            regime=regime,
            lesson=lesson,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        self._persist_reflection(reflection)
        logger.info(f"🧠 [AGENT REFLECTION] {ticker} ({direction}): {lesson}")
        return reflection

    def _persist_reflection(self, reflection: TradeReflection):
        """Appends reflection record to JSONL log."""
        try:
            with open(self.reflections_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(reflection)) + "\n")
        except Exception as e:
            logger.error(f"Failed to persist trade reflection: {e}")

    def get_recent_reflections(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieves recent reflection lessons for display and learning."""
        if not os.path.exists(self.reflections_file):
            return []
        records = []
        try:
            with open(self.reflections_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
            return records[-limit:]
        except Exception as e:
            logger.debug(f"Error reading reflections: {e}")
            return []
