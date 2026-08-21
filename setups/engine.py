"""
SetupEngine — Orchestrator that runs all registered setups and returns
aggregated results.  Each setup is executed in isolation so one failure
does not block the others.
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

logger = logging.getLogger("trading.setups.engine")


class SetupEngine:
    """Runs all technical setups against an OHLCV DataFrame."""

    def __init__(self) -> None:
        self.setups: List[BaseSetup] = [
            MACrossoverSetup(),
            RSISetup(),
            MACDSetup(),
            BollingerBandsSetup(),
            BreakoutSetup(),
        ]

    def evaluate_all(self, df: pd.DataFrame, ticker: str = "") -> List[SetupSignal]:
        """Run every registered setup.

        Args:
            df: OHLCV DataFrame with columns ``time, open, high, low,
                close, volume`` in ascending chronological order.
            ticker: The ticker symbol being evaluated.

        Returns:
            A list of ``SetupSignal`` — one per setup.  On error the signal
            is "neutral" with confidence 0 and the error message in
            ``reasoning``.
        """
        results: List[SetupSignal] = []
        
        # Detect Market Regime.  It is used only as a confidence modifier;
        # failure to determine it must not change the result contract.
        regime_data = RegimeDetector.detect(df)
        
        for setup in self.setups:
            try:
                sig = inspect.signature(setup.evaluate)
                if "ticker" in sig.parameters:
                    signal = setup.evaluate(df, ticker=ticker)
                else:
                    signal = setup.evaluate(df)
                
                # Apply Regime-based confidence weighting
                # E.g., trend setups like MA crossover are weak in range-bound markets
                if regime_data["regime"] == "range-bound":
                    if setup.name in ["MA Crossover", "MACD", "Ichimoku Cloud"]:
                        if signal.confidence > 0.0:
                            signal.confidence *= 0.5  # Slash confidence by 50%
                            signal.reasoning += " (Confidence reduced due to range-bound regime)."
                            
                # Hard Gating: Smart money doesn't catch falling knives
                if regime_data["regime"] == "crash":
                    if signal.signal == "bullish":
                        signal.confidence = 0.0
                        signal.signal = "neutral"
                        signal.reasoning += " [SYSTEM BLOCK: Extreme Crash Regime Detected. Bullish setups gated.]"
                            
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
                
        return results
