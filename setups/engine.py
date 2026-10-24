"""
SetupEngine — F&O-Optimized Orchestrator

Runs registered technical and institutional setups against price and derivative data to generate
signals for Futures & Options and equity trading decisions.

Included Core Setups:
- MA Crossover: Trend direction on index
- RSI: Overbought/oversold extremes for mean-reversion
- MACD: Momentum confirmation for directional trades
- Bollinger Bands: Squeeze/breakout for volatility-based entries
- Breakout: Donchian channel breakout for trend-following
- VWAP: Volume-weighted price for intraday scalping

Institutional & Advanced Setups (from research repositories):
- VCP: Minervini Volatility Contraction Pattern (from claude-trading-skills)
- Options PCR: Live NSE Put-Call Ratio & Max Pain (from nsepython & Bharat-SM-Data)
- Piotroski F-Score: 9-point fundamental health (from staskh/trading_skills)
"""

from __future__ import annotations

import logging
import inspect
from typing import List, Optional

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
    """Runs technical and institutional setups against OHLCV and market data."""

    def __init__(self, include_advanced: bool = False) -> None:
        self.setups: List[BaseSetup] = [
            MACrossoverSetup(),
            RSISetup(),
            MACDSetup(),
            BollingerBandsSetup(),
            BreakoutSetup(),
            VWAPSetup(),
        ]
        if include_advanced:
            try:
                from setups.vcp_setup import VCPSetup
                from setups.options_setup import OptionsSetup
                from setups.piotroski_setup import PiotroskiSetup
                self.setups.extend([VCPSetup(), OptionsSetup(), PiotroskiSetup()])
            except Exception as e:
                logger.debug(f"Could not load advanced setups: {e}")

    def evaluate_with_regime(self, df: pd.DataFrame, ticker: str = "") -> tuple[dict, List[SetupSignal]]:
        """Run every registered setup against price data.

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
                if regime_data.get("regime") == "range-bound":
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
                if regime_data.get("regime") == "crash":
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
