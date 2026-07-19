from __future__ import annotations
import pandas as pd
from setups.base import BaseSetup, SetupSignal

class FibonacciSetup(BaseSetup):
    """
    Detects if the current price is bouncing off major Fibonacci retracement levels
    (0.382 or 0.618) of the recent major swing (last 100 periods).
    """
    
    @property
    def name(self) -> str:
        return "Fibonacci Retracement"
        
    def evaluate(self, df: pd.DataFrame) -> SetupSignal:
        period = 100
        if len(df) < period:
            return SetupSignal(self.name, "neutral", 0.0, f"Needs {period} bars for Fib levels.")
            
        try:
            recent = df.iloc[-period:]
            swing_high = recent['high'].max()
            swing_low = recent['low'].min()
            
            diff = swing_high - swing_low
            if diff == 0:
                return SetupSignal(self.name, "neutral", 0.0, "No volatility for Fib levels.")
                
            # Golden ratio levels
            level_382 = swing_high - (0.382 * diff)
            level_618 = swing_high - (0.618 * diff)
            
            last_close = df['close'].iloc[-1]
            last_low = df['low'].iloc[-1]
            last_high = df['high'].iloc[-1]
            
            # Tolerance for a bounce is 1% of the swing diff
            tol = diff * 0.01
            
            # Bullish bounce: low touches fib, close is above
            bounce_382_bull = abs(last_low - level_382) <= tol and last_close > level_382
            bounce_618_bull = abs(last_low - level_618) <= tol and last_close > level_618
            
            # Bearish rejection: high touches fib, close is below
            reject_382_bear = abs(last_high - level_382) <= tol and last_close < level_382
            reject_618_bear = abs(last_high - level_618) <= tol and last_close < level_618
            
            if bounce_618_bull:
                return SetupSignal(self.name, "bullish", 0.75, f"Bounced cleanly off the 0.618 Golden Ratio ({level_618:.2f}).")
            if bounce_382_bull:
                return SetupSignal(self.name, "bullish", 0.65, f"Bounced off the 0.382 retracement level ({level_382:.2f}).")
                
            if reject_618_bear:
                return SetupSignal(self.name, "bearish", 0.75, f"Rejected sharply at the 0.618 Golden Ratio ({level_618:.2f}).")
            if reject_382_bear:
                return SetupSignal(self.name, "bearish", 0.65, f"Rejected at the 0.382 retracement level ({level_382:.2f}).")
                
            return SetupSignal(self.name, "neutral", 0.3, f"Between levels. 0.382={level_382:.2f}, 0.618={level_618:.2f}.")
            
        except Exception as e:
            return SetupSignal(self.name, "neutral", 0.0, f"Error: {str(e)}")
