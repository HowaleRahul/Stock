"""
Options Setup: Real-Time Put-Call Ratio (PCR) & Derivative Sentiment

Enhanced with live NSE India Option Chain support from `nsepython` and `Bharat-SM-Data`:
- Direct NSE real-time option chain for Indian Indices (NIFTY, BANKNIFTY) and F&O equities.
- Calculates PCR (Open Interest & Volume) and Max-Pain level.
- Fallback to yfinance option chain if available with full test compatibility.
"""

from __future__ import annotations

import logging
import math
from typing import Optional
import pandas as pd
import yfinance as yf
from functools import lru_cache

from setups.base import BaseSetup, SetupSignal
from data.nse_feed import NSEFeed

logger = logging.getLogger("trading.setups.options")


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
    Evaluates real-time options market sentiment using Put-Call Ratio (PCR)
    and Max-Pain analysis from live NSE option chains with yfinance fallback.
    """

    @property
    def name(self) -> str:
        return "Options (Put-Call Ratio)"

    def evaluate(self, df: pd.DataFrame, ticker: str = "") -> SetupSignal:
        if not ticker:
            return SetupSignal(self.name, "neutral", 0.0, "No ticker provided.")

        clean_sym = NSEFeed.clean_symbol(ticker)

        # 1. Try real-time NSE Option Chain (Primary for Indian Markets)
        # Only try if ticker appears to be an index or F&O symbol
        if clean_sym in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY") or not ticker.endswith((".NS", ".BO", ".US")):
            try:
                chain = NSEFeed.get_option_chain_raw(clean_sym)
                if chain and "records" in chain:
                    pcr_oi, pcr_vol, put_oi, call_oi = NSEFeed.calculate_pcr(chain)
                    max_pain = NSEFeed.calculate_max_pain(chain)

                    mp_str = f" | Max Pain: ₹{max_pain:,.0f}" if max_pain else ""
                    reason = f"NSE Live PCR (OI): {pcr_oi:.2f} (Vol: {pcr_vol:.2f}){mp_str}"

                    indicator_vals = {
                        "pcr_oi": pcr_oi,
                        "pcr_vol": pcr_vol,
                        "max_pain": max_pain,
                        "total_put_oi": put_oi,
                        "total_call_oi": call_oi,
                    }

                    if pcr_oi > 1.25:
                        return SetupSignal(
                            self.name,
                            "bullish",
                            min(0.85, 0.5 + (pcr_oi - 1.25) * 0.4),
                            reason + " — Strong put writing/support base; bullish undertone.",
                            indicator_values=indicator_vals,
                        )
                    elif pcr_oi < 0.75:
                        return SetupSignal(
                            self.name,
                            "bearish",
                            min(0.85, 0.5 + (0.75 - pcr_oi) * 0.4),
                            reason + " — Heavy call writing/overhead resistance; bearish pressure.",
                            indicator_values=indicator_vals,
                        )
                    else:
                        return SetupSignal(
                            self.name,
                            "neutral",
                            0.4,
                            reason + " — Derivative positioning is balanced.",
                            indicator_values=indicator_vals,
                        )
            except Exception as e:
                logger.debug(f"NSE direct options evaluation note: {e}")

        # 2. Yahoo Finance options (standard fallback + unit test interface)
        try:
            nearest_exp, opt = get_options_data(ticker)

            if not opt:
                return SetupSignal(self.name, "neutral", 0.0, "No options data available for this ticker.")

            calls = opt.calls
            puts = opt.puts

            if calls.empty or puts.empty:
                return SetupSignal(self.name, "neutral", 0.0, "Incomplete options data.")

            if "openInterest" not in calls.columns or "openInterest" not in puts.columns:
                return SetupSignal(self.name, "neutral", 0.0, "Open Interest data not found in option chain.")

            total_call_oi = float(calls["openInterest"].fillna(0).sum())
            total_put_oi = float(puts["openInterest"].fillna(0).sum())

            if math.isnan(total_call_oi) or total_call_oi <= 0:
                return SetupSignal(self.name, "neutral", 0.0, "No Call Open Interest.")

            pcr = total_put_oi / total_call_oi
            if math.isnan(pcr):
                return SetupSignal(self.name, "neutral", 0.0, "Could not calculate Put-Call Ratio.")

            reason = f"PCR for {nearest_exp} expiry is {pcr:.2f}. (Puts OI: {total_put_oi:,.0f}, Calls OI: {total_call_oi:,.0f})"

            if pcr > 1.2:
                return SetupSignal(self.name, "bearish", 0.7, reason + " High put-call ratio suggests bearish sentiment.")
            elif pcr < 0.7:
                return SetupSignal(self.name, "bullish", 0.7, reason + " Low put-call ratio suggests bullish sentiment.")
            else:
                return SetupSignal(self.name, "neutral", 0.4, reason + " PCR is balanced.")

        except Exception as e:
            return SetupSignal(self.name, "neutral", 0.0, f"Error analyzing options: {str(e)}")
