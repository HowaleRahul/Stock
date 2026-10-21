"""
Momentum Masters Swing Breakout Setup — BaseSetup Implementation.

Integrates the 3 Scanners and 8-Factor Filter Checklist into the
standard BaseSetup / SetupSignal contract for strategy backtesting,
live paper trading, and indicator visualization.
"""

from __future__ import annotations

import pandas as pd
from setups.base import BaseSetup, SetupSignal
from setups.swing_toolkit.scanners import SwingScannerSuite
from setups.swing_toolkit.checklist import SwingFilterChecklist


class MomentumMastersSetup(BaseSetup):
    """
    Evaluates whether a symbol meets the Momentum Masters Swing Toolkit criteria:
    - Scanned by Momentum, DWIB, or ATH Contraction
    - Filtered by the 8-Factor Quality Checklist (Stage 2, VCP, Liquidity, RS, Candle Quality)
    """

    def __init__(self) -> None:
        self.scanners = SwingScannerSuite()
        self.checklist = SwingFilterChecklist()

    @property
    def name(self) -> str:
        return "Momentum Masters Swing"

    def evaluate(self, df: pd.DataFrame, ticker: str = "") -> SetupSignal:
        if len(df) < 50:
            return SetupSignal(
                name=self.name,
                signal="neutral",
                confidence=0.0,
                reasoning=f"Insufficient history ({len(df)} bars, need 50+).",
            )

        try:
            scan_res = self.scanners.scan_symbol(df, ticker)
            checklist_res = self.checklist.evaluate(df, ticker)

            if scan_res["is_hit"] and checklist_res.qualifies_for_watchlist:
                # High conviction swing setup
                scanners_str = ", ".join(scan_res["matched_scanners"])
                confidence = min(0.60 + (checklist_res.composite_score / 250.0), 0.98)
                reasoning = (
                    f"🔥 Momentum Masters Setup Active! Triggered by [{scanners_str}]. "
                    f"Checklist Score: {checklist_res.composite_score:.1f}/100 ({checklist_res.passed_count}/8 passed). "
                    f"{checklist_res.summary}"
                )
                return SetupSignal(
                    name=self.name,
                    signal="bullish",
                    confidence=confidence,
                    reasoning=reasoning,
                    indicator_values={
                        "scanners": scan_res["matched_scanners"],
                        "composite_score": checklist_res.composite_score,
                        "qualifies_watchlist": checklist_res.qualifies_for_watchlist,
                        "stage_2": checklist_res.checklist_items.get("stage_2", {}).passed if hasattr(checklist_res.checklist_items.get("stage_2", None), "passed") else False,
                        "vcp_passed": checklist_res.checklist_items.get("contraction", {}).passed if hasattr(checklist_res.checklist_items.get("contraction", None), "passed") else False,
                    },
                )

            elif scan_res["is_hit"]:
                # Scanner hit, but failed checklist cutoff (< 70)
                scanners_joined = ", ".join(scan_res["matched_scanners"])
                return SetupSignal(
                    name=self.name,
                    signal="neutral",
                    confidence=0.30,
                    reasoning=(
                        f"Scanner hit [{scanners_joined}], but failed checklist cutoff "
                        f"(Score: {checklist_res.composite_score:.1f}/100, needed 70.0). Filtered out."
                    ),
                    indicator_values={
                        "scanners": scan_res["matched_scanners"],
                        "composite_score": checklist_res.composite_score,
                        "qualifies_watchlist": False,
                    },
                )
            else:
                return SetupSignal(
                    name=self.name,
                    signal="neutral",
                    confidence=0.0,
                    reasoning="No Momentum, DWIB, or ATH contraction setup detected.",
                )

        except Exception as e:
            return SetupSignal(
                name=self.name,
                signal="neutral",
                confidence=0.0,
                reasoning=f"Evaluation error: {str(e)}",
            )
