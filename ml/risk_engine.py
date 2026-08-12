"""
Risk Engine — Phase 6: Complete Trade Plan Generator.

Converts raw AI signals into fully actionable trade plans with:
- Position sizing (Kelly Criterion, capped at 2% risk per trade)
- ATR + S/R based Entry / Target / Stop Loss
- Risk:Reward gating (reject < 1.5:1)
- Probability of Ruin calculation
- Trailing stop management
- Time-based exit enforcement
- Portfolio correlation checks
"""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
import pandas as pd

from setups.indicators import find_support_resistance

logger = logging.getLogger("trading.risk_engine")


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class TradePlan:
    """A complete, actionable trade recommendation."""

    # Identification
    ticker: str
    direction: str  # "LONG" or "SHORT"
    timeframe: str  # "1h" or "1d"

    # Prices
    entry_price: float
    stop_loss: float
    take_profit: float
    trailing_stop: Optional[float] = None

    # Risk Metrics
    risk_reward_ratio: float = 0.0
    risk_per_trade_pct: float = 0.0  # % of capital risked
    position_size_qty: int = 0
    position_value: float = 0.0
    max_loss_amount: float = 0.0
    max_profit_amount: float = 0.0

    # Probability & Statistics
    ai_probability: float = 0.0
    kelly_fraction: float = 0.0
    probability_of_ruin: float = 0.0
    win_rate: float = 0.5  # Historical win rate used

    # Context
    atr_at_entry: float = 0.0
    regime: str = "unknown"
    sl_method: str = ""  # "ATR" or "Swing Point"
    tp_method: str = ""  # "ATR" or "S/R Level"
    max_hold_bars: int = 0
    reasoning: str = ""

    # Gating
    is_approved: bool = True
    rejection_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "direction": self.direction,
            "timeframe": self.timeframe,
            "entry_price": round(self.entry_price, 2),
            "stop_loss": round(self.stop_loss, 2),
            "take_profit": round(self.take_profit, 2),
            "trailing_stop": round(self.trailing_stop, 2) if self.trailing_stop else None,
            "risk_reward_ratio": round(self.risk_reward_ratio, 2),
            "risk_per_trade_pct": round(self.risk_per_trade_pct, 4),
            "position_size_qty": self.position_size_qty,
            "position_value": round(self.position_value, 2),
            "max_loss_amount": round(self.max_loss_amount, 2),
            "max_profit_amount": round(self.max_profit_amount, 2),
            "ai_probability": round(self.ai_probability, 4),
            "kelly_fraction": round(self.kelly_fraction, 4),
            "probability_of_ruin": round(self.probability_of_ruin, 6),
            "win_rate": round(self.win_rate, 4),
            "atr_at_entry": round(self.atr_at_entry, 4),
            "regime": self.regime,
            "sl_method": self.sl_method,
            "tp_method": self.tp_method,
            "max_hold_bars": self.max_hold_bars,
            "reasoning": self.reasoning,
            "is_approved": self.is_approved,
            "rejection_reasons": self.rejection_reasons,
        }


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Hard risk caps
MAX_RISK_PER_TRADE_PCT = 0.02   # Never risk more than 2% of capital per trade
MIN_RISK_REWARD_RATIO = 1.5     # Reject anything under 1.5:1 R:R
STT_SLIPPAGE_PCT = 0.0005       # 0.05% combined Indian STT + slippage friction

# Trailing stop parameters (in ATR multiples)
TRAIL_BREAKEVEN_THRESHOLD = 1.0  # Move SL to breakeven after 1× ATR move in our favor
TRAIL_LOCK_PROFIT_THRESHOLD = 1.5  # Lock in 0.5× ATR profit after 1.5× ATR move
TRAIL_LOCK_AMOUNT = 0.5  # ATR multiples of profit to lock

# Timeframe-specific hold limits
TIMEFRAME_HOLD_LIMITS = {
    "1h": 40,  # 40 hourly bars = ~1 week
    "1d": 20,  # 20 daily bars = ~1 month
}

# Correlation matrix for instruments we trade
# NIFTY and BANKNIFTY are ~0.92 correlated historically
CORRELATION_MATRIX = {
    ("^NSEI", "^NSEBANK"): 0.92,
    ("^NSEBANK", "^NSEI"): 0.92,
}

# If correlation > this threshold, treat positions as overlapping
CORRELATION_THRESHOLD = 0.70


# ---------------------------------------------------------------------------
# Risk Engine
# ---------------------------------------------------------------------------

class RiskEngine:
    """
    Institutional-grade risk management engine.
    
    Takes a raw AI signal and market data, outputs a complete trade plan
    or rejects the trade with explicit reasoning.
    """

    def __init__(self, historical_trades: Optional[List[Dict]] = None):
        """
        Args:
            historical_trades: List of past trade dicts with at minimum
                'status' ('CLOSED_WIN' or 'CLOSED_LOSS') and 'pnl_pct' fields.
                Used to compute historical win rate for Kelly and Ruin calculations.
        """
        self._historical_trades = historical_trades or []
        self._win_rate = self._compute_win_rate()
        self._avg_win = self._compute_avg_win()
        self._avg_loss = self._compute_avg_loss()

    def _compute_win_rate(self) -> float:
        """Calculate historical win rate from closed trades."""
        closed = [t for t in self._historical_trades
                  if t.get("status") in ("CLOSED_WIN", "CLOSED_LOSS")]
        if len(closed) < 5:
            # Not enough data — use conservative default
            return 0.50
        wins = sum(1 for t in closed if t["status"] == "CLOSED_WIN")
        return wins / len(closed)

    def _compute_avg_win(self) -> float:
        """Average winning trade return."""
        wins = [t.get("pnl_pct", 0) for t in self._historical_trades
                if t.get("status") == "CLOSED_WIN" and t.get("pnl_pct", 0) > 0]
        return float(np.mean(wins)) if wins else 0.01

    def _compute_avg_loss(self) -> float:
        """Average losing trade return (as positive number)."""
        losses = [abs(t.get("pnl_pct", 0)) for t in self._historical_trades
                  if t.get("status") == "CLOSED_LOSS" and t.get("pnl_pct", 0) < 0]
        return float(np.mean(losses)) if losses else 0.005

    # -----------------------------------------------------------------------
    # Core: Generate a complete trade plan
    # -----------------------------------------------------------------------

    def generate_trade_plan(
        self,
        ticker: str,
        direction: str,  # "bullish" or "bearish"
        ai_probability: float,
        df: pd.DataFrame,
        capital: float,
        regime: str = "unknown",
        timeframe: str = "1h",
        open_positions: Optional[List[Dict]] = None,
    ) -> TradePlan:
        """
        Generate a complete, actionable trade plan from a raw signal.

        Args:
            ticker: The instrument ticker (e.g., "^NSEI")
            direction: "bullish" or "bearish"
            ai_probability: AI confidence (0.0 to 1.0)
            df: OHLCV DataFrame with 'close', 'high', 'low', 'atr' columns
            capital: Current available capital
            regime: Current market regime string
            timeframe: "1h" or "1d"
            open_positions: List of currently open trade dicts for correlation check

        Returns:
            TradePlan with all fields populated, including approval status.
        """
        trade_dir = "LONG" if direction.lower() == "bullish" else "SHORT"
        close = float(df["close"].iloc[-1])
        atr = float(df["atr"].iloc[-1]) if "atr" in df.columns else self._calculate_atr(df)

        # Prevent zero ATR
        if atr <= 0:
            atr = close * 0.01

        max_hold = TIMEFRAME_HOLD_LIMITS.get(timeframe, 20)

        # 1. Calculate Entry Price (with slippage)
        if trade_dir == "LONG":
            entry = close * (1 + STT_SLIPPAGE_PCT)
        else:
            entry = close * (1 - STT_SLIPPAGE_PCT)

        # 2. Calculate Stop Loss (ATR-based vs Swing Point — pick the tighter one)
        sl_price, sl_method = self._calculate_stop_loss(df, entry, atr, trade_dir)

        # 3. Calculate Take Profit (ATR-based vs S/R level — pick optimal)
        tp_price, tp_method = self._calculate_take_profit(df, entry, atr, trade_dir, sl_price)

        # 4. Calculate Risk:Reward Ratio
        sl_distance = abs(entry - sl_price)
        tp_distance = abs(tp_price - entry)

        if sl_distance <= 0:
            sl_distance = atr  # Fallback

        rr_ratio = tp_distance / sl_distance if sl_distance > 0 else 0.0

        # 5. Position Sizing (Kelly Criterion, capped at 2%)
        kelly_f = self._kelly_criterion(ai_probability, rr_ratio)
        risk_pct = min(kelly_f, MAX_RISK_PER_TRADE_PCT)
        risk_pct = max(risk_pct, 0.001)  # Floor at 0.1% to avoid zero positions

        capital_at_risk = capital * risk_pct
        qty = int(capital_at_risk / sl_distance) if sl_distance > 0 else 0

        # Cap quantity so position value doesn't exceed capital
        if qty > 0:
            position_val = qty * entry
            if position_val > capital:
                qty = int(capital / entry)
                position_val = qty * entry
        else:
            position_val = 0.0

        max_loss = qty * sl_distance
        max_profit = qty * tp_distance

        # 6. Probability of Ruin
        p_ruin = self._probability_of_ruin(
            win_rate=self._win_rate,
            avg_win=tp_distance,
            avg_loss=sl_distance,
            risk_fraction=risk_pct
        )

        # 7. Build the Trade Plan
        plan = TradePlan(
            ticker=ticker,
            direction=trade_dir,
            timeframe=timeframe,
            entry_price=entry,
            stop_loss=sl_price,
            take_profit=tp_price,
            trailing_stop=sl_price,  # Initial trailing stop = SL
            risk_reward_ratio=rr_ratio,
            risk_per_trade_pct=risk_pct,
            position_size_qty=qty,
            position_value=position_val,
            max_loss_amount=max_loss,
            max_profit_amount=max_profit,
            ai_probability=ai_probability,
            kelly_fraction=kelly_f,
            probability_of_ruin=p_ruin,
            win_rate=self._win_rate,
            atr_at_entry=atr,
            regime=regime,
            sl_method=sl_method,
            tp_method=tp_method,
            max_hold_bars=max_hold,
        )

        # 8. Apply Rejection Gates
        self._apply_gates(plan, open_positions or [])

        # 9. Build reasoning string
        plan.reasoning = self._build_reasoning(plan)

        return plan

    # -----------------------------------------------------------------------
    # Stop Loss Calculation
    # -----------------------------------------------------------------------

    def _calculate_stop_loss(
        self, df: pd.DataFrame, entry: float, atr: float, direction: str
    ) -> Tuple[float, str]:
        """
        Calculate optimal stop loss using:
        1. ATR-based: 1× ATR from entry
        2. Swing Point: Recent pivot high/low
        
        Uses whichever provides a tighter, more logical stop.
        """
        # ATR-based SL
        if direction == "LONG":
            atr_sl = entry - (1.0 * atr)
        else:
            atr_sl = entry + (1.0 * atr)

        # Swing Point SL
        try:
            sr_levels = find_support_resistance(
                df["close"], df["high"], df["low"], lookback=50, num_levels=5
            )

            if direction == "LONG" and sr_levels["support"]:
                # Find nearest support below entry
                supports_below = [s for s in sr_levels["support"] if s < entry]
                if supports_below:
                    swing_sl = max(supports_below)  # Closest support below
                    # Only use swing point if it's within 1.5× ATR distance
                    # (too far = not meaningful)
                    if abs(entry - swing_sl) <= 1.5 * atr:
                        # Use the tighter of ATR and swing point
                        if swing_sl > atr_sl:
                            return swing_sl, "Swing Point"
            elif direction == "SHORT" and sr_levels["resistance"]:
                resistances_above = [r for r in sr_levels["resistance"] if r > entry]
                if resistances_above:
                    swing_sl = min(resistances_above)  # Closest resistance above
                    if abs(swing_sl - entry) <= 1.5 * atr:
                        if swing_sl < atr_sl:
                            return swing_sl, "Swing Point"
        except Exception as e:
            logger.debug(f"Swing point SL calculation failed: {e}")

        return atr_sl, "ATR"

    # -----------------------------------------------------------------------
    # Take Profit Calculation
    # -----------------------------------------------------------------------

    def _calculate_take_profit(
        self, df: pd.DataFrame, entry: float, atr: float, direction: str,
        sl_price: float
    ) -> Tuple[float, str]:
        """
        Calculate optimal take profit using:
        1. ATR-based: 2× ATR from entry (default 2:1 R:R target)
        2. S/R Level: Next resistance (for longs) or support (for shorts)
        
        Uses whichever is closest to achieving 2:1 R:R without being unrealistic.
        """
        sl_distance = abs(entry - sl_price)

        # ATR-based TP (targeting 2:1 R:R minimum)
        if direction == "LONG":
            atr_tp = entry + (2.0 * atr)
        else:
            atr_tp = entry - (2.0 * atr)

        # S/R Level TP
        try:
            sr_levels = find_support_resistance(
                df["close"], df["high"], df["low"], lookback=50, num_levels=5
            )

            if direction == "LONG" and sr_levels["resistance"]:
                # Find resistance levels above entry
                resistances_above = sorted([r for r in sr_levels["resistance"] if r > entry])
                for res_level in resistances_above:
                    tp_distance = res_level - entry
                    # Only use S/R target if it achieves at least 1.5:1 R:R
                    if sl_distance > 0 and (tp_distance / sl_distance) >= MIN_RISK_REWARD_RATIO:
                        # Use S/R level if it's more conservative (closer) than 2× ATR
                        if res_level < atr_tp:
                            return res_level, "S/R Level"
                        break  # The ATR target is closer, use that

            elif direction == "SHORT" and sr_levels["support"]:
                supports_below = sorted([s for s in sr_levels["support"] if s < entry], reverse=True)
                for sup_level in supports_below:
                    tp_distance = entry - sup_level
                    if sl_distance > 0 and (tp_distance / sl_distance) >= MIN_RISK_REWARD_RATIO:
                        if sup_level > atr_tp:
                            return sup_level, "S/R Level"
                        break
        except Exception as e:
            logger.debug(f"S/R TP calculation failed: {e}")

        return atr_tp, "ATR"

    # -----------------------------------------------------------------------
    # Kelly Criterion Position Sizing
    # -----------------------------------------------------------------------

    def _kelly_criterion(self, win_probability: float, reward_risk_ratio: float) -> float:
        """
        Calculate Half-Kelly fraction for position sizing.
        
        Full Kelly = p - (1-p)/b
        where p = win probability, b = reward/risk ratio
        
        We use Half-Kelly (divide by 2) as a safety margin because:
        - Full Kelly is mathematically optimal but assumes perfect edge estimation
        - Half-Kelly sacrifices ~25% of theoretical returns but reduces variance by ~50%
        - This is what professional quant funds use in practice
        
        Returns:
            Fraction of capital to risk (capped at MAX_RISK_PER_TRADE_PCT)
        """
        p = max(0.01, min(0.99, win_probability))
        q = 1.0 - p
        b = max(0.01, reward_risk_ratio)

        full_kelly = p - (q / b)

        if full_kelly <= 0:
            # Negative Kelly means the edge is insufficient — size at minimum
            return 0.005  # 0.5% risk floor for exploration

        half_kelly = full_kelly / 2.0
        return min(half_kelly, MAX_RISK_PER_TRADE_PCT)

    # -----------------------------------------------------------------------
    # Probability of Ruin
    # -----------------------------------------------------------------------

    def _probability_of_ruin(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        risk_fraction: float,
        ruin_threshold: float = 0.5  # Account destroyed at 50% drawdown
    ) -> float:
        """
        Calculate the probability that a sequence of trades will draw the account
        down to the ruin threshold.
        
        Uses the classic gambler's ruin formula adapted for asymmetric payoffs:
        
        P(ruin) = ((1 - edge) / (1 + edge))^N
        
        where:
            edge = (win_rate × avg_win) - ((1 - win_rate) × avg_loss)
            N = number of risk units until ruin
        
        This accounts for the sequence-of-losses risk that a flat per-trade 
        percentage rule completely misses. A trader with 55% win rate and 2:1 R:R
        has very different ruin probability at 2% risk vs 10% risk.
        """
        p = max(0.01, min(0.99, win_rate))
        q = 1.0 - p

        # Expected value per trade in risk-units
        if avg_loss <= 0:
            avg_loss = 1.0
        payoff_ratio = avg_win / avg_loss if avg_loss > 0 else 1.0

        # Edge per trade
        edge = (p * payoff_ratio) - q

        if edge <= 0:
            # Negative edge — ruin is nearly certain
            return 0.99

        # Number of risk units until ruin
        if risk_fraction <= 0:
            return 0.0
        
        n_units = -math.log(1.0 - ruin_threshold) / risk_fraction

        # Ruin probability using the adapted formula
        ratio = q / (p * payoff_ratio) if (p * payoff_ratio) > 0 else 1.0

        if ratio >= 1.0:
            return 0.99  # No edge, ruin nearly certain

        try:
            p_ruin = ratio ** n_units
        except (OverflowError, ValueError):
            p_ruin = 0.0

        return max(0.0, min(1.0, p_ruin))

    # -----------------------------------------------------------------------
    # Trailing Stop Management
    # -----------------------------------------------------------------------

    @staticmethod
    def update_trailing_stop(
        trade: Dict[str, Any],
        current_high: float,
        current_low: float,
    ) -> Dict[str, Any]:
        """
        Update trailing stop for an open trade based on current price action.
        
        Logic:
        1. After price moves 1× ATR in our favor → trail SL to breakeven
        2. After price moves 1.5× ATR in our favor → lock in 0.5× ATR profit
        3. Never move the trailing stop backwards (only tighten)
        
        Args:
            trade: Trade dict with 'direction', 'entry_price', 'atr_at_entry',
                   'trailing_stop', 'sl' keys
            current_high: Current bar's high
            current_low: Current bar's low
            
        Returns:
            Updated trade dict with new trailing_stop value
        """
        entry = trade["entry_price"]
        atr = trade["atr_at_entry"]
        current_trail = trade.get("trailing_stop", trade["sl"])

        if trade["direction"] == "LONG":
            # How far has price moved in our favor?
            favorable_move = current_high - entry

            if favorable_move >= TRAIL_LOCK_PROFIT_THRESHOLD * atr:
                # Lock in 0.5× ATR profit
                new_trail = entry + (TRAIL_LOCK_AMOUNT * atr)
            elif favorable_move >= TRAIL_BREAKEVEN_THRESHOLD * atr:
                # Move to breakeven
                new_trail = entry
            else:
                new_trail = current_trail

            # Never move trailing stop downward
            trade["trailing_stop"] = max(current_trail, new_trail)

        elif trade["direction"] == "SHORT":
            favorable_move = entry - current_low

            if favorable_move >= TRAIL_LOCK_PROFIT_THRESHOLD * atr:
                new_trail = entry - (TRAIL_LOCK_AMOUNT * atr)
            elif favorable_move >= TRAIL_BREAKEVEN_THRESHOLD * atr:
                new_trail = entry
            else:
                new_trail = current_trail

            # Never move trailing stop upward (for shorts)
            trade["trailing_stop"] = min(current_trail, new_trail)

        return trade

    # -----------------------------------------------------------------------
    # Time-Based Exit Check
    # -----------------------------------------------------------------------

    @staticmethod
    def check_time_exit(trade: Dict[str, Any], bars_held: int) -> bool:
        """
        Check if a trade has exceeded its maximum hold period.
        
        Returns True if the trade should be force-closed.
        """
        max_hold = trade.get("max_hold_bars", 20)
        return bars_held >= max_hold

    # -----------------------------------------------------------------------
    # Portfolio Correlation Check
    # -----------------------------------------------------------------------

    @staticmethod
    def check_correlation(
        ticker: str,
        direction: str,
        open_positions: List[Dict[str, Any]]
    ) -> Tuple[bool, str]:
        """
        Check if opening a new position would create hidden correlation risk.
        
        For example, going LONG on both NIFTY and BANKNIFTY is effectively
        a 2× leveraged bet on the same index — not diversification.
        
        Args:
            ticker: Proposed new ticker
            direction: "LONG" or "SHORT"
            open_positions: List of currently open trade dicts
            
        Returns:
            (is_correlated, reason) — True if correlated risk detected
        """
        if not open_positions:
            return False, ""

        for pos in open_positions:
            if pos.get("status") != "OPEN":
                continue

            existing_ticker = pos.get("ticker", "")
            existing_dir = pos.get("direction", "")

            # Check correlation matrix
            pair = (ticker, existing_ticker)
            corr = CORRELATION_MATRIX.get(pair, 0.0)

            if corr >= CORRELATION_THRESHOLD:
                if existing_dir == direction:
                    # Same direction on correlated instruments = hidden concentration
                    return True, (
                        f"CORRELATION BLOCK: {ticker} ({direction}) is {corr*100:.0f}% "
                        f"correlated with existing {existing_dir} position in "
                        f"{existing_ticker}. This is effectively a double-sized bet. "
                        f"Reduce existing position or skip."
                    )
                else:
                    # Opposite direction on correlated instruments = hedged (OK)
                    pass

        return False, ""

    # -----------------------------------------------------------------------
    # Rejection Gate
    # -----------------------------------------------------------------------

    def _apply_gates(self, plan: TradePlan, open_positions: List[Dict]) -> None:
        """
        Apply all rejection gates to a trade plan.
        If any gate fails, mark the plan as rejected with reasons.
        """
        rejections = []

        # Gate 1: Risk:Reward minimum
        if plan.risk_reward_ratio < MIN_RISK_REWARD_RATIO:
            rejections.append(
                f"R:R ratio {plan.risk_reward_ratio:.2f}:1 is below minimum "
                f"{MIN_RISK_REWARD_RATIO}:1. The potential reward does not justify the risk."
            )

        # Gate 2: Position size must be positive
        if plan.position_size_qty <= 0:
            rejections.append(
                "Position size calculated as 0 units. Capital may be insufficient "
                "or ATR-based stop distance is too wide."
            )

        # Gate 3: Probability of Ruin
        if plan.probability_of_ruin > 0.10:
            rejections.append(
                f"Probability of Ruin is {plan.probability_of_ruin*100:.2f}% — "
                f"exceeds 10% safety threshold. Reduce position size or improve edge."
            )

        # Gate 4: Correlation check
        is_correlated, corr_reason = self.check_correlation(
            plan.ticker, plan.direction, open_positions
        )
        if is_correlated:
            rejections.append(corr_reason)

        # Gate 5: AI confidence floor
        if plan.ai_probability < 0.55:
            rejections.append(
                f"AI confidence {plan.ai_probability*100:.1f}% is below 55% minimum. "
                f"Edge is too thin for a swing trade."
            )

        if rejections:
            plan.is_approved = False
            plan.rejection_reasons = rejections

    # -----------------------------------------------------------------------
    # Reasoning Builder
    # -----------------------------------------------------------------------

    def _build_reasoning(self, plan: TradePlan) -> str:
        """Build a human-readable trade plan summary."""
        if not plan.is_approved:
            return (
                f"⛔ TRADE REJECTED for {plan.ticker} ({plan.direction})\n"
                + "\n".join(f"  • {r}" for r in plan.rejection_reasons)
            )

        sl_dist_pct = abs(plan.entry_price - plan.stop_loss) / plan.entry_price * 100
        tp_dist_pct = abs(plan.take_profit - plan.entry_price) / plan.entry_price * 100

        return (
            f"✅ TRADE APPROVED: {plan.direction} {plan.ticker}\n"
            f"  📊 Entry:  ₹{plan.entry_price:,.2f}\n"
            f"  🎯 Target: ₹{plan.take_profit:,.2f} (+{tp_dist_pct:.2f}%) [{plan.tp_method}]\n"
            f"  🛑 Stop:   ₹{plan.stop_loss:,.2f} (-{sl_dist_pct:.2f}%) [{plan.sl_method}]\n"
            f"  ⚖️  R:R Ratio: {plan.risk_reward_ratio:.2f}:1\n"
            f"  📐 Position: {plan.position_size_qty} units × ₹{plan.entry_price:,.2f} = ₹{plan.position_value:,.2f}\n"
            f"  💰 Max Loss: ₹{plan.max_loss_amount:,.2f} ({plan.risk_per_trade_pct*100:.2f}% of capital)\n"
            f"  💎 Max Profit: ₹{plan.max_profit_amount:,.2f}\n"
            f"  🧠 AI Confidence: {plan.ai_probability*100:.1f}% | Kelly: {plan.kelly_fraction*100:.2f}%\n"
            f"  📉 P(Ruin): {plan.probability_of_ruin*100:.4f}% | Win Rate: {plan.win_rate*100:.1f}%\n"
            f"  ⏱️  Max Hold: {plan.max_hold_bars} bars | Regime: {plan.regime}\n"
        )

    # -----------------------------------------------------------------------
    # Utility
    # -----------------------------------------------------------------------

    @staticmethod
    def _calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
        """Calculate ATR from raw OHLCV data."""
        high_low = df["high"] - df["low"]
        high_close = np.abs(df["high"] - df["close"].shift())
        low_close = np.abs(df["low"] - df["close"].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        atr = true_range.rolling(period).mean().iloc[-1]
        return float(atr) if not np.isnan(atr) else float(true_range.mean())
