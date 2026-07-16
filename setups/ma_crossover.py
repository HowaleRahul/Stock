"""
Moving Average Crossover Setup.

Detects golden crosses (EMA-20 above EMA-50) and death crosses (EMA-20 below
EMA-50).  Confidence is scaled by the percentage separation between the two
EMAs relative to price.
"""

from __future__ import annotations

import pandas as pd

from setups.base import BaseSetup, SetupSignal
from setups.indicators import ema


class MACrossoverSetup(BaseSetup):
    name = "MA Crossover"

    # Configurable look-back windows
    fast_period: int = 20
    slow_period: int = 50

    def evaluate(self, df: pd.DataFrame) -> SetupSignal:
        close = df["close"]
        if len(close) < self.slow_period + 2:
            return SetupSignal(
                name=self.name,
                signal="neutral",
                confidence=0.0,
                reasoning=f"Insufficient data ({len(close)} bars, need {self.slow_period + 2}).",
            )

        ema_fast = ema(close, self.fast_period)
        ema_slow = ema(close, self.slow_period)

        # Current and previous values
        cur_fast = float(ema_fast.iloc[-1])
        cur_slow = float(ema_slow.iloc[-1])
        prev_fast = float(ema_fast.iloc[-2])
        prev_slow = float(ema_slow.iloc[-2])

        import numpy as np
        if any(np.isnan(v) for v in [cur_fast, cur_slow, prev_fast, prev_slow]):
            return SetupSignal(
                name=self.name,
                signal="neutral",
                confidence=0.0,
                reasoning="Moving average values contain NaN — insufficient data or missing bars.",
            )

        # Separation as fraction of current price
        price = close.iloc[-1]
        separation = abs(cur_fast - cur_slow) / price if price > 0 else 0.0

        # Scale confidence: 0 at 0% separation, 1.0 at ≥2% separation
        raw_conf = min(separation / 0.02, 1.0)

        # Detect crossover in the most recent bar
        crossed_up = prev_fast <= prev_slow and cur_fast > cur_slow
        crossed_down = prev_fast >= prev_slow and cur_fast < cur_slow

        if crossed_up:
            return SetupSignal(
                name=self.name,
                signal="bullish",
                confidence=max(raw_conf, 0.6),  # crossover itself is notable
                reasoning=(
                    f"Golden cross: EMA({self.fast_period}) crossed above "
                    f"EMA({self.slow_period}).  Separation: {separation*100:.2f}%."
                ),
                indicator_values={
                    "ema_fast_period": self.fast_period,
                    "ema_slow_period": self.slow_period,
                    "cross_type": "golden",
                },
            )

        if crossed_down:
            return SetupSignal(
                name=self.name,
                signal="bearish",
                confidence=max(raw_conf, 0.6),
                reasoning=(
                    f"Death cross: EMA({self.fast_period}) crossed below "
                    f"EMA({self.slow_period}).  Separation: {separation*100:.2f}%."
                ),
                indicator_values={
                    "ema_fast_period": self.fast_period,
                    "ema_slow_period": self.slow_period,
                    "cross_type": "death",
                },
            )

        # No crossover — report current trend
        if cur_fast > cur_slow:
            return SetupSignal(
                name=self.name,
                signal="bullish",
                confidence=raw_conf * 0.7,  # dampen when no fresh cross
                reasoning=(
                    f"EMA({self.fast_period}) is above EMA({self.slow_period}) "
                    f"(trend intact, separation {separation*100:.2f}%)."
                ),
                indicator_values={
                    "ema_fast_period": self.fast_period,
                    "ema_slow_period": self.slow_period,
                    "cross_type": "none",
                },
            )

        return SetupSignal(
            name=self.name,
            signal="bearish",
            confidence=raw_conf * 0.7,
            reasoning=(
                f"EMA({self.fast_period}) is below EMA({self.slow_period}) "
                f"(downtrend, separation {separation*100:.2f}%)."
            ),
            indicator_values={
                "ema_fast_period": self.fast_period,
                "ema_slow_period": self.slow_period,
                "cross_type": "none",
            },
        )
