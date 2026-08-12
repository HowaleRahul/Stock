"""
Psychology Setup.

Models 'Smart Money' trading by detecting retail trader psychological traps.
Instead of following momentum, this setup looks for FOMO exhaustion, 
panic capitulation, and stop-hunting around major psychological round numbers.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from setups.base import BaseSetup, SetupSignal


class PsychologySetup(BaseSetup):
    name = "Smart Money Psychology"

    def evaluate(self, df: pd.DataFrame) -> SetupSignal:
        if len(df) < 20:
            return SetupSignal(
                name=self.name,
                signal="neutral",
                confidence=0.0,
                reasoning="Not enough data for psychology baseline.",
            )

        # We assume the psychology features have already been computed and appended to the df
        required_cols = ['psych_fomo_streak', 'psych_panic_index', 'psych_dist_to_round', 'psych_session_phase']
        if not all(col in df.columns for col in required_cols):
            return SetupSignal(
                name=self.name,
                signal="neutral",
                confidence=0.0,
                reasoning="Psychological features not found in DataFrame.",
            )

        cur_fomo = float(df['psych_fomo_streak'].iloc[-1])
        cur_panic = float(df['psych_panic_index'].iloc[-1])
        cur_dist = float(df['psych_dist_to_round'].iloc[-1])
        
        # Calculate recent EMA to see if we are stretched
        ema_20 = df['close'].rolling(20).mean().iloc[-1]
        close = float(df['close'].iloc[-1])
        open_price = float(df['open'].iloc[-1])
        
        extension_pct = (close - ema_20) / ema_20
        
        # 1. FOMO Exhaustion (Smart Money Short)
        # Retail sees 4+ green candles and massive extension, so they buy. Smart Money shorts.
        if cur_fomo >= 4 and extension_pct > 0.015:
            conf = min((cur_fomo - 3) * 0.2 + (extension_pct * 10), 1.0)
            return SetupSignal(
                name=self.name,
                signal="bearish",
                confidence=conf,
                reasoning=f"Extreme Greed FOMO detected ({cur_fomo} green candles). Smart money fading retail buyers.",
                indicator_values={"fomo": cur_fomo, "panic": cur_panic, "dist_to_round": cur_dist}
            )
            
        # 2. Panic Capitulation (Smart Money Long)
        # Retail panics and dumps, creating huge lower wicks on high volume. Smart Money absorbs it.
        # Retail sees 4+ red candles and shorts. Smart Money buys.
        if cur_fomo <= -4 and extension_pct < -0.015:
            conf = min((abs(cur_fomo) - 3) * 0.2 + (abs(extension_pct) * 10), 1.0)
            return SetupSignal(
                name=self.name,
                signal="bullish",
                confidence=conf,
                reasoning=f"Extreme Panic Capitulation ({abs(cur_fomo)} red candles). Smart money accumulating.",
                indicator_values={"fomo": cur_fomo, "panic": cur_panic, "dist_to_round": cur_dist}
            )
            
        # 3. Stop-Hunt Reversal around Psychological Numbers
        # If we are extremely close to a round number (< 0.1% away) and the candle rejected it
        if cur_dist < 0.001:
            # Bullish Stop Hunt: Price dipped below the round number, hit retail stops, and closed above open
            if close > open_price and df['low'].iloc[-1] < (close * (1 - cur_dist)):
                return SetupSignal(
                    name=self.name,
                    signal="bullish",
                    confidence=0.8,
                    reasoning="Bullish Stop Hunt: Swept retail stops below round number and recovered.",
                    indicator_values={"fomo": cur_fomo, "panic": cur_panic, "dist_to_round": cur_dist}
                )
            
            # Bearish Stop Hunt: Price spiked above the round number, hit retail stops, and closed below open
            if close < open_price and df['high'].iloc[-1] > (close * (1 + cur_dist)):
                return SetupSignal(
                    name=self.name,
                    signal="bearish",
                    confidence=0.8,
                    reasoning="Bearish Stop Hunt: Swept retail stops above round number and rejected.",
                    indicator_values={"fomo": cur_fomo, "panic": cur_panic, "dist_to_round": cur_dist}
                )

        # No extreme emotional setups present
        return SetupSignal(
            name=self.name,
            signal="neutral",
            confidence=0.0,
            reasoning="Retail psychology is stable. No obvious traps to fade.",
            indicator_values={"fomo": cur_fomo, "panic": cur_panic, "dist_to_round": cur_dist}
        )
