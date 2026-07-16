"""
Support / Resistance Breakout Setup.

Identifies key S/R levels from recent pivot highs and lows, then checks
whether the latest close has broken through with volume confirmation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from setups.base import BaseSetup, SetupSignal
from setups.indicators import find_support_resistance, sma


class BreakoutSetup(BaseSetup):
    name = "S/R Breakout"

    lookback: int = 50
    num_levels: int = 3
    vol_avg_period: int = 20

    def evaluate(self, df: pd.DataFrame) -> SetupSignal:
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        min_bars = max(self.lookback, self.vol_avg_period) + 2
        if len(close) < min_bars:
            return SetupSignal(
                name=self.name,
                signal="neutral",
                confidence=0.0,
                reasoning=f"Insufficient data ({len(close)} bars, need {min_bars}).",
            )

        levels = find_support_resistance(
            close, high, low,
            lookback=self.lookback,
            num_levels=self.num_levels,
        )

        cur_close = float(close.iloc[-1])
        prev_close = float(close.iloc[-2])

        if np.isnan(cur_close) or np.isnan(prev_close):
            return SetupSignal(
                name=self.name,
                signal="neutral",
                confidence=0.0,
                reasoning="Price data contains NaN.",
            )

        # Volume confirmation
        avg_vol = sma(volume, self.vol_avg_period)
        cur_vol = float(volume.iloc[-1])
        avg_vol_val = float(avg_vol.iloc[-1]) if not np.isnan(avg_vol.iloc[-1]) else cur_vol
        if np.isnan(cur_vol) or np.isnan(avg_vol_val) or avg_vol_val <= 0:
            vol_ratio = 1.0
        else:
            vol_ratio = cur_vol / avg_vol_val

        support_levels = [l for l in levels["support"] if not np.isnan(l) and l > 0]
        resistance_levels = [l for l in levels["resistance"] if not np.isnan(l) and l > 0]

        # ── Check for resistance breakout ───────────────────────────
        for res_level in resistance_levels:
            if prev_close <= res_level and cur_close > res_level:
                # Volume boost confidence
                vol_boost = min(vol_ratio / 1.5, 1.0)  # vol_ratio ≥ 1.5 → max boost
                confidence = 0.4 + 0.3 * vol_boost

                # Price overshoot boost
                overshoot_pct = (cur_close - res_level) / res_level * 100
                confidence += min(overshoot_pct / 2.0, 0.3)
                confidence = min(confidence, 1.0)

                vol_note = (
                    f"Volume is {vol_ratio:.1f}x average — "
                    + ("strong confirmation." if vol_ratio >= 1.5 else "weak confirmation.")
                )

                return SetupSignal(
                    name=self.name,
                    signal="bullish",
                    confidence=confidence,
                    reasoning=(
                        f"Price broke above resistance at {res_level:.2f} "
                        f"(close: {cur_close:.2f}).  {vol_note}"
                    ),
                    indicator_values={
                        "breakout_level": res_level,
                        "breakout_type": "resistance",
                        "volume_ratio": vol_ratio,
                        "support_levels": support_levels,
                        "resistance_levels": resistance_levels,
                    },
                )

        # ── Check for support breakdown ─────────────────────────────
        for sup_level in support_levels:
            if prev_close >= sup_level and cur_close < sup_level:
                vol_boost = min(vol_ratio / 1.5, 1.0)
                confidence = 0.4 + 0.3 * vol_boost
                breakdown_pct = (sup_level - cur_close) / sup_level * 100
                confidence += min(breakdown_pct / 2.0, 0.3)
                confidence = min(confidence, 1.0)

                vol_note = (
                    f"Volume is {vol_ratio:.1f}x average — "
                    + ("strong confirmation." if vol_ratio >= 1.5 else "weak confirmation.")
                )

                return SetupSignal(
                    name=self.name,
                    signal="bearish",
                    confidence=confidence,
                    reasoning=(
                        f"Price broke below support at {sup_level:.2f} "
                        f"(close: {cur_close:.2f}).  {vol_note}"
                    ),
                    indicator_values={
                        "breakout_level": sup_level,
                        "breakout_type": "support",
                        "volume_ratio": vol_ratio,
                        "support_levels": support_levels,
                        "resistance_levels": resistance_levels,
                    },
                )

        # ── No breakout ─────────────────────────────────────────────
        # Report proximity to nearest levels
        nearest_sup = f"{support_levels[0]:.2f}" if support_levels else "none"
        nearest_res = f"{resistance_levels[0]:.2f}" if resistance_levels else "none"

        return SetupSignal(
            name=self.name,
            signal="neutral",
            confidence=0.0,
            reasoning=(
                f"No breakout detected.  "
                f"Nearest support: {nearest_sup}, resistance: {nearest_res}.  "
                f"Price: {cur_close:.2f}, volume ratio: {vol_ratio:.1f}x."
            ),
            indicator_values={
                "volume_ratio": vol_ratio,
                "support_levels": support_levels,
                "resistance_levels": resistance_levels,
            },
        )
