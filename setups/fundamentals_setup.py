import pandas as pd
import yfinance as yf
from functools import lru_cache
from setups.base import BaseSetup, SetupSignal

@lru_cache(maxsize=128)
def get_fundamentals(ticker: str) -> dict:
    stock = yf.Ticker(ticker)
    return stock.info

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
            info = get_fundamentals(ticker)
            
            pe_raw = info.get("trailingPE")
            if not info or pe_raw is None:
                return SetupSignal(self.name, "neutral", 0.0, "Fundamental data not available.")
                
            try:
                pe = float(pe_raw)
            except (ValueError, TypeError):
                return SetupSignal(self.name, "neutral", 0.0, "Fundamental data not available.")
                
            fwd_pe = info.get("forwardPE")
            peg = info.get("pegRatio")
            industry_pe = info.get("industryPE")  # Sometimes missing
            
            reason = f"Trailing P/E: {pe:.2f}."
            if fwd_pe is not None:
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
