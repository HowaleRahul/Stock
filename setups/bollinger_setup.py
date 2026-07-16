"""
Bollinger Bands Setup.

Detects mean-reversion signals when price touches or breaks the outer bands,
and volatility squeezes (bandwidth contraction) that precede big moves.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from setups.base import BaseSetup, SetupSignal
from setups.indicators import bollinger_bands


class BollingerBandsSetup(BaseSetup):
    name = "Bollinger Bands"

    period: int = 20
    std_dev: float = 2.0

    def evaluate(self, df: pd.DataFrame) -> SetupSignal:
        close = df["close"]
        if len(close) < self.period + 2:
            return SetupSignal(
                name=self.name,
                signal="neutral",
                confidence=0.0,
                reasoning=f"Insufficient data ({len(close)} bars, need {self.period + 2}).",
            )

        upper, middle, lower = bollinger_bands(close, self.period, self.std_dev)

        cur_close = float(close.iloc[-1])
        cur_upper = float(upper.iloc[-1])
        cur_middle = float(middle.iloc[-1])
        cur_lower = float(lower.iloc[-1])

        if any(np.isnan(v) for v in [cur_upper, cur_middle, cur_lower]):
            return SetupSignal(
                name=self.name,
                signal="neutral",
                confidence=0.0,
                reasoning="Bollinger Bands contain NaN.",
            )

        band_width = cur_upper - cur_lower
        if cur_middle > 0:
            bandwidth_pct = band_width / cur_middle * 100
        else:
            bandwidth_pct = 0.0

        # %B (Percent B): where the price sits within the bands
        # %B < 0 → below lower band, %B > 1 → above upper band
        if band_width > 0:
            pct_b = (cur_close - cur_lower) / band_width
        else:
            pct_b = 0.5  # flat bands → neutral

        # ── Price at/below lower band → bullish bounce ──────────────
        if pct_b <= 0.0:
            # Below the lower band — strong mean-reversion signal
            overshoot = abs(pct_b)
            confidence = min(0.6 + overshoot * 0.4, 1.0)
            return SetupSignal(
                name=self.name,
                signal="bullish",
                confidence=confidence,
                reasoning=(
                    f"Price ({cur_close:.2f}) broke below lower Bollinger Band "
                    f"({cur_lower:.2f}).  %B = {pct_b:.2f}.  "
                    f"Mean-reversion bounce expected."
                ),
                indicator_values={
                    "pct_b": pct_b,
                    "bandwidth_pct": bandwidth_pct,
                },
            )

        if pct_b <= 0.15:
            # Near the lower band
            confidence = 0.3 + (0.15 - pct_b) / 0.15 * 0.3
            return SetupSignal(
                name=self.name,
                signal="bullish",
                confidence=confidence,
                reasoning=(
                    f"Price ({cur_close:.2f}) near lower Bollinger Band "
                    f"({cur_lower:.2f}).  %B = {pct_b:.2f}.  "
                    f"Potential mean-reversion bounce."
                ),
                indicator_values={
                    "pct_b": pct_b,
                    "bandwidth_pct": bandwidth_pct,
                },
            )

        # ── Price at/above upper band → bearish pullback ────────────
        if pct_b >= 1.0:
            overshoot = pct_b - 1.0
            confidence = min(0.6 + overshoot * 0.4, 1.0)
            return SetupSignal(
                name=self.name,
                signal="bearish",
                confidence=confidence,
                reasoning=(
                    f"Price ({cur_close:.2f}) broke above upper Bollinger Band "
                    f"({cur_upper:.2f}).  %B = {pct_b:.2f}.  "
                    f"Overbought pullback likely."
                ),
                indicator_values={
                    "pct_b": pct_b,
                    "bandwidth_pct": bandwidth_pct,
                },
            )

        if pct_b >= 0.85:
            confidence = 0.3 + (pct_b - 0.85) / 0.15 * 0.3
            return SetupSignal(
                name=self.name,
                signal="bearish",
                confidence=confidence,
                reasoning=(
                    f"Price ({cur_close:.2f}) near upper Bollinger Band "
                    f"({cur_upper:.2f}).  %B = {pct_b:.2f}.  "
                    f"Potential overbought pullback."
                ),
                indicator_values={
                    "pct_b": pct_b,
                    "bandwidth_pct": bandwidth_pct,
                },
            )

        # ── Neutral — price within bands ────────────────────────────
        squeeze_note = ""
        if bandwidth_pct < 5.0:
            squeeze_note = (
                f"  Volatility squeeze detected (bandwidth {bandwidth_pct:.1f}%) — "
                f"a large move may be imminent."
            )

        return SetupSignal(
            name=self.name,
            signal="neutral",
            confidence=0.0,
            reasoning=(
                f"Price ({cur_close:.2f}) within Bollinger Bands "
                f"({cur_lower:.2f} – {cur_upper:.2f}).  "
                f"%B = {pct_b:.2f}, bandwidth = {bandwidth_pct:.1f}%.{squeeze_note}"
            ),
            indicator_values={
                "pct_b": pct_b,
                "bandwidth_pct": bandwidth_pct,
            },
        )
