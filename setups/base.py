"""
Base interfaces and data structures for the trading setups engine.
Every setup implements BaseSetup and returns a SetupSignal.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from typing import Any, Dict

import pandas as pd


@dataclass
class SetupSignal:
    """Standardized output from every setup evaluation.

    Attributes:
        name:             Human-readable setup name (e.g. "MA Crossover").
        signal:           One of "bullish", "bearish", or "neutral".
        confidence:       Float in [0.0, 1.0] indicating conviction strength.
        reasoning:        Plain-English explanation of the signal.
        indicator_values: Raw indicator data for chart overlay rendering.
    """

    name: str
    signal: str  # "bullish" | "bearish" | "neutral"
    confidence: float  # 0.0 – 1.0
    reasoning: str
    indicator_values: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        import math
        try:
            val = float(self.confidence)
            if math.isnan(val):
                val = 0.0
            elif math.isinf(val):
                val = 1.0 if val > 0 else 0.0
        except (ValueError, TypeError):
            val = 0.0
        # Clamp confidence into valid range
        self.confidence = max(0.0, min(1.0, val))
        # Normalize signal string
        if not isinstance(self.signal, str):
            self.signal = "neutral"
        else:
            self.signal = self.signal.replace("\x00", "").lower().strip()
            if self.signal not in ("bullish", "bearish", "neutral"):
                self.signal = "neutral"
        # Sanitize name and reasoning
        if not isinstance(self.name, str):
            self.name = str(self.name) if self.name is not None else "Unnamed Setup"
        self.name = self.name.replace("\x00", "").strip()[:128] or "Unnamed Setup"
        if not isinstance(self.reasoning, str):
            self.reasoning = str(self.reasoning) if self.reasoning is not None else ""
        self.reasoning = self.reasoning.replace("\x00", "").strip()[:2048]
        if not isinstance(self.indicator_values, dict):
            self.indicator_values = {}


class BaseSetup(ABC):
    """Abstract base class that every technical setup must implement."""

    name: str = "Unnamed Setup"

    @abstractmethod
    def evaluate(self, df: pd.DataFrame) -> SetupSignal:
        """Evaluate the setup against an OHLCV DataFrame.

        Args:
            df: DataFrame with at minimum the columns:
                time, open, high, low, close, volume.
                Rows are in ascending chronological order.

        Returns:
            A SetupSignal with the evaluation result.
        """
        ...
