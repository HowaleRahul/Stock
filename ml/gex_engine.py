"""
Institutional Gamma Exposure (GEX) & Dealer Positioning Engine

Incorporates the Gamma-Exposure framework from `staskh/trading_skills`:
- Evaluates Dealer positioning across strike chains:
  - Net GEX > 0: Positive Gamma (Vol dampening, mean-reverting pin regime)
  - Net GEX < 0: Negative Gamma (Vol explosive, breakout acceleration regime)
- Identifies:
  - Gamma Flip Level (pivot boundary between trending vs mean-reverting)
  - Call Wall (major upside pinning / resistance barrier)
  - Put Wall (major downside pinning / support floor)
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import scipy.stats as si

logger = logging.getLogger("trading.ml.gex")


class GEXEngine:
    """Calculates dealer gamma exposure (GEX) across option chains."""

    @staticmethod
    def calculate_gamma(S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Calculates per-share option gamma using Black-Scholes."""
        if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
            return 0.0
        denom = sigma * math.sqrt(T)
        if denom <= 1e-9:
            return 0.0
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / denom
        gamma = si.norm.pdf(d1, 0.0, 1.0) / (S * denom)
        return float(gamma) if not math.isnan(gamma) else 0.0

    @classmethod
    def analyze_chain_gex(
        cls,
        spot: float,
        strikes_data: List[Dict[str, Any]],
        lot_size: int = 25,
        iv: float = 0.15,
        days_to_expiry: float = 7.0,
        r: float = 0.065,
    ) -> Dict[str, Any]:
        """
        Analyzes full strike chain for Gamma Exposure.

        Args:
            spot: Current underlying index spot price
            strikes_data: List of dicts with:
                {"strike": float, "call_oi": int, "put_oi": int, "call_vol": int, "put_vol": int}
            lot_size: Index lot size (e.g. 25 for NIFTY, 15 for BANKNIFTY)
            iv: Implied volatility proxy
            days_to_expiry: Time remaining in days
        """
        if spot <= 0 or not strikes_data:
            return {
                "net_gex_crores": 0.0,
                "regime": "NEUTRAL",
                "gamma_flip": spot,
                "call_wall": spot,
                "put_wall": spot,
                "volatility_bias": "BALANCED",
            }

        T = max(0.001, days_to_expiry / 365.0)

        total_call_gex = 0.0
        total_put_gex = 0.0

        strike_gex_map: Dict[float, Dict[str, float]] = {}

        for row in strikes_data:
            k = float(row.get("strike", 0.0))
            if k <= 0:
                continue

            c_oi = float(row.get("call_oi", 0.0))
            p_oi = float(row.get("put_oi", 0.0))

            gamma = cls.calculate_gamma(spot, k, T, r, iv)

            # Dollar gamma per 1% move: gamma * OI * lot_size * spot * spot * 0.01
            # In INR Crores: divide by 10,000,000 (1 Crore = 10^7 INR)
            c_gex = (gamma * c_oi * lot_size * (spot ** 2) * 0.01) / 1e7
            # Dealers assumed short puts -> put gamma is negative for dealers
            p_gex = (gamma * p_oi * lot_size * (spot ** 2) * 0.01) / 1e7

            total_call_gex += c_gex
            total_put_gex += p_gex

            strike_gex_map[k] = {
                "call_gex": c_gex,
                "put_gex": p_gex,
                "net_strike_gex": c_gex - p_gex,
            }

        net_gex = total_call_gex - total_put_gex

        # Identify Call Wall (strike with highest call GEX / resistance pin)
        call_wall = max(strike_gex_map.keys(), key=lambda k: strike_gex_map[k]["call_gex"], default=spot)
        # Identify Put Wall (strike with highest put GEX / support pin)
        put_wall = max(strike_gex_map.keys(), key=lambda k: strike_gex_map[k]["put_gex"], default=spot)

        # Scan for Gamma Flip Level (where net GEX crosses 0 around spot)
        sorted_strikes = sorted(strike_gex_map.keys())
        gamma_flip = spot
        for i in range(len(sorted_strikes) - 1):
            k1 = sorted_strikes[i]
            k2 = sorted_strikes[i + 1]
            g1 = strike_gex_map[k1]["net_strike_gex"]
            g2 = strike_gex_map[k2]["net_strike_gex"]
            if (g1 <= 0 and g2 > 0) or (g1 >= 0 and g2 < 0):
                gamma_flip = (k1 + k2) / 2.0
                break

        # Regime classification
        if net_gex > 2.0:  # > 2 Crore positive GEX
            regime = "POSITIVE_GAMMA"
            vol_bias = "SUPPRESSED / MEAN_REVERTING (Dealers Buy Dips, Sell Rallies)"
        elif net_gex < -2.0:  # < -2 Crore negative GEX
            regime = "NEGATIVE_GAMMA"
            vol_bias = "EXPANSIVE / BREAKOUT (Dealers Accelerate Trends)"
        else:
            regime = "NEUTRAL"
            vol_bias = "BALANCED"

        return {
            "net_gex_crores": round(net_gex, 2),
            "call_gex_crores": round(total_call_gex, 2),
            "put_gex_crores": round(total_put_gex, 2),
            "regime": regime,
            "volatility_bias": vol_bias,
            "gamma_flip": round(gamma_flip, 2),
            "call_wall": round(call_wall, 2),
            "put_wall": round(put_wall, 2),
            "is_above_flip": spot >= gamma_flip,
        }
