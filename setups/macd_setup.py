"""
MACD (Moving Average Convergence Divergence) Setup.

Detects MACD-line / signal-line crossovers and histogram momentum shifts.
Confidence is scaled by histogram magnitude relative to recent range.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from setups.base import BaseSetup, SetupSignal
from setups.indicators import macd as calc_macd


class MACDSetup(BaseSetup):
    name = "MACD"

    fast: int = 12
    slow: int = 26
    signal_period: int = 9

    def evaluate(self, df: pd.DataFrame) -> SetupSignal:
        close = df["close"]
        min_bars = self.slow + self.signal_period + 2
        if len(close) < min_bars:
            return SetupSignal(
                name=self.name,
                signal="neutral",
                confidence=0.0,
                reasoning=f"Insufficient data ({len(close)} bars, need {min_bars}).",
            )

        macd_line, signal_line, histogram = calc_macd(
            close, self.fast, self.slow, self.signal_period
        )

        # Current and previous valid values
        cur_macd = float(macd_line.iloc[-1])
        cur_signal = float(signal_line.iloc[-1])
        cur_hist = float(histogram.iloc[-1])
        prev_macd = float(macd_line.iloc[-2])
        prev_signal = float(signal_line.iloc[-2])

        if any(np.isnan(v) for v in [cur_macd, cur_signal, cur_hist, prev_macd, prev_signal]):
            return SetupSignal(
                name=self.name,
                signal="neutral",
                confidence=0.0,
                reasoning="MACD values contain NaN — insufficient convergence window.",
            )

        # Histogram range for confidence scaling
        valid_hist = histogram.dropna()
        if len(valid_hist) > 0:
            hist_range = float(valid_hist.abs().quantile(0.95))
            if hist_range == 0:
                hist_range = 1.0
        else:
            hist_range = 1.0

        raw_conf = min(abs(cur_hist) / hist_range, 1.0)

        # Detect crossover
        crossed_up = prev_macd <= prev_signal and cur_macd > cur_signal
        crossed_down = prev_macd >= prev_signal and cur_macd < cur_signal

        if crossed_up:
            return SetupSignal(
                name=self.name,
                signal="bullish",
                confidence=max(raw_conf, 0.55),
                reasoning=(
                    f"MACD crossed above signal line.  Histogram: {cur_hist:+.4f}.  "
                    f"Bullish momentum building."
                ),
                indicator_values={
                    "macd": cur_macd,
                    "signal": cur_signal,
                    "histogram": cur_hist,
                    "crossover": "bullish",
                },
            )

        if crossed_down:
            return SetupSignal(
                name=self.name,
                signal="bearish",
                confidence=max(raw_conf, 0.55),
                reasoning=(
                    f"MACD crossed below signal line.  Histogram: {cur_hist:+.4f}.  "
                    f"Bearish momentum building."
                ),
                indicator_values={
                    "macd": cur_macd,
                    "signal": cur_signal,
                    "histogram": cur_hist,
                    "crossover": "bearish",
                },
            )

        # No crossover — directional lean from histogram sign
        if cur_hist > 0:
            return SetupSignal(
                name=self.name,
                signal="bullish",
                confidence=raw_conf * 0.6,
                reasoning=(
                    f"MACD above signal (histogram {cur_hist:+.4f}).  "
                    f"Bullish momentum intact."
                ),
                indicator_values={
                    "macd": cur_macd,
                    "signal": cur_signal,
                    "histogram": cur_hist,
                    "crossover": "none",
                },
            )

        return SetupSignal(
            name=self.name,
            signal="bearish",
            confidence=raw_conf * 0.6,
            reasoning=(
                f"MACD below signal (histogram {cur_hist:+.4f}).  "
                f"Bearish momentum intact."
            ),
            indicator_values={
                "macd": cur_macd,
                "signal": cur_signal,
                "histogram": cur_hist,
                "crossover": "none",
            },
        )
