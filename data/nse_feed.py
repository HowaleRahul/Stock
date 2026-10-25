"""
NSE Live Feed & Derivatives Data Aggregator

Incorporates proven concepts from `nsepython` (aeron7) and `Bharat-SM-Data` (Sampad-Hegde):
- Uses curl_cffi with browser TLS/JA3 impersonation (chrome120) to bypass Akamai Bot Protection.
- Fetches real-time NSE Option Chain data (NIFTY, BANKNIFTY, SENSEX, individual F&O equities).
- Computes real-time Put-Call Ratio (PCR) from Open Interest and Volume.
- Computes Strike Max-Pain level.
- Fetches FII / DII Institutional cash market flows.
- Fetches live India VIX and Market Status.
- Resilient fallback logic so market closed/offline events never crash downstream pipelines.
"""

from __future__ import annotations

import logging
import math
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("trading.data.nse_feed")

try:
    from curl_cffi import requests as cffi_requests
    _CURL_CFFI_AVAILABLE = True
except ImportError:
    _CURL_CFFI_AVAILABLE = False
    import requests as cffi_requests

NSE_BASE_URL = "https://www.nseindia.com"
NSE_INDICES = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "^NSEI", "^NSEBANK"}


class NSEFeed:
    """Live NSE India market and derivative data scraper."""

    _session = None
    _last_warmed_at = 0.0
    _WARM_INTERVAL = 300.0  # re-warm cookies every 5 minutes

    @classmethod
    def _get_headers(cls) -> Dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nseindia.com/option-chain",
            "X-Requested-With": "XMLHttpRequest",
        }

    @classmethod
    def get_session(cls):
        now = time.time()
        if cls._session is None or (now - cls._last_warmed_at) > cls._WARM_INTERVAL:
            try:
                if _CURL_CFFI_AVAILABLE:
                    session = cffi_requests.Session(impersonate="chrome120")
                else:
                    session = cffi_requests.Session()

                # Warm up session with base URL to harvest Akamai cookies
                session.get(NSE_BASE_URL, headers=cls._get_headers(), timeout=10)
                cls._session = session
                cls._last_warmed_at = now
                logger.info("NSE session initialized and warmed up successfully.")
            except Exception as e:
                logger.warning(f"Error initializing NSE session: {e}")
                if cls._session is None:
                    cls._session = cffi_requests.Session()
        return cls._session

    @classmethod
    def clean_symbol(cls, symbol: str) -> str:
        if not symbol or not isinstance(symbol, str):
            return ""
        s = symbol.upper().replace("^", "").strip()
        if s in ("NSEI", "NIFTY50", "NIFTY 50"):
            return "NIFTY"
        if s in ("NSEBANK", "BANK NIFTY"):
            return "BANKNIFTY"
        if s in ("BSESN", "SENSEX"):
            return "SENSEX"
        return s

    @classmethod
    def get_option_chain_raw(cls, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetches raw JSON option chain payload from NSE with automatic retry and cookie refreshment."""
        sym = cls.clean_symbol(symbol)
        if not sym:
            return None
        nse_query_sym = sym[:-3] if (sym.endswith(".NS") or sym.endswith(".BO")) else sym
        encoded_sym = urllib.parse.quote(nse_query_sym)
        is_index = nse_query_sym in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")

        if is_index:
            url = f"{NSE_BASE_URL}/api/option-chain-indices?symbol={encoded_sym}"
        else:
            url = f"{NSE_BASE_URL}/api/option-chain-equities?symbol={encoded_sym}"

        for attempt in range(2):
            try:
                session = cls.get_session()
                resp = session.get(url, headers=cls._get_headers(), timeout=10)
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        if isinstance(data, dict) and "records" in data:
                            return data
                    except Exception as json_err:
                        logger.warning(f"NSE option chain JSON decode error for {sym}: {json_err}")
                elif resp.status_code in (401, 403):
                    logger.warning(f"NSE session expired/blocked (status {resp.status_code}) for {sym}. Re-warming...")
                    cls._session = None
                    cls._last_warmed_at = 0.0
                    continue
                else:
                    logger.warning(f"NSE option chain returned status {resp.status_code} for {sym}")
                    break
            except Exception as e:
                logger.debug(f"Attempt {attempt + 1} failed to fetch live option chain for {sym}: {e}")
                cls._session = None
                cls._last_warmed_at = 0.0
                if attempt == 0:
                    time.sleep(0.5)

        return None

    @classmethod
    def calculate_pcr(cls, option_chain: Dict[str, Any]) -> Tuple[float, float, int, int]:
        """
        Calculates Put-Call Ratio (PCR) from option chain data.
        Returns: (pcr_oi, pcr_volume, total_put_oi, total_call_oi)
        """
        if not option_chain or "records" not in option_chain:
            return 1.0, 1.0, 0, 0

        data_rows = option_chain.get("records", {}).get("data", [])
        total_call_oi = 0
        total_put_oi = 0
        total_call_vol = 0
        total_put_vol = 0

        for row in data_rows:
            ce = row.get("CE")
            pe = row.get("PE")
            if ce:
                total_call_oi += ce.get("openInterest", 0)
                total_call_vol += ce.get("totalTradedVolume", 0)
            if pe:
                total_put_oi += pe.get("openInterest", 0)
                total_put_vol += pe.get("totalTradedVolume", 0)

        pcr_oi = total_put_oi / total_call_oi if total_call_oi > 0 else (100.0 if total_put_oi > 0 else 1.0)
        pcr_vol = total_put_vol / total_call_vol if total_call_vol > 0 else (100.0 if total_put_vol > 0 else 1.0)

        return round(pcr_oi, 3), round(pcr_vol, 3), total_put_oi, total_call_oi

    @classmethod
    def calculate_max_pain(cls, option_chain: Dict[str, Any]) -> Optional[float]:
        """
        Calculates Max Pain strike where option sellers incur the least payout upon expiry.
        """
        if not option_chain or "records" not in option_chain:
            return None

        data_rows = option_chain.get("records", {}).get("data", [])
        if not data_rows:
            return None

        # Gather strikes and their call/put OI
        strikes = []
        call_oi_map = {}
        put_oi_map = {}

        for row in data_rows:
            k = row.get("strikePrice")
            if k is None:
                continue
            try:
                k_val = float(k)
                if math.isnan(k_val) or math.isinf(k_val):
                    continue
            except (ValueError, TypeError):
                continue
            strikes.append(k_val)
            ce = row.get("CE", {}) or {}
            pe = row.get("PE", {}) or {}
            call_oi_map[k_val] = float(ce.get("openInterest", 0) or 0)
            put_oi_map[k_val] = float(pe.get("openInterest", 0) or 0)

        strikes = sorted(list(set(strikes)))
        if not strikes:
            return None

        # For each candidate settlement price, calculate total loss for option sellers
        min_loss = float("inf")
        max_pain_strike = strikes[len(strikes) // 2]

        for settlement in strikes:
            loss = 0.0
            for k in strikes:
                # Call seller loss if settlement > k
                if settlement > k:
                    loss += (settlement - k) * call_oi_map.get(k, 0.0)
                # Put seller loss if settlement < k
                elif settlement < k:
                    loss += (k - settlement) * put_oi_map.get(k, 0.0)

            if loss < min_loss:
                min_loss = loss
                max_pain_strike = settlement

        return float(max_pain_strike)

    @classmethod
    def get_fii_dii_activity(cls) -> Dict[str, Any]:
        """
        Fetches daily Institutional FII / DII activity in Indian cash market.
        """
        url = f"{NSE_BASE_URL}/api/fiidiiTradeReact"
        for attempt in range(2):
            try:
                session = cls.get_session()
                resp = session.get(url, headers=cls._get_headers(), timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    fii_net = 0.0
                    dii_net = 0.0
                    for item in data:
                        cat = item.get("category", "").upper()
                        try:
                            val = float(item.get("netValue", 0.0) or 0.0)
                        except (ValueError, TypeError):
                            val = 0.0
                        if "FII" in cat or "FPI" in cat:
                            fii_net += val
                        elif "DII" in cat:
                            dii_net += val

                    return {
                        "fii_net_crores": round(fii_net, 2),
                        "dii_net_crores": round(dii_net, 2),
                        "sentiment": "BULLISH" if (fii_net + dii_net) > 0 else "BEARISH",
                        "timestamp": time.time(),
                    }
                elif resp.status_code in (401, 403):
                    cls._session = None
                    cls._last_warmed_at = 0.0
                    continue
                else:
                    break
            except Exception as e:
                logger.debug(f"Failed to fetch FII/DII activity (attempt {attempt + 1}): {e}")
                cls._session = None
                cls._last_warmed_at = 0.0

        return {
            "fii_net_crores": 0.0,
            "dii_net_crores": 0.0,
            "sentiment": "NEUTRAL",
            "timestamp": time.time(),
        }

    @classmethod
    def get_india_vix(cls) -> Optional[float]:
        """
        Fetches live India VIX from NSE India allIndices API.
        Returns percentage (e.g. 14.5) or None on failure.
        """
        url = f"{NSE_BASE_URL}/api/allIndices"
        for attempt in range(2):
            try:
                session = cls.get_session()
                resp = session.get(url, headers=cls._get_headers(), timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    for item in data.get("data", []):
                        idx_name = item.get("index", "").upper().replace(" ", "")
                        if "INDIAVIX" in idx_name or "VIX" in idx_name:
                            try:
                                val = float(item.get("last", 0.0) or 0.0)
                                if val > 0:
                                    return round(val, 2)
                            except (ValueError, TypeError):
                                pass
                elif resp.status_code in (401, 403):
                    cls._session = None
                    cls._last_warmed_at = 0.0
                    continue
                else:
                    break
            except Exception as e:
                logger.debug(f"Failed to fetch India VIX from NSE (attempt {attempt + 1}): {e}")
                cls._session = None
                cls._last_warmed_at = 0.0

        return None
