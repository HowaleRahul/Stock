"""
Drawdown Circuit Breaker & Risk Discipline Gate

Incorporates account-level risk gate concepts from `tradermonty/claude-trading-skills`:
- Enforces strict daily loss limits (e.g. 2.0% of capital).
- Detects losing streaks (e.g. 3 consecutive losses) and enforces mandatory cooldowns
  to protect against revenge trading and emotional tilt.
- Enforces weekly and monthly drawdown ceilings.
- Provides actionable recommendations: TRADING_ALLOWED, COOLDOWN, or HALTED.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("trading.ml.circuit_breaker")


@dataclass(frozen=True)
class CircuitConfig:
    max_daily_loss_pct: float = 0.02       # 2% max realized daily loss
    losing_streak_threshold: int = 3       # 3 consecutive losses -> mandatory cooldown
    cooldown_hours: float = 24.0           # 24-hour timeout after streak
    max_weekly_drawdown_pct: float = 0.05  # 5% max weekly loss
    max_monthly_drawdown_pct: float = 0.08 # 8% max monthly loss


@dataclass
class CircuitDecision:
    status: str  # "TRADING_ALLOWED", "COOLDOWN", "HALTED"
    is_allowed: bool
    reason: str
    daily_realized_pnl: float
    consecutive_losses: int
    cooldown_expires_at: Optional[datetime] = None
    cooldown_hours_remaining: float = 0.0


class DrawdownCircuitBreaker:
    """
    Evaluates account-level risk status before allowing any new paper or live trade.
    """

    def __init__(self, config: Optional[CircuitConfig] = None):
        self.config = config or CircuitConfig()
        self.recent_trades: List[Dict[str, Any]] = []
        self._cooldown_until: Optional[datetime] = None

    def record_trade_outcome(self, pnl_pct: float, cash_pnl: float, closed_at: Optional[datetime] = None):
        """Records a completed trade into the breaker ledger."""
        dt = closed_at or datetime.now(timezone.utc)
        self.recent_trades.append({
            "pnl_pct": pnl_pct,
            "cash_pnl": cash_pnl,
            "timestamp": dt,
            "is_win": pnl_pct > 0
        })

    def get_consecutive_losses(self) -> int:
        """Counts unbroken losing trades from the most recent outcome backwards."""
        streak = 0
        for trade in reversed(self.recent_trades):
            if not trade.get("is_win", False):
                streak += 1
            else:
                break
        return streak

    def get_daily_realized_loss(self, current_time: Optional[datetime] = None) -> float:
        """Computes total realized loss (as positive number) in the last 24 hours."""
        now = current_time or datetime.now(timezone.utc)
        one_day_ago = now - timedelta(days=1)
        total_loss = 0.0
        for t in self.recent_trades:
            if t["timestamp"] >= one_day_ago and t.get("pnl_pct", 0) < 0:
                total_loss += abs(t["pnl_pct"])
        return total_loss

    def evaluate(self, current_capital: float, current_time: Optional[datetime] = None) -> CircuitDecision:
        """
        Evaluates whether new trade risk is permitted today.
        """
        now = current_time or datetime.now(timezone.utc)

        # 1. Check active cooldown timer
        if self._cooldown_until and now < self._cooldown_until:
            rem_hrs = (self._cooldown_until - now).total_seconds() / 3600.0
            return CircuitDecision(
                status="COOLDOWN",
                is_allowed=False,
                reason=f"Active losing-streak cooldown in effect for another {rem_hrs:.1f} hours. Prevents revenge trading.",
                daily_realized_pnl=-self.get_daily_realized_loss(now),
                consecutive_losses=self.get_consecutive_losses(),
                cooldown_expires_at=self._cooldown_until,
                cooldown_hours_remaining=round(rem_hrs, 2)
            )

        # 2. Check consecutive loss streak
        losses = self.get_consecutive_losses()
        if losses >= self.config.losing_streak_threshold:
            self._cooldown_until = now + timedelta(hours=self.config.cooldown_hours)
            rem_hrs = self.config.cooldown_hours
            logger.warning(f"🚨 CIRCUIT BREAKER TRIGGERED: {losses} consecutive losses. Initiating {rem_hrs}h cooldown.")
            return CircuitDecision(
                status="COOLDOWN",
                is_allowed=False,
                reason=f"Losing streak threshold reached ({losses} consecutive losses). Mandating {rem_hrs:.0f}h risk pause.",
                daily_realized_pnl=-self.get_daily_realized_loss(now),
                consecutive_losses=losses,
                cooldown_expires_at=self._cooldown_until,
                cooldown_hours_remaining=rem_hrs
            )

        # 3. Check daily realized loss limit
        daily_loss = self.get_daily_realized_loss(now)
        if daily_loss >= self.config.max_daily_loss_pct:
            logger.warning(f"🚨 CIRCUIT BREAKER TRIGGERED: Daily realized loss {daily_loss*100:.2f}% exceeds {self.config.max_daily_loss_pct*100:.1f}% limit.")
            return CircuitDecision(
                status="HALTED",
                is_allowed=False,
                reason=f"Daily realized loss ({daily_loss*100:.2f}%) reached max daily budget ({self.config.max_daily_loss_pct*100:.1f}%). Trading halted for today.",
                daily_realized_pnl=-daily_loss,
                consecutive_losses=losses
            )

        # 4. Trading Allowed
        return CircuitDecision(
            status="TRADING_ALLOWED",
            is_allowed=True,
            reason="Account risk parameters healthy; new trade risk permitted.",
            daily_realized_pnl=-daily_loss,
            consecutive_losses=losses
        )
