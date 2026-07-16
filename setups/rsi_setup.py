"""
RSI (Relative Strength Index) Setup.

Uses Wilder's RSI-14 to detect overbought / oversold conditions.
Confidence increases the deeper the RSI pushes into extreme territory.
"""

from __future__ import annotations

import pandas as pd

from setups.base import BaseSetup, SetupSignal
from setups.indicators import rsi as calc_rsi


class RSISetup(BaseSetup):
    name = "RSI"

    period: int = 14
    overbought: float = 70.0
    oversold: float = 30.0

    def evaluate(self, df: pd.DataFrame) -> SetupSignal:
        close = df["close"]
        if len(close) < self.period + 2:
            return SetupSignal(
                name=self.name,
                signal="neutral",
                confidence=0.0,
                reasoning=f"Insufficient data ({len(close)} bars, need {self.period + 2}).",
            )

        rsi_series = calc_rsi(close, self.period)
        current_rsi = float(rsi_series.iloc[-1])

        if pd.isna(current_rsi):
            return SetupSignal(
                name=self.name,
                signal="neutral",
                confidence=0.0,
                reasoning="RSI could not be computed (NaN).",
            )

        # ── Oversold (bullish bounce expected) ──────────────────────
        if current_rsi < self.oversold:
            # Deeper oversold → higher confidence
            # RSI 30 → conf ~0.4,  RSI 20 → conf ~0.8,  RSI 10 → conf 1.0
            denom = max(self.oversold, 0.1)
            depth = (self.oversold - current_rsi) / denom
            confidence = min(0.4 + depth * 1.5, 1.0)
            return SetupSignal(
                name=self.name,
                signal="bullish",
                confidence=confidence,
                reasoning=(
                    f"RSI({self.period}) = {current_rsi:.1f} — oversold territory "
                    f"(below {self.oversold}).  Mean-reversion bounce likely."
                ),
                indicator_values={"current_rsi": current_rsi, "zone": "oversold"},
            )

        # ── Overbought (bearish pullback expected) ──────────────────
        if current_rsi > self.overbought:
            denom = max(100.0 - self.overbought, 0.1)
            depth = (current_rsi - self.overbought) / denom
            confidence = min(0.4 + depth * 1.5, 1.0)
            return SetupSignal(
                name=self.name,
                signal="bearish",
                confidence=confidence,
                reasoning=(
                    f"RSI({self.period}) = {current_rsi:.1f} — overbought territory "
                    f"(above {self.overbought}).  Pullback risk elevated."
                ),
                indicator_values={"current_rsi": current_rsi, "zone": "overbought"},
            )

        # ── Neutral zone ────────────────────────────────────────────
        # Slight directional lean based on which half of the neutral band
        mid = (self.overbought + self.oversold) / 2.0
        if current_rsi >= mid:
            lean = "mildly bullish"
        else:
            lean = "mildly bearish"

        return SetupSignal(
            name=self.name,
            signal="neutral",
            confidence=0.0,
            reasoning=(
                f"RSI({self.period}) = {current_rsi:.1f} — neutral zone "
                f"({self.oversold}–{self.overbought}).  Momentum is {lean}."
            ),
            indicator_values={"current_rsi": current_rsi, "zone": "neutral"},
        )
