from __future__ import annotations
import pandas as pd
import pandas_ta as ta
from setups.base import BaseSetup, SetupSignal

class CandlestickSetup(BaseSetup):
    """
    Detects powerful candlestick reversal patterns using pandas-ta.
    Focuses on: Engulfing, Hammer, Doji, and Morning/Evening Stars.
    """
    
    @property
    def name(self) -> str:
        return "Candlestick Patterns"
        
    def evaluate(self, df: pd.DataFrame) -> SetupSignal:
        if len(df) < 5:
            return SetupSignal(self.name, "neutral", 0.0, "Not enough data for candlestick patterns.")
            
        try:
            # We specifically target reliable reversal patterns
            engulfing = df.ta.cdl_engulfing()
            hammer = df.ta.cdl_hammer()
            doji = df.ta.cdl_doji()
            morning_star = df.ta.cdl_morningstar()
            evening_star = df.ta.cdl_eveningstar()
            
            # The TA-Lib style returns 100 for bullish, -100 for bearish, 0 for none.
            # Get the latest signal from each (last row)
            signals = []
            
            if engulfing is not None and len(engulfing) > 0:
                val = engulfing.iloc[-1]
                if val > 0: signals.append(("Bullish Engulfing", "bullish", 0.8))
                elif val < 0: signals.append(("Bearish Engulfing", "bearish", 0.8))
                
            if hammer is not None and len(hammer) > 0:
                if hammer.iloc[-1] > 0: signals.append(("Bullish Hammer", "bullish", 0.7))
                
            if morning_star is not None and len(morning_star) > 0:
                if morning_star.iloc[-1] > 0: signals.append(("Morning Star", "bullish", 0.9))
                
            if evening_star is not None and len(evening_star) > 0:
                if evening_star.iloc[-1] < 0: signals.append(("Evening Star", "bearish", 0.9))
                
            if doji is not None and len(doji) > 0:
                if doji.iloc[-1] > 0: signals.append(("Doji (Indecision)", "neutral", 0.5))
                
            if not signals:
                return SetupSignal(self.name, "neutral", 0.0, "No major candlestick patterns detected.")
                
            # Aggregate the strongest signal
            signals.sort(key=lambda x: x[2], reverse=True)
            top_signal = signals[0]
            
            all_patterns = ", ".join([s[0] for s in signals])
            
            return SetupSignal(
                name=self.name,
                signal=top_signal[1],
                confidence=top_signal[2],
                reasoning=f"Detected: {all_patterns}. The primary driver is {top_signal[0]}."
            )
            
        except Exception as e:
            return SetupSignal(self.name, "neutral", 0.0, f"Error calculating candlestick patterns: {e}")
