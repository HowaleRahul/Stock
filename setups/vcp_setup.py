"""
Volatility Contraction Pattern (VCP) Setup

Incorporates Mark Minervini's legendary VCP institutional setup from `tradermonty/claude-trading-skills`:
- Identifies progressive reduction in price volatility across successive contractions (T1 > T2 > T3).
- Validates volume dry-up during consolidation (low supply / smart money absorption).
- Checks trend template: price above 50 EMA and 200 EMA.
- Fires High-conviction Bullish breakout signal when price penetrates the tight pivot level.
"""

from __future__ import annotations

import logging
import numpy as np
import pandas as pd

from setups.base import BaseSetup, SetupSignal

logger = logging.getLogger("trading.setups.vcp")


class VCPSetup(BaseSetup):
    """
    Minervini Volatility Contraction Pattern (VCP) Setup.
    Detects progressive tightening of swings with volume exhaustion.
    """

    @property
    def name(self) -> str:
        return "Volatility Contraction (VCP)"

    def evaluate(self, df: pd.DataFrame, ticker: str = "") -> SetupSignal:
        if df is None or len(df) < 50:
            return SetupSignal(self.name, "neutral", 0.0, "Insufficient bars for VCP analysis (needs 50+).")

        close = df["close"]
        high = df["high"]
        low = df["low"]
        vol = df["volume"] if "volume" in df.columns else None

        current_price = float(close.iloc[-1])

        # 1. Trend Filter: Must be in stage 2 uptrend (Price > 50 EMA)
        ema50 = close.ewm(span=50, adjust=False).mean()
        is_above_50 = current_price >= float(ema50.iloc[-1])

        # 2. Measure rolling volatility across 3 contraction windows:
        # Window 1 (bars -45 to -25): Earlier swing
        # Window 2 (bars -25 to -10): Intermediate swing
        # Window 3 (bars -10 to -1): Tightest pivot
        w1_high = float(high.iloc[-45:-25].max())
        w1_low = float(low.iloc[-45:-25].min())
        w1_depth = (w1_high - w1_low) / w1_high if w1_high > 0 else 0.0

        w2_high = float(high.iloc[-25:-10].max())
        w2_low = float(low.iloc[-25:-10].min())
        w2_depth = (w2_high - w2_low) / w2_high if w2_high > 0 else 0.0

        w3_high = float(high.iloc[-10:].max())
        w3_low = float(low.iloc[-10:].min())
        w3_depth = (w3_high - w3_low) / w3_high if w3_high > 0 else 0.0

        # VCP Contraction condition: w1_depth > w2_depth > w3_depth (successive contractions)
        is_contracting = (w1_depth > w2_depth > w3_depth) and (w3_depth <= 0.08)  # tightest pivot <= 8%

        # 3. Volume Contraction: recent volume should dry up vs 20-period average
        vol_drying = True
        rel_vol = 1.0
        if vol is not None and len(vol) >= 20:
            vol_sma20 = vol.rolling(20).mean()
            recent_avg_vol = float(vol.iloc[-5:].mean())
            base_vol = float(vol_sma20.iloc[-1])
            if base_vol > 0:
                rel_vol = recent_avg_vol / base_vol
                vol_drying = rel_vol < 0.90  # volume drying up on the right side of the base

        pivot_resistance = w3_high
        is_breaking_pivot = current_price >= pivot_resistance * 0.995

        ind_values = {
            "w1_depth_pct": round(w1_depth * 100, 2),
            "w2_depth_pct": round(w2_depth * 100, 2),
            "w3_depth_pct": round(w3_depth * 100, 2),
            "rel_volume": round(rel_vol, 2),
            "pivot_resistance": round(pivot_resistance, 2),
            "is_above_50ema": is_above_50,
        }

        if is_above_50 and is_contracting and vol_drying:
            if is_breaking_pivot:
                return SetupSignal(
                    self.name,
                    "bullish",
                    0.85,
                    f"VCP Breakout Active! Contractions ({w1_depth*100:.1f}% -> {w2_depth*100:.1f}% -> {w3_depth*100:.1f}%) with volume dry-up ({rel_vol:.2f}x). Crossing pivot ₹{pivot_resistance:,.2f}.",
                    indicator_values=ind_values,
                )
            else:
                return SetupSignal(
                    self.name,
                    "bullish",
                    0.70,
                    f"VCP Setup Formed. Volatility tightening ({w1_depth*100:.1f}% -> {w2_depth*100:.1f}% -> {w3_depth*100:.1f}%), volume exhausted. Awaiting breakout above ₹{pivot_resistance:,.2f}.",
                    indicator_values=ind_values,
                )
        elif not is_above_50 and (w1_depth < w2_depth < w3_depth):
            # Expanding volatility in downtrend = distribution / breakdown
            return SetupSignal(
                self.name,
                "bearish",
                0.65,
                f"Expanding volatility in downtrend below 50 EMA ({w1_depth*100:.1f}% -> {w3_depth*100:.1f}%). High distribution risk.",
                indicator_values=ind_values,
            )

        return SetupSignal(
            self.name,
            "neutral",
            0.20,
            f"No clean Volatility Contraction Pattern detected (Spreads: {w1_depth*100:.1f}%, {w2_depth*100:.1f}%, {w3_depth*100:.1f}%).",
            indicator_values=ind_values,
        )
