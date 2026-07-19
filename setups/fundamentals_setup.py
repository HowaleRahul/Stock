from __future__ import annotations
import pandas as pd
import yfinance as yf
from setups.base import BaseSetup, SetupSignal

class FundamentalsSetup(BaseSetup):
    """
    Evaluates basic fundamental valuation (P/E ratio, PEG ratio) using yfinance.
    Note: Can be slow as it hits the Yahoo Finance API.
    """
    
    @property
    def name(self) -> str:
        return "Fundamentals Valuation"
        
    def evaluate(self, df: pd.DataFrame, ticker: str = "") -> SetupSignal:
        if not ticker:
            return SetupSignal(self.name, "neutral", 0.0, "No ticker provided.")
            
        try:
            # We strip any Yahoo Finance suffixes if needed, but assuming ticker is ready.
            stock = yf.Ticker(ticker)
            info = stock.info
            
            if not info or "trailingPE" not in info:
                return SetupSignal(self.name, "neutral", 0.0, "Fundamental data not available.")
                
            pe = info.get("trailingPE")
            fwd_pe = info.get("forwardPE")
            peg = info.get("pegRatio")
            industry_pe = info.get("industryPE")  # Sometimes missing
            
            reason = f"Trailing P/E: {pe}."
            if fwd_pe:
                reason += f" Forward P/E: {fwd_pe}."
                
            # Basic value heuristic
            # If P/E < 15, it's considered cheap (bullish)
            # If P/E > 30, it's considered expensive (bearish)
            # This is highly sector dependent, so we keep confidence low.
            
            if pe > 40:
                return SetupSignal(self.name, "bearish", 0.6, reason + " Valuation is very high (expensive).")
            elif pe < 15:
                return SetupSignal(self.name, "bullish", 0.6, reason + " Valuation is relatively low (value play).")
            else:
                return SetupSignal(self.name, "neutral", 0.3, reason + " Valuation is in standard range.")
                
        except Exception as e:
            return SetupSignal(self.name, "neutral", 0.0, f"Error fetching fundamentals: {str(e)}")
