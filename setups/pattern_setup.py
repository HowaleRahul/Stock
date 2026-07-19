from __future__ import annotations
import pandas as pd
import numpy as np
from scipy.signal import argrelextrema
from setups.base import BaseSetup, SetupSignal

class PatternSetup(BaseSetup):
    """
    Detects structural chart patterns like Double Tops and Double Bottoms
    by finding local extrema using scipy.
    """
    
    @property
    def name(self) -> str:
        return "Chart Patterns (Double Top/Bottom)"
        
    def evaluate(self, df: pd.DataFrame) -> SetupSignal:
        if len(df) < 30:
            return SetupSignal(self.name, "neutral", 0.0, "Need at least 30 bars to detect structural patterns.")
            
        try:
            close_prices = df['close'].values
            
            # Find local maxima and minima over a rolling window of 5 bars
            order = 5
            local_max = argrelextrema(close_prices, np.greater_equal, order=order)[0]
            local_min = argrelextrema(close_prices, np.less_equal, order=order)[0]
            
            if len(local_max) < 2 and len(local_min) < 2:
                return SetupSignal(self.name, "neutral", 0.0, "No major structural patterns forming.")
                
            last_price = close_prices[-1]
            tolerance = last_price * 0.015  # 1.5% tolerance for pattern matching
            
            # Check for Double Bottom (W pattern)
            if len(local_min) >= 2:
                last_two_min_idx = local_min[-2:]
                # Ensure they are reasonably spaced apart (e.g. at least 5 bars)
                if last_two_min_idx[1] - last_two_min_idx[0] >= 5:
                    min1 = close_prices[last_two_min_idx[0]]
                    min2 = close_prices[last_two_min_idx[1]]
                    
                    if abs(min1 - min2) <= tolerance:
                        # Ensure we are currently bouncing off it
                        if len(close_prices) - last_two_min_idx[1] <= 10 and last_price > min2:
                            return SetupSignal(self.name, "bullish", 0.8, f"Double Bottom forming around {min2:.2f}.")
                            
            # Check for Double Top (M pattern)
            if len(local_max) >= 2:
                last_two_max_idx = local_max[-2:]
                if last_two_max_idx[1] - last_two_max_idx[0] >= 5:
                    max1 = close_prices[last_two_max_idx[0]]
                    max2 = close_prices[last_two_max_idx[1]]
                    
                    if abs(max1 - max2) <= tolerance:
                        # Ensure we are currently rejecting from it
                        if len(close_prices) - last_two_max_idx[1] <= 10 and last_price < max2:
                            return SetupSignal(self.name, "bearish", 0.8, f"Double Top forming around {max2:.2f}.")
                            
            return SetupSignal(self.name, "neutral", 0.0, "No double tops or bottoms detected currently.")
            
        except Exception as e:
            return SetupSignal(self.name, "neutral", 0.0, f"Error detecting patterns: {str(e)}")
