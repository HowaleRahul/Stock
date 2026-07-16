"""
SetupEngine — Orchestrator that runs all registered setups and returns
aggregated results.  Each setup is executed in isolation so one failure
does not block the others.
"""

from __future__ import annotations

import logging
from typing import List

import pandas as pd

from setups.base import BaseSetup, SetupSignal
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

    def evaluate_all(self, df: pd.DataFrame) -> List[SetupSignal]:
        """Run every registered setup.

        Args:
            df: OHLCV DataFrame with columns ``time, open, high, low,
                close, volume`` in ascending chronological order.

        Returns:
            A list of ``SetupSignal`` — one per setup.  On error the signal
            is "neutral" with confidence 0 and the error message in
            ``reasoning``.
        """
        results: List[SetupSignal] = []
        for setup in self.setups:
            try:
                signal = setup.evaluate(df)
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
