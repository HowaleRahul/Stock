"""
Concept Drift Detector — Phase 7

Analyzes the paper trading journal to identify setups whose live performance
has significantly degraded compared to their historical average.
"""

import logging
from typing import Dict, Any, Optional

from ml.performance_dashboard import PerformanceDashboard

logger = logging.getLogger("trading.drift_detector")

# Threshold: If recent win rate drops by this much (absolute %) relative to overall, alert!
DRIFT_THRESHOLD_PCT = 0.15  # 15% drop in win-rate
RECENT_TRADE_WINDOW = 10    # Minimum trades to consider recent performance statistically relevant

class DriftDetector:
    def __init__(self, dashboard: Optional[PerformanceDashboard] = None):
        self.dashboard = dashboard or PerformanceDashboard()
        
    def check_for_drift(self):
        """
        Compare overall setup performance vs recent performance to detect degradation.
        """
        self.dashboard.refresh()
        overall_perf = self.dashboard.per_setup_performance()
        
        exits = self.dashboard._exits
        entry_map = self.dashboard._entry_map
        
        # Calculate recent performance per setup
        recent_stats = {}
        for exit_rec in exits[-50:]:  # Look at the last 50 trades overall
            trade_id = exit_rec.get("trade_id")
            entry_rec = entry_map.get(trade_id, {})
            setup_signals = entry_rec.get("setup_signals", [])
            pnl = exit_rec.get("pnl_pct", 0)
            is_win = pnl > 0
            
            for setup in setup_signals:
                name = setup.get("name", "Unknown")
                signal = setup.get("signal", "neutral")
                conf = setup.get("confidence", 0)
                if signal == "neutral" or conf <= 0:
                    continue
                    
                if name not in recent_stats:
                    recent_stats[name] = {"wins": 0, "total": 0}
                    
                recent_stats[name]["total"] += 1
                if is_win:
                    recent_stats[name]["wins"] += 1
                    
        # Compare and alert
        alerts_generated = False
        for name, recent in recent_stats.items():
            if recent["total"] >= RECENT_TRADE_WINDOW:
                recent_wr = recent["wins"] / recent["total"]
                overall = overall_perf.get(name, {})
                overall_wr = overall.get("win_rate", 0.0)
                
                # Check for negative drift
                if (overall_wr - recent_wr) >= DRIFT_THRESHOLD_PCT:
                    logger.warning(
                        f"⚠️ CONCEPT DRIFT DETECTED: Setup '{name}' "
                        f"overall win-rate is {overall_wr*100:.1f}%, but recent "
                        f"win-rate (last {recent['total']} trades) dropped to {recent_wr*100:.1f}%!"
                    )
                    alerts_generated = True
                    
        if not alerts_generated:
            logger.info("No concept drift detected across active setups.")
            
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    detector = DriftDetector()
    detector.check_for_drift()
