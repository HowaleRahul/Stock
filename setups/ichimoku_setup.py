from __future__ import annotations
import pandas as pd
import pandas_ta as ta
from setups.base import BaseSetup, SetupSignal

class IchimokuSetup(BaseSetup):
    """
    Detects Ichimoku Kumo (Cloud) Breakouts.
    A bullish signal is generated when price crosses above the cloud.
    A bearish signal when price crosses below the cloud.
    """
    
    @property
    def name(self) -> str:
        return "Ichimoku Cloud"
        
    def evaluate(self, df: pd.DataFrame) -> SetupSignal:
        if len(df) < 52:
            return SetupSignal(self.name, "neutral", 0.0, "Needs 52 bars for Ichimoku.")
            
        try:
            # df.ta.ichimoku() returns (ichimoku_df, span_df)
            ichi = df.ta.ichimoku()
            if ichi is None or len(ichi) < 2 or ichi[0] is None or ichi[0].empty:
                return SetupSignal(self.name, "neutral", 0.0, "Could not calculate Ichimoku.")
                
            ichi_df = ichi[0]
            
            # Columns usually look like: ISA_9, ISB_26, ITS_9, IKS_26, ICS_26
            # We care about ISA (Senkou Span A) and ISB (Senkou Span B)
            span_a_col = [c for c in ichi_df.columns if c.startswith('ISA_')][0]
            span_b_col = [c for c in ichi_df.columns if c.startswith('ISB_')][0]
            
            span_a = ichi_df[span_a_col].values
            span_b = ichi_df[span_b_col].values
            close = df['close'].values
            
            c = close[-1]
            prev_c = close[-2]
            
            a = span_a[-1]
            b = span_b[-1]
            prev_a = span_a[-2]
            prev_b = span_b[-2]
            
            if pd.isna(a) or pd.isna(b):
                return SetupSignal(self.name, "neutral", 0.0, "Ichimoku Cloud values are NaN.")
                
            cloud_top = max(a, b)
            cloud_bottom = min(a, b)
            prev_cloud_top = max(prev_a, prev_b)
            prev_cloud_bottom = min(prev_a, prev_b)
            
            # Breakout logic
            cross_up = prev_c <= prev_cloud_top and c > cloud_top
            cross_down = prev_c >= prev_cloud_bottom and c < cloud_bottom
            
            if cross_up:
                return SetupSignal(self.name, "bullish", 0.85, f"Kumo Breakout: Price crossed above the cloud ({cloud_top:.2f}).")
            if cross_down:
                return SetupSignal(self.name, "bearish", 0.85, f"Kumo Breakdown: Price crossed below the cloud ({cloud_bottom:.2f}).")
                
            if c > cloud_top:
                return SetupSignal(self.name, "bullish", 0.5, "Trending above the cloud.")
            elif c < cloud_bottom:
                return SetupSignal(self.name, "bearish", 0.5, "Trending below the cloud.")
            else:
                return SetupSignal(self.name, "neutral", 0.3, "Chopping inside the cloud (No Trade Zone).")
                
        except Exception as e:
            return SetupSignal(self.name, "neutral", 0.0, f"Error: {str(e)}")
