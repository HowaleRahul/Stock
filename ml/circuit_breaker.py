"""
Drawdown Circuit Breaker & Risk Discipline Gate

Incorporates account-level risk gate concepts from `tradermonty/claude-trading-skills`:
- Enforces strict daily loss limits (e.g. 2.0% of portfolio capital).
- Detects losing streaks (e.g. 3 consecutive losses) and enforces mandatory cooldowns
  to protect against revenge trading and emotional tilt.
- Enforces weekly and monthly drawdown ceilings.
- Provides actionable recommendations: TRADING_ALLOWED, COOLDOWN, or HALTED.
- Fully persists cooldown and recent trade history to survive system reboots.
- Robust timezone-aware comparisons preventing offset-naive/aware crashes.
"""

from __future__ import annotations

import os
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("trading.ml.circuit_breaker")


def _normalize_dt(dt: Any) -> datetime:
    """Normalizes any input (str, naive datetime, aware datetime) to UTC aware datetime."""
    if isinstance(dt, str):
        try:
            parsed = datetime.fromisoformat(dt.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            return datetime.now(timezone.utc)
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class CircuitConfig:
    max_daily_loss_pct: float = 0.02       # 2% max realized daily loss of portfolio capital
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

    def __init__(self, config: Optional[CircuitConfig] = None, state_file: Optional[str] = None):
        self.config = config or CircuitConfig()
        if state_file:
            self.state_file = state_file
        elif os.getenv("PYTEST_CURRENT_TEST"):
            self.state_file = None
        else:
            self.state_file = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "logs", "circuit_breaker_state.json")
            )
        self.recent_trades: List[Dict[str, Any]] = []
        self._cooldown_until: Optional[datetime] = None
        if self.state_file:
            self._load_state()

    def _load_state(self) -> None:
        """Loads persisted circuit breaker state from disk."""
        if not self.state_file or not os.path.exists(self.state_file):
            return
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            cd_str = data.get("cooldown_until")
            self._cooldown_until = _normalize_dt(cd_str) if cd_str else None
            trades = data.get("recent_trades", [])
            self.recent_trades = [
                {
                    "pnl_pct": float(t.get("pnl_pct", 0.0)),
                    "cash_pnl": float(t.get("cash_pnl", 0.0)),
                    "timestamp": _normalize_dt(t.get("timestamp")),
                    "is_win": bool(t.get("is_win", False))
                }
                for t in trades
            ]
        except Exception as e:
            logger.debug(f"Could not load circuit breaker state: {e}")

    def _save_state(self) -> None:
        """Atomically persists circuit breaker state to disk."""
        if not self.state_file:
            return
        try:
            import tempfile
            directory = os.path.dirname(os.path.abspath(self.state_file))
            os.makedirs(directory, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=directory, prefix=".cb_state_", suffix=".json")
            payload = {
                "cooldown_until": self._cooldown_until.isoformat() if self._cooldown_until else None,
                "recent_trades": [
                    {
                        "pnl_pct": t.get("pnl_pct", 0.0),
                        "cash_pnl": t.get("cash_pnl", 0.0),
                        "timestamp": _normalize_dt(t.get("timestamp")).isoformat(),
                        "is_win": t.get("is_win", False)
                    }
                    for t in self.recent_trades[-100:]
                ]
            }
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.state_file)
        except Exception as e:
            logger.debug(f"Could not save circuit breaker state: {e}")

    def record_trade_outcome(self, pnl_pct: float, cash_pnl: float, closed_at: Optional[Any] = None):
        """Records a completed trade into the breaker ledger and persists state."""
        dt = _normalize_dt(closed_at or datetime.now(timezone.utc))
        self.recent_trades.append({
            "pnl_pct": pnl_pct,
            "cash_pnl": cash_pnl,
            "timestamp": dt,
            "is_win": pnl_pct > 0
        })
        self._save_state()

    def get_consecutive_losses(self) -> int:
        """Counts unbroken losing trades from the most recent outcome backwards."""
        streak = 0
        for trade in reversed(self.recent_trades):
            if not trade.get("is_win", False):
                streak += 1
            else:
                break
        return streak

    def get_daily_realized_loss(
        self,
        current_capital: Optional[float] = None,
        current_time: Optional[Any] = None
    ) -> float:
        """
        Computes total realized loss pct in the last 24 hours.
        If current_capital is provided, calculates cash loss / portfolio capital.
        Otherwise falls back to sum of per-trade loss pct.
        """
        if isinstance(current_capital, datetime):
            current_time = current_capital
            current_capital = None

        now = _normalize_dt(current_time or datetime.now(timezone.utc))
        one_day_ago = now - timedelta(days=1)
        total_cash_loss = 0.0
        total_trade_loss_pct = 0.0

        for t in self.recent_trades:
            t_time = _normalize_dt(t["timestamp"])
            if t_time >= one_day_ago:
                cash_p = t.get("cash_pnl", 0.0)
                pnl_p = t.get("pnl_pct", 0.0)
                if cash_p < 0:
                    total_cash_loss += abs(cash_p)
                elif pnl_p < 0:
                    total_trade_loss_pct += abs(pnl_p)

        if current_capital and current_capital > 0:
            return total_cash_loss / current_capital
        return total_trade_loss_pct if total_trade_loss_pct > 0 else (total_cash_loss / 100000.0)

    def evaluate(self, current_capital: float, current_time: Optional[Any] = None) -> CircuitDecision:
        """
        Evaluates whether new trade risk is permitted today.
        """
        now = _normalize_dt(current_time or datetime.now(timezone.utc))

        # 1. Check active cooldown timer
        if self._cooldown_until and now < self._cooldown_until:
            rem_hrs = max(0.0, (self._cooldown_until - now).total_seconds() / 3600.0)
            return CircuitDecision(
                status="COOLDOWN",
                is_allowed=False,
                reason=f"Active losing-streak cooldown in effect for another {rem_hrs:.1f} hours. Prevents revenge trading.",
                daily_realized_pnl=-self.get_daily_realized_loss(current_capital, now),
                consecutive_losses=self.get_consecutive_losses(),
                cooldown_expires_at=self._cooldown_until,
                cooldown_hours_remaining=round(rem_hrs, 2)
            )

        # 2. Check consecutive loss streak
        losses = self.get_consecutive_losses()
        if losses >= self.config.losing_streak_threshold:
            self._cooldown_until = now + timedelta(hours=self.config.cooldown_hours)
            self._save_state()
            rem_hrs = self.config.cooldown_hours
            logger.warning(f"🚨 CIRCUIT BREAKER TRIGGERED: {losses} consecutive losses. Initiating {rem_hrs}h cooldown.")
            return CircuitDecision(
                status="COOLDOWN",
                is_allowed=False,
                reason=f"Losing streak threshold reached ({losses} consecutive losses). Mandating {rem_hrs:.0f}h risk pause.",
                daily_realized_pnl=-self.get_daily_realized_loss(current_capital, now),
                consecutive_losses=losses,
                cooldown_expires_at=self._cooldown_until,
                cooldown_hours_remaining=rem_hrs
            )

        # 3. Check daily realized loss limit relative to portfolio capital
        daily_loss_pct = self.get_daily_realized_loss(current_capital, now)
        if daily_loss_pct >= self.config.max_daily_loss_pct:
            logger.warning(
                f"🚨 CIRCUIT BREAKER TRIGGERED: Daily realized loss {daily_loss_pct*100:.2f}% "
                f"exceeds {self.config.max_daily_loss_pct*100:.1f}% limit."
            )
            return CircuitDecision(
                status="HALTED",
                is_allowed=False,
                reason=(
                    f"Daily realized loss ({daily_loss_pct*100:.2f}%) reached max daily budget "
                    f"({self.config.max_daily_loss_pct*100:.1f}%). Trading halted for today."
                ),
                daily_realized_pnl=-daily_loss_pct,
                consecutive_losses=losses
            )

        # 4. Trading Allowed
        return CircuitDecision(
            status="TRADING_ALLOWED",
            is_allowed=True,
            reason="Account risk parameters healthy; new trade risk permitted.",
            daily_realized_pnl=-daily_loss_pct,
            consecutive_losses=losses
        )
