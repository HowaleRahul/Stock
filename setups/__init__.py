"""
Trading Setups Engine — Technical analysis setups that evaluate OHLCV data
and emit standardized signals with confidence scores.

Public API:
    - SetupSignal:  Standardized signal dataclass.
    - BaseSetup:    Abstract base class for all setups.
    - SetupEngine:  Orchestrator that runs all registered setups.
    - Indicator functions: sma, ema, rsi, macd, bollinger_bands, find_support_resistance.
"""

from setups.base import BaseSetup, SetupSignal
from setups.engine import SetupEngine
from setups.indicators import (
    sma,
    ema,
    rsi,
    macd,
    bollinger_bands,
    find_support_resistance,
)

__all__ = [
    "BaseSetup",
    "SetupSignal",
    "SetupEngine",
    "sma",
    "ema",
    "rsi",
    "macd",
    "bollinger_bands",
    "find_support_resistance",
]
