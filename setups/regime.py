import pandas as pd
import pandas_ta as ta
from typing import Dict, Any

class RegimeDetector:
    """Detects market regime (trending vs range-bound) using ADX."""
    
    @staticmethod
    def detect(df: pd.DataFrame, adx_threshold: float = 25.0) -> Dict[str, Any]:
        """
        Returns regime information for the latest bar.
        
        Args:
            df: OHLCV DataFrame (ascending chronological).
            adx_threshold: Above this is trending, below is range-bound.
            
        Returns:
            Dict containing regime state, ADX value, and trend direction.
        """
        if len(df) < 20:
            return {"regime": "unknown", "adx": 0.0, "direction": "unknown"}
            
        try:
            # pandas-ta computes ADX, DMP, DMN
            adx_df = df.ta.adx(length=14)
            if adx_df is None or adx_df.empty:
                return {"regime": "unknown", "adx": 0.0, "direction": "unknown"}
                
            # ta.adx returns columns like ADX_14, DMP_14, DMN_14
            latest = adx_df.iloc[-1]
            adx_val = float(latest[0])  # First column is ADX
            dmp_val = float(latest[1])  # Second is +DI
            dmn_val = float(latest[2])  # Third is -DI
            
            if pd.isna(adx_val):
                return {"regime": "unknown", "adx": 0.0, "direction": "unknown"}
                
            is_trending = adx_val >= adx_threshold
            direction = "bullish" if dmp_val > dmn_val else "bearish"
            
            return {
                "regime": "trending" if is_trending else "range-bound",
                "adx": round(adx_val, 2),
                "direction": direction,
                "dmp": round(dmp_val, 2),
                "dmn": round(dmn_val, 2)
            }
        except Exception as e:
            return {"regime": "error", "adx": 0.0, "direction": "unknown", "error": str(e)}
