"""
SetupEngine — F&O-Optimized Orchestrator

Runs all registered technical setups against index OHLCV data to generate
signals for Futures & Options trading decisions.

All setups operate on the underlying index price action (NIFTY, BANKNIFTY).
The DerivativeEngine then translates these spot signals into F&O trade plans.

Included Setups (all applicable to F&O index trading):
- MA Crossover: Trend direction on index
- RSI: Overbought/oversold extremes for mean-reversion F&O plays
- MACD: Momentum confirmation for directional F&O trades
- Bollinger Bands: Squeeze/breakout for volatility-based F&O entries
- Breakout: Donchian channel breakout for trend-following F&O
- VWAP: Volume-weighted price for intraday F&O scalping
"""

from __future__ import annotations

import logging
import inspect
from typing import List

import pandas as pd

from setups.base import BaseSetup, SetupSignal
from setups.regime import RegimeDetector
from setups.ma_crossover import MACrossoverSetup
from setups.rsi_setup import RSISetup
from setups.macd_setup import MACDSetup
from setups.bollinger_setup import BollingerBandsSetup
from setups.breakout_setup import BreakoutSetup
from setups.vwap_setup import VWAPSetup

logger = logging.getLogger("trading.setups.engine")


class SetupEngine:
    """Runs all F&O-relevant technical setups against an index OHLCV DataFrame."""

    def __init__(self) -> None:
        self.setups: List[BaseSetup] = [
            MACrossoverSetup(),
            RSISetup(),
            MACDSetup(),
            BollingerBandsSetup(),
            BreakoutSetup(),
            VWAPSetup(),
        ]

    def evaluate_with_regime(self, df: pd.DataFrame, ticker: str = "") -> tuple[dict, List[SetupSignal]]:
        """Run every registered setup against index price data.

        Args:
            df: OHLCV DataFrame with columns ``time, open, high, low,
                close, volume`` in ascending chronological order.
            ticker: The underlying index ticker being evaluated.

        Returns:
            A tuple of (regime_data, signals) where signals is a list of
            ``SetupSignal`` — one per setup.
        """
        results: List[SetupSignal] = []
        
        # Detect Market Regime for confidence modulation
        regime_data = RegimeDetector.detect(df)
        
        for setup in self.setups:
            try:
                sig = inspect.signature(setup.evaluate)
                if "ticker" in sig.parameters:
                    signal = setup.evaluate(df, ticker=ticker)
                else:
                    signal = setup.evaluate(df)
                
                # Regime-based confidence weighting for F&O
                if regime_data["regime"] == "range-bound":
                    # Trend setups are weak in range-bound — reduce confidence
                    if setup.name in ["MA Crossover", "MACD"]:
                        if signal.confidence > 0.0:
                            signal.confidence *= 0.5
                            signal.reasoning += " (Confidence reduced: range-bound regime unfavorable for trend setups)."
                    # But mean-reversion setups like RSI and Bollinger thrive
                    if setup.name in ["RSI", "Bollinger Bands"]:
                        if signal.confidence > 0.0:
                            signal.confidence = min(1.0, signal.confidence * 1.15)
                            signal.reasoning += " (Confidence boosted: range-bound regime favorable for mean-reversion)."
                            
                # Hard Gating: No bullish F&O entries in crash regime
                if regime_data["regime"] == "crash":
                    if signal.signal == "bullish":
                        signal.confidence = 0.0
                        signal.signal = "neutral"
                        signal.reasoning += " [SYSTEM BLOCK: Crash Regime — bullish F&O entries gated.]"
                        
                results.append(signal)
            except Exception as e:
                logger.warning(f"Setup '{setup.name}' raised an error: {e}")
                results.append(
                    SetupSignal(
                        name=setup.name,
                        signal="neutral",
                        confidence=0.0,
                        reasoning=f"Evaluation error: {str(e)}",
                    )
                )
                
        return regime_data, results

    def evaluate_all(self, df: pd.DataFrame, ticker: str = "") -> List[SetupSignal]:
        """Return signals only, preserving the original public contract."""
        _, results = self.evaluate_with_regime(df, ticker=ticker)
        return results
