"""Canonical asset-class policy shared by training and inference.

Keeping this classification in one module prevents a symbol from receiving
different macro inputs or model flags in the batch and continuous pipelines.
"""

from __future__ import annotations

from typing import Final

ASSET_CLASSES: Final[tuple[str, ...]] = ("IN_EQUITY", "US_EQUITY", "CRYPTO")
TARGETS: Final[dict[str, tuple[str, ...]]] = {
    "IN_EQUITY": ("^NSEI", "^NSEBANK"),
    "US_EQUITY": ("^GSPC", "^DJI", "^IXIC"),
    "CRYPTO": ("BTC-USD", "ETH-USD", "SOL-USD"),
}

TICKER_ALIASES: Final[dict[str, str]] = {
    "NIFTY": "^NSEI",
    "NIFTY50": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
}

# These symbols are present in the application catalog and are explicitly
# supported for global price-action training. New symbols must be classified
# deliberately instead of inheriting Indian-equity assumptions.
US_EQUITY_SYMBOLS: Final[frozenset[str]] = frozenset({"AAPL", "NVDA", "MSFT"})


def normalize_ticker(ticker: str) -> str:
    """Return the canonical Yahoo symbol or reject malformed input."""
    if not isinstance(ticker, str):
        raise ValueError("Ticker symbol must be a string")
    normalized = ticker.upper().strip()
    if not normalized or len(normalized) > 64:
        raise ValueError("Ticker symbol is empty or too long")
    if any(char.isspace() or ord(char) < 32 for char in normalized):
        raise ValueError("Ticker symbol contains whitespace or control characters")
    return TICKER_ALIASES.get(normalized, normalized)


def classify_ticker(ticker: str) -> str:
    """Return the supported asset class for a Yahoo Finance ticker.

    The explicit crypto allow-list intentionally avoids broad heuristics such
    as ``"USD" in ticker`` which would misclassify FX symbols as crypto.
    Unknown symbols fail closed because the asset class controls macro data,
    labels, model flags, and execution assumptions.
    """
    normalized = normalize_ticker(ticker)
    for asset_class, symbols in TARGETS.items():
        if normalized in symbols:
            return asset_class
    if normalized == "INR=X" or normalized.endswith((".NS", ".BO")):
        return "IN_EQUITY"
    if normalized in US_EQUITY_SYMBOLS:
        return "US_EQUITY"
    raise ValueError(f"Unsupported or unclassified ticker: {ticker}")


def is_execution_supported(ticker: str) -> bool:
    """Return whether the current live/paper execution scope supports ticker."""
    return classify_ticker(ticker) == "IN_EQUITY"


def asset_flags(asset_class: str) -> dict[str, float]:
    """One-hot asset features used by every model-training path."""
    if asset_class not in ASSET_CLASSES:
        raise ValueError(f"Unsupported asset class: {asset_class}")
    return {
        "feat_is_in_equity": float(asset_class == "IN_EQUITY"),
        "feat_is_us_equity": float(asset_class == "US_EQUITY"),
        "feat_is_crypto": float(asset_class == "CRYPTO"),
    }


def barrier_config(asset_class: str, timeframe: str) -> dict[str, float | int]:
    """Return conservative, volatility-aware triple-barrier defaults."""
    if asset_class not in ASSET_CLASSES:
        raise ValueError(f"Unsupported asset class: {asset_class}")
    daily = timeframe.lower() == "1d"
    if asset_class == "CRYPTO":
        return {"tp_atr": 3.0, "sl_atr": 1.5, "max_hold": 20 if daily else 40}
    return {"tp_atr": 2.0, "sl_atr": 1.0, "max_hold": 20 if daily else 40}
