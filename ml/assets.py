"""Canonical asset-class policy for F&O-only Indian market trading.

This module defines the ONLY supported instruments: NSE Index Futures
and Options (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY).

No equity/cash segment, no US markets, no crypto.
Foreign market F&O support is reserved for future expansion.
"""

from __future__ import annotations

from typing import Final


# ---------------------------------------------------------------------------
# F&O Asset Classes
# ---------------------------------------------------------------------------

ASSET_CLASSES: Final[tuple[str, ...]] = ("IN_INDEX_FO",)

# Supported F&O underlyings — these are Indian index tickers on Yahoo Finance
# used for price-action analysis. Actual trading happens via F&O contracts.
FO_UNDERLYINGS: Final[dict[str, str]] = {
    "NIFTY":      "^NSEI",
    "BANKNIFTY":  "^NSEBANK",
    "SENSEX":     "^BSESN",
    "FINNIFTY":   "^NSEI",      # FINNIFTY uses NIFTY as proxy on Yahoo
    "MIDCPNIFTY": "^NSEI",      # MIDCPNIFTY uses NIFTY as proxy on Yahoo
}

# Lot sizes as per NSE/BSE (updated periodically)
LOT_SIZES: Final[dict[str, int]] = {
    "NIFTY":      25,
    "BANKNIFTY":  15,
    "SENSEX":     10,
    "FINNIFTY":   25,
    "MIDCPNIFTY": 50,
}

# Strike intervals for option chain
STRIKE_INTERVALS: Final[dict[str, int]] = {
    "NIFTY":      50,
    "BANKNIFTY":  100,
    "SENSEX":     100,
    "FINNIFTY":   50,
    "MIDCPNIFTY": 25,
}

# Futures margin rates (SPAN + Exposure, ~14-16%)
FUTURES_MARGIN_RATES: Final[dict[str, float]] = {
    "NIFTY":      0.15,
    "BANKNIFTY":  0.16,
    "SENSEX":     0.15,
    "FINNIFTY":   0.15,
    "MIDCPNIFTY": 0.16,
}

# Yahoo Finance ticker aliases for normalization
TICKER_ALIASES: Final[dict[str, str]] = {
    "NIFTY":       "^NSEI",
    "NIFTY50":     "^NSEI",
    "BANKNIFTY":   "^NSEBANK",
    "SENSEX":      "^BSESN",
    "BSE":         "^BSESN",
    "BSESN":       "^BSESN",
    "FINNIFTY":    "^NSEI",
    "MIDCPNIFTY":  "^NSEI",
    "^NSEI":       "^NSEI",
    "^NSEBANK":    "^NSEBANK",
    "^BSESN":      "^BSESN",
}

# Reverse map: Yahoo ticker → F&O underlying name
YAHOO_TO_FO: Final[dict[str, str]] = {
    "^NSEI":     "NIFTY",
    "^NSEBANK":  "BANKNIFTY",
    "^BSESN":    "SENSEX",
}

# Weekly expiry days (0=Monday ... 6=Sunday)
EXPIRY_DAYS: Final[dict[str, int]] = {
    "NIFTY":      3,   # Thursday
    "BANKNIFTY":  2,   # Wednesday
    "SENSEX":     4,   # Friday
    "FINNIFTY":   1,   # Tuesday
    "MIDCPNIFTY": 0,   # Monday
}


def normalize_ticker(ticker: str) -> str:
    """Return the canonical Yahoo symbol for F&O underlying."""
    if not isinstance(ticker, str):
        raise ValueError("Ticker symbol must be a string")
    normalized = ticker.upper().strip()
    if not normalized or len(normalized) > 64:
        raise ValueError("Ticker symbol is empty or too long")
    if any(char.isspace() or ord(char) < 32 for char in normalized):
        raise ValueError("Ticker symbol contains whitespace or control characters")
    result = TICKER_ALIASES.get(normalized)
    if result is None:
        raise ValueError(
            f"Unsupported ticker: {ticker}. "
            f"Only F&O indices are supported: {list(FO_UNDERLYINGS.keys())}"
        )
    return result


def classify_ticker(ticker: str) -> str:
    """Return 'IN_INDEX_FO' for all supported tickers.

    Fails closed on anything not in the F&O universe.
    """
    normalize_ticker(ticker)  # validates
    return "IN_INDEX_FO"


def get_fo_name(ticker: str) -> str:
    """Return the F&O underlying name (NIFTY, BANKNIFTY, etc.) from any ticker format."""
    normalized = ticker.upper().strip()
    # Direct match
    if normalized in FO_UNDERLYINGS:
        return normalized
    # Yahoo ticker reverse lookup
    if normalized in YAHOO_TO_FO:
        return YAHOO_TO_FO[normalized]
    # Try alias → yahoo → reverse
    yahoo = TICKER_ALIASES.get(normalized)
    if yahoo and yahoo in YAHOO_TO_FO:
        return YAHOO_TO_FO[yahoo]
    raise ValueError(f"Cannot resolve F&O name for: {ticker}")


def is_execution_supported(ticker: str) -> bool:
    """Return whether trading is supported for this ticker."""
    try:
        classify_ticker(ticker)
        return True
    except ValueError:
        return False


def asset_flags(asset_class: str) -> dict[str, float]:
    """One-hot asset features — simplified for F&O only."""
    if asset_class != "IN_INDEX_FO":
        raise ValueError(f"Unsupported asset class: {asset_class}")
    return {
        "feat_is_nifty": 0.0,
        "feat_is_banknifty": 0.0,
    }


def fo_asset_flags(fo_name: str) -> dict[str, float]:
    """F&O-specific one-hot features by underlying index."""
    return {
        "feat_is_nifty": float(fo_name in ("NIFTY", "FINNIFTY", "MIDCPNIFTY")),
        "feat_is_banknifty": float(fo_name == "BANKNIFTY"),
        "feat_is_sensex": float(fo_name == "SENSEX"),
    }


def barrier_config(asset_class: str, timeframe: str) -> dict[str, float | int]:
    """Return F&O-appropriate triple-barrier defaults.

    F&O uses wider barriers than equity because index movements
    are amplified through leverage (lot size * delta).
    """
    if asset_class != "IN_INDEX_FO":
        raise ValueError(f"Unsupported asset class: {asset_class}")
    daily = timeframe.lower() == "1d"
    return {
        "tp_atr": 2.0,
        "sl_atr": 1.0,
        "max_hold": 10 if daily else 30,  # F&O weekly expiry constraint
    }
