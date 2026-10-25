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
        if not all(isinstance(v, (int, float)) for v in (S, K, T, r, sigma)):
            return 0.0
        if any(math.isnan(v) or math.isinf(v) for v in (S, K, T, r, sigma)):
            return 0.0
        if T <= 0.0 or sigma <= 0.0 or S <= 0.0 or K <= 0.0:
            return 0.0

        denom = sigma * math.sqrt(T)
        if denom <= 1e-9:
            return 0.0

        s_denom = S * denom
        if s_denom <= 1e-12:
            return 0.0

        try:
            d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / denom
            if abs(d1) > 50.0:
                return 0.0
            gamma = si.norm.pdf(d1, 0.0, 1.0) / s_denom
            if math.isnan(gamma) or math.isinf(gamma) or gamma < 0.0:
                return 0.0
            return float(gamma)
        except Exception:
            return 0.0

    @classmethod
    def calculate_pcr(
        cls,
        chain_or_strikes: Any,
    ) -> Dict[str, float]:
        """
        Calculates Put-Call Ratio (PCR) from Open Interest and Volume.
        Handles zero call OI/volume (division by zero) and empty data gracefully.

        Supports both:
          1. List of strike dicts: [{"strike": ..., "call_oi": ..., "put_oi": ..., "call_vol": ..., "put_vol": ...}]
          2. NSE option chain dict: {"records": {"data": [{"strikePrice": ..., "CE": {...}, "PE": {...}}]}}
        """
        total_call_oi = 0.0
        total_put_oi = 0.0
        total_call_vol = 0.0
        total_put_vol = 0.0

        if isinstance(chain_or_strikes, dict):
            data_rows = chain_or_strikes.get("records", {}).get("data", [])
            for row in data_rows:
                ce = row.get("CE") or {}
                pe = row.get("PE") or {}
                total_call_oi += max(0.0, float(ce.get("openInterest", 0) or 0))
                total_call_vol += max(0.0, float(ce.get("totalTradedVolume", 0) or 0))
                total_put_oi += max(0.0, float(pe.get("openInterest", 0) or 0))
                total_put_vol += max(0.0, float(pe.get("totalTradedVolume", 0) or 0))
        elif isinstance(chain_or_strikes, list):
            for row in chain_or_strikes:
                if not isinstance(row, dict):
                    continue
                total_call_oi += max(0.0, float(row.get("call_oi", 0) or 0))
                total_put_oi += max(0.0, float(row.get("put_oi", 0) or 0))
                total_call_vol += max(0.0, float(row.get("call_vol", 0) or 0))
                total_put_vol += max(0.0, float(row.get("put_vol", 0) or 0))

        # PCR OI calculation: guard against division by zero
        if total_call_oi > 0.0:
            pcr_oi = total_put_oi / total_call_oi
        else:
            pcr_oi = 1.0 if total_put_oi == 0.0 else 100.0  # Capped upper bound instead of inf/ZeroDivisionError

        # PCR Volume calculation: guard against division by zero
        if total_call_vol > 0.0:
            pcr_vol = total_put_vol / total_call_vol
        else:
            pcr_vol = 1.0 if total_put_vol == 0.0 else 100.0

        pcr_oi = float(np.clip(pcr_oi, 0.0, 100.0))
        pcr_vol = float(np.clip(pcr_vol, 0.0, 100.0))

        return {
            "pcr_oi": round(pcr_oi, 3),
            "pcr_volume": round(pcr_vol, 3),
            "total_put_oi": int(total_put_oi),
            "total_call_oi": int(total_call_oi),
            "total_put_vol": int(total_put_vol),
            "total_call_vol": int(total_call_vol),
        }

    @classmethod
    def calculate_max_pain(
        cls,
        chain_or_strikes: Any,
        spot: Optional[float] = None,
    ) -> Optional[float]:
        """
        Calculates Max Pain strike where option sellers incur the least payout upon expiry.
        Handles empty chains, zero OI, and non-numeric entries safely.
        """
        if not chain_or_strikes:
            return float(spot) if spot and spot > 0 else None

        strikes: List[float] = []
        call_oi_map: Dict[float, float] = {}
        put_oi_map: Dict[float, float] = {}

        if isinstance(chain_or_strikes, dict):
            data_rows = chain_or_strikes.get("records", {}).get("data", [])
            for row in data_rows:
                k = row.get("strikePrice")
                if k is None:
                    continue
                try:
                    k_val = float(k)
                    if k_val <= 0 or math.isnan(k_val):
                        continue
                except (ValueError, TypeError):
                    continue
                strikes.append(k_val)
                ce = row.get("CE") or {}
                pe = row.get("PE") or {}
                call_oi_map[k_val] = max(0.0, float(ce.get("openInterest", 0) or 0))
                put_oi_map[k_val] = max(0.0, float(pe.get("openInterest", 0) or 0))
        elif isinstance(chain_or_strikes, list):
            for row in chain_or_strikes:
                if not isinstance(row, dict):
                    continue
                k = row.get("strike")
                if k is None:
                    continue
                try:
                    k_val = float(k)
                    if k_val <= 0 or math.isnan(k_val):
                        continue
                except (ValueError, TypeError):
                    continue
                strikes.append(k_val)
                call_oi_map[k_val] = max(0.0, float(row.get("call_oi", 0) or 0))
                put_oi_map[k_val] = max(0.0, float(row.get("put_oi", 0) or 0))

        strikes = sorted(list(set(strikes)))
        if not strikes:
            return float(spot) if spot and spot > 0 else None

        # If all OI is 0 everywhere, return median strike
        total_oi = sum(call_oi_map.values()) + sum(put_oi_map.values())
        if total_oi <= 0.0:
            return float(strikes[len(strikes) // 2])

        min_loss = float("inf")
        max_pain_strike = strikes[len(strikes) // 2]

        for settlement in strikes:
            loss = 0.0
            for k in strikes:
                if settlement > k:
                    loss += (settlement - k) * call_oi_map.get(k, 0.0)
                elif settlement < k:
                    loss += (k - settlement) * put_oi_map.get(k, 0.0)

            if loss < min_loss:
                min_loss = loss
                max_pain_strike = settlement

        return float(max_pain_strike)

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
        if spot <= 0 or math.isnan(spot) or not strikes_data:
            safe_spot = 0.0 if math.isnan(spot) or spot <= 0 else spot
            return {
                "net_gex_crores": 0.0,
                "call_gex_crores": 0.0,
                "put_gex_crores": 0.0,
                "regime": "NEUTRAL",
                "volatility_bias": "BALANCED",
                "gamma_flip": safe_spot,
                "call_wall": safe_spot,
                "put_wall": safe_spot,
                "is_above_flip": True,
                "pcr_oi": 1.0,
                "pcr_volume": 1.0,
                "max_pain": safe_spot,
            }

        T = max(0.001, days_to_expiry / 365.0)
        safe_iv = max(0.001, iv)

        total_call_gex = 0.0
        total_put_gex = 0.0

        strike_gex_map: Dict[float, Dict[str, float]] = {}

        for row in strikes_data:
            if not isinstance(row, dict):
                continue
            try:
                k = float(row.get("strike", 0.0))
            except (ValueError, TypeError):
                continue

            if k <= 0 or math.isnan(k):
                continue

            try:
                c_oi = max(0.0, float(row.get("call_oi", 0.0) or 0.0))
                p_oi = max(0.0, float(row.get("put_oi", 0.0) or 0.0))
            except (ValueError, TypeError):
                continue

            gamma = cls.calculate_gamma(spot, k, T, r, safe_iv)

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

        if not strike_gex_map:
            return {
                "net_gex_crores": 0.0,
                "call_gex_crores": 0.0,
                "put_gex_crores": 0.0,
                "regime": "NEUTRAL",
                "volatility_bias": "BALANCED",
                "gamma_flip": spot,
                "call_wall": spot,
                "put_wall": spot,
                "is_above_flip": True,
                "pcr_oi": 1.0,
                "pcr_volume": 1.0,
                "max_pain": spot,
            }

        net_gex = total_call_gex - total_put_gex

        # Identify Call Wall (strike with highest call GEX / resistance pin)
        call_wall = max(strike_gex_map.keys(), key=lambda k: strike_gex_map[k]["call_gex"], default=spot)
        # Identify Put Wall (strike with highest put GEX / support pin)
        put_wall = max(strike_gex_map.keys(), key=lambda k: strike_gex_map[k]["put_gex"], default=spot)

        # Scan for Gamma Flip Level (where net GEX crosses 0 around spot)
        sorted_strikes = sorted(strike_gex_map.keys())
        gamma_flip = spot
        flip_found = False

        for i in range(len(sorted_strikes) - 1):
            k1 = sorted_strikes[i]
            k2 = sorted_strikes[i + 1]
            g1 = strike_gex_map[k1]["net_strike_gex"]
            g2 = strike_gex_map[k2]["net_strike_gex"]

            if (g1 <= 0.0 and g2 > 0.0) or (g1 >= 0.0 and g2 < 0.0):
                # Precise linear interpolation for exact zero root
                if abs(g2 - g1) > 1e-12:
                    gamma_flip = k1 - g1 * (k2 - k1) / (g2 - g1)
                else:
                    gamma_flip = (k1 + k2) / 2.0
                flip_found = True
                break
            elif abs(g1) < 1e-9:
                gamma_flip = k1
                flip_found = True
                break

        # If no zero-crossing detected, estimate flip at strike with lowest absolute net GEX
        if not flip_found and sorted_strikes:
            gamma_flip = min(sorted_strikes, key=lambda k: abs(strike_gex_map[k]["net_strike_gex"]))

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

        pcr_data = cls.calculate_pcr(strikes_data)
        max_pain = cls.calculate_max_pain(strikes_data, spot=spot) or spot

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
            "pcr_oi": pcr_data["pcr_oi"],
            "pcr_volume": pcr_data["pcr_volume"],
            "max_pain": round(max_pain, 2),
        }
