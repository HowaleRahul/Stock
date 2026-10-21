"""
Momentum Masters — Swing Toolkit Package.
"""

from setups.swing_toolkit.scanners import (
    MomentumScanner,
    DWIBScanner,
    ATHScanner,
    SwingScannerSuite,
    ScannerMatch,
)
from setups.swing_toolkit.checklist import (
    SwingFilterChecklist,
    QualityScoreResult,
    ChecklistItem,
)
from setups.swing_toolkit.orb_entry import (
    ORBBreakoutEngine,
    ORBExecutionPlan,
)
from setups.swing_toolkit.toolkit import SwingToolkitManager
from setups.swing_toolkit.universe import (
    DEFAULT_SWING_UNIVERSE,
    STOCK_SECTORS,
    BENCHMARK_TICKER,
)

__all__ = [
    "MomentumScanner",
    "DWIBScanner",
    "ATHScanner",
    "SwingScannerSuite",
    "ScannerMatch",
    "SwingFilterChecklist",
    "QualityScoreResult",
    "ChecklistItem",
    "ORBBreakoutEngine",
    "ORBExecutionPlan",
    "SwingToolkitManager",
    "DEFAULT_SWING_UNIVERSE",
    "STOCK_SECTORS",
    "BENCHMARK_TICKER",
]
