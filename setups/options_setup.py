import pandas as pd
import yfinance as yf
from functools import lru_cache
from setups.base import BaseSetup, SetupSignal

@lru_cache(maxsize=128)
def get_options_data(ticker: str):
    stock = yf.Ticker(ticker)
    expirations = stock.options
    if not expirations:
        return None, None
    nearest_exp = expirations[0]
    return nearest_exp, stock.option_chain(nearest_exp)

class OptionsSetup(BaseSetup):
    """
    Evaluates options data for the nearest expiration date.
    Calculates Put-Call Ratio (PCR) based on Open Interest.
    """
    
    @property
    def name(self) -> str:
        return "Options (Put-Call Ratio)"
        
    def evaluate(self, df: pd.DataFrame, ticker: str = "") -> SetupSignal:
        if not ticker:
            return SetupSignal(self.name, "neutral", 0.0, "No ticker provided.")
            
        try:
            nearest_exp, opt = get_options_data(ticker)
            
            if not opt:
                return SetupSignal(self.name, "neutral", 0.0, "No options data available for this ticker.")
            
            calls = opt.calls
            puts = opt.puts
            
            if calls.empty or puts.empty:
                return SetupSignal(self.name, "neutral", 0.0, "Incomplete options data.")
                
            if 'openInterest' not in calls.columns or 'openInterest' not in puts.columns:
                return SetupSignal(self.name, "neutral", 0.0, "Open Interest data not found in option chain.")

            total_call_oi = float(calls['openInterest'].fillna(0).sum())
            total_put_oi = float(puts['openInterest'].fillna(0).sum())
            
            import math
            if math.isnan(total_call_oi) or total_call_oi <= 0:
                return SetupSignal(self.name, "neutral", 0.0, "No Call Open Interest.")
                
            pcr = total_put_oi / total_call_oi
            if math.isnan(pcr):
                return SetupSignal(self.name, "neutral", 0.0, "Could not calculate Put-Call Ratio.")
            
            reason = f"PCR for {nearest_exp} expiry is {pcr:.2f}. (Puts OI: {total_put_oi:,.0f}, Calls OI: {total_call_oi:,.0f})"
            
            # PCR > 1 typically implies heavy put buying (bearish sentiment)
            if pcr > 1.2:
                return SetupSignal(self.name, "bearish", 0.7, reason + " High put-call ratio suggests bearish sentiment.")
            elif pcr < 0.7:
                return SetupSignal(self.name, "bullish", 0.7, reason + " Low put-call ratio suggests bullish sentiment.")
            else:
                return SetupSignal(self.name, "neutral", 0.4, reason + " PCR is balanced.")
                
        except Exception as e:
            return SetupSignal(self.name, "neutral", 0.0, f"Error analyzing options: {str(e)}")
