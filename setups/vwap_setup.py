from __future__ import annotations
import pandas as pd
import pandas_ta as ta
from setups.base import BaseSetup, SetupSignal

class VWAPSetup(BaseSetup):
    """
    Evaluates Volume Weighted Average Price (VWAP) combined with volume spikes.
    Strong signals occur when price crosses VWAP accompanied by volume > 2x average.
    """
    
    @property
    def name(self) -> str:
        return "VWAP & Volume"
        
    def evaluate(self, df: pd.DataFrame) -> SetupSignal:
        if len(df) < 20 or 'volume' not in df.columns:
            return SetupSignal(self.name, "neutral", 0.0, "Insufficient data or missing volume.")
            
        try:
            # We need a datetime index for accurate anchored VWAP, but pandas_ta
            # handles it gracefully. We use standard VWAP.
            vwap = df.ta.vwap()
            if vwap is None or vwap.empty:
                return SetupSignal(self.name, "neutral", 0.0, "Could not calculate VWAP.")
                
            # Volume 20-period SMA
            vol_sma = df['volume'].rolling(20).mean()
            
            c = df['close'].values
            v = df['volume'].values
            vs = vol_sma.values
            vw = vwap.values
            
            last_close = c[-1]
            last_vwap = vw[-1]
            prev_close = c[-2]
            prev_vwap = vw[-2]
            
            last_vol = v[-1]
            last_vol_sma = vs[-1]
            
            # Identify volume spike (> 1.5x average)
            vol_spike = last_vol > (1.5 * last_vol_sma)
            
            # Crossover logic
            cross_up = prev_close < prev_vwap and last_close > last_vwap
            cross_down = prev_close > prev_vwap and last_close < last_vwap
            
            if cross_up:
                conf = 0.85 if vol_spike else 0.55
                reason = f"Price crossed above VWAP ({last_vwap:.2f})."
                if vol_spike:
                    reason += f" Accompanied by high volume spike ({last_vol:,.0f})."
                return SetupSignal(self.name, "bullish", conf, reason)
                
            if cross_down:
                conf = 0.85 if vol_spike else 0.55
                reason = f"Price crossed below VWAP ({last_vwap:.2f})."
                if vol_spike:
                    reason += f" Accompanied by high volume spike ({last_vol:,.0f})."
                return SetupSignal(self.name, "bearish", conf, reason)
                
            # If no crossover, just check where price is relative to VWAP
            if last_close > last_vwap:
                return SetupSignal(self.name, "bullish", 0.4, f"Trending above VWAP ({last_vwap:.2f}).")
            else:
                return SetupSignal(self.name, "bearish", 0.4, f"Trending below VWAP ({last_vwap:.2f}).")
                
        except Exception as e:
            return SetupSignal(self.name, "neutral", 0.0, f"Error: {str(e)}")
