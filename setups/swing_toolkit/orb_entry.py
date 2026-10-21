"""
Opening Range Breakout (ORB) & Early Volume Gate Execution Engine.

Implements the Momentum Masters institutional breakout entry protocol:
1. Volume Gate 1 (First 5 min): Cumulative volume >= 7-10% of 20-day ADV.
2. Volume Gate 2 (First 15 min): Cumulative volume >= 17-20% of 20-day ADV.
3. 15-Minute Opening Range: Mark High and Low of the first 15 minutes.
4. Entry Trigger: Buy when price crosses above the 15m ORB High WITH volume gate confirmed.
5. Invalidation Stop: Placed at 15m ORB Low (or structural swing low).
6. Position Sizing: Sized strictly by predefined account risk (default 1-2%).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd

from setups.indicators import sma

logger = logging.getLogger("trading.setups.swing_orb")


@dataclass
class ORBExecutionPlan:
    ticker: str
    is_triggered: bool
    volume_gate_confirmed: bool
    gate_5m_pct: float
    gate_5m_passed: bool
    gate_15m_pct: float
    gate_15m_passed: bool
    orb_high: float
    orb_low: float
    current_price: float
    adv_20: float
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    target_2r: Optional[float] = None
    target_3r: Optional[float] = None
    position_size: int = 0
    risk_amount: float = 0.0
    reasoning: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "is_triggered": self.is_triggered,
            "volume_gate_confirmed": self.volume_gate_confirmed,
            "gate_5m_pct": round(self.gate_5m_pct, 2),
            "gate_5m_passed": self.gate_5m_passed,
            "gate_15m_pct": round(self.gate_15m_pct, 2),
            "gate_15m_passed": self.gate_15m_passed,
            "orb_high": round(self.orb_high, 2),
            "orb_low": round(self.orb_low, 2),
            "current_price": round(self.current_price, 2),
            "adv_20": round(self.adv_20, 0),
            "entry_price": round(self.entry_price, 2) if self.entry_price else None,
            "stop_loss": round(self.stop_loss, 2) if self.stop_loss else None,
            "target_2r": round(self.target_2r, 2) if self.target_2r else None,
            "target_3r": round(self.target_3r, 2) if self.target_3r else None,
            "position_size": self.position_size,
            "risk_amount": round(self.risk_amount, 2),
            "reasoning": self.reasoning,
        }


class ORBBreakoutEngine:
    """
    Evaluates intraday 5m/15m bars against the 20-day ADV volume gates
    and manages Opening Range Breakout entries.
    """

    MIN_GATE_5M_PCT = 7.0    # 7% of 20d ADV in first 5 mins
    MIN_GATE_15M_PCT = 17.0  # 17% of 20d ADV in first 15 mins

    def evaluate_entry(
        self,
        intraday_5m_df: pd.DataFrame,
        daily_df: pd.DataFrame,
        ticker: str,
        capital: float = 1000000.0,
        risk_per_trade_pct: float = 0.015,  # 1.5% max account risk
    ) -> ORBExecutionPlan:
        # Calculate 20-day Average Daily Volume from daily bars
        if daily_df is None or len(daily_df) < 5:
            adv_20 = 500000.0  # Safe fallback
        else:
            daily_vol = pd.to_numeric(daily_df["volume"], errors="coerce")
            vol_sma = sma(daily_vol, min(20, len(daily_vol)))
            adv_20 = float(vol_sma.iloc[-1]) if not np.isnan(vol_sma.iloc[-1]) else float(daily_vol.iloc[-1])
            if adv_20 <= 0:
                adv_20 = 500000.0

        if intraday_5m_df is None or len(intraday_5m_df) < 1:
            return ORBExecutionPlan(
                ticker=ticker,
                is_triggered=False,
                volume_gate_confirmed=False,
                gate_5m_pct=0.0,
                gate_5m_passed=False,
                gate_15m_pct=0.0,
                gate_15m_passed=False,
                orb_high=0.0,
                orb_low=0.0,
                current_price=0.0,
                adv_20=adv_20,
                reasoning="No intraday bars available.",
            )

        close = pd.to_numeric(intraday_5m_df["close"], errors="coerce").astype(float)
        high = pd.to_numeric(intraday_5m_df["high"], errors="coerce").astype(float)
        low = pd.to_numeric(intraday_5m_df["low"], errors="coerce").astype(float)
        volume = pd.to_numeric(intraday_5m_df["volume"], errors="coerce").astype(float)

        cur_price = float(close.iloc[-1])

        # 1. First 5-minute volume gate
        vol_5m = float(volume.iloc[0])
        gate_5m_pct = (vol_5m / adv_20) * 100.0
        gate_5m_passed = gate_5m_pct >= self.MIN_GATE_5M_PCT

        # 2. First 15-minute volume gate (bars 0, 1, 2 for 5m candles)
        bars_15m_count = min(3, len(volume))
        vol_15m = float(volume.iloc[:bars_15m_count].sum())
        gate_15m_pct = (vol_15m / adv_20) * 100.0
        gate_15m_passed = gate_15m_pct >= self.MIN_GATE_15M_PCT

        volume_gate_confirmed = gate_5m_passed or gate_15m_passed

        # 3. 15-Minute Opening Range (High and Low of first 3 5-min bars)
        orb_high = float(high.iloc[:bars_15m_count].max())
        orb_low = float(low.iloc[:bars_15m_count].min())

        # 4. Breakout Trigger
        # Can only trigger after the 15-minute opening range is fully established
        is_triggered = False
        entry_price = None
        stop_loss = None
        target_2r = None
        target_3r = None
        pos_size = 0
        risk_amount = 0.0
        reasoning = ""

        if len(intraday_5m_df) >= 3:
            # Check if latest price or any post-15m candle broke above ORB high
            post_15m_highs = high.iloc[3:]
            broken_above = (cur_price >= orb_high) or (len(post_15m_highs) > 0 and post_15m_highs.max() >= orb_high)

            if broken_above and volume_gate_confirmed:
                is_triggered = True
                entry_price = max(cur_price, orb_high)
                stop_loss = orb_low * 0.998  # Small buffer below ORB low
                risk_per_share = max(entry_price - stop_loss, entry_price * 0.005)

                risk_capital = capital * risk_per_trade_pct
                pos_size = max(int(risk_capital / risk_per_share), 1)
                risk_amount = pos_size * risk_per_share

                target_2r = entry_price + (2.0 * risk_per_share)
                target_3r = entry_price + (3.0 * risk_per_share)

                reasoning = (
                    f"🔥 ORB BUY TRIGGERED! Price {cur_price:.2f} broke above 15m ORB High ({orb_high:.2f}). "
                    f"Volume Gates: 5m={gate_5m_pct:.1f}% of ADV (Req: {self.MIN_GATE_5M_PCT}%), "
                    f"15m={gate_15m_pct:.1f}% of ADV (Req: {self.MIN_GATE_15M_PCT}%). "
                    f"Defined Risk: Stop Loss @ ₹{stop_loss:.2f}, Targets: 2R @ ₹{target_2r:.2f}, 3R @ ₹{target_3r:.2f}."
                )
            elif broken_above and not volume_gate_confirmed:
                reasoning = (
                    f"⚠️ Breakout above {orb_high:.2f} rejected by Volume Gate. "
                    f"Early volume pace (5m: {gate_5m_pct:.1f}%, 15m: {gate_15m_pct:.1f}%) is below institutional threshold. "
                    f"Avoid false bull-trap breakout."
                )
            else:
                reasoning = (
                    f"Watching 15m ORB [{orb_low:.2f} - {orb_high:.2f}]. Current Price: {cur_price:.2f}. "
                    f"Volume Gate: {'CONFIRMED (' + str(round(gate_15m_pct, 1)) + '%)' if volume_gate_confirmed else 'AWAITING DEMAND'}."
                )
        else:
            reasoning = f"Building 15-minute Opening Range (Bar {len(intraday_5m_df)} of 3). High: {orb_high:.2f}, Low: {orb_low:.2f}."

        return ORBExecutionPlan(
            ticker=ticker,
            is_triggered=is_triggered,
            volume_gate_confirmed=volume_gate_confirmed,
            gate_5m_pct=gate_5m_pct,
            gate_5m_passed=gate_5m_passed,
            gate_15m_pct=gate_15m_pct,
            gate_15m_passed=gate_15m_passed,
            orb_high=orb_high,
            orb_low=orb_low,
            current_price=cur_price,
            adv_20=adv_20,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target_2r=target_2r,
            target_3r=target_3r,
            position_size=pos_size,
            risk_amount=risk_amount,
            reasoning=reasoning,
        )
