import os
import json
from fastapi import APIRouter
from typing import Dict, Any

from ml.performance_dashboard import PerformanceDashboard
from ml.trade_logger import TradeLogger

router = APIRouter(prefix="/api/v1/dashboard", tags=["Dashboard"])

CONFIG_PATH = "config.json"

@router.get("/metrics")
async def get_metrics():
    """Get portfolio summary, regime performance, and setup performance."""
    perf_board = PerformanceDashboard()
    return {
        "summary": perf_board.portfolio_summary(),
        "setup_perf": perf_board.per_setup_performance(),
        "regime_perf": perf_board.per_regime_performance(),
        "rolling_win_rate": perf_board.rolling_win_rate()
    }

@router.get("/trades")
async def get_trades():
    """Get all open and closed trades."""
    entries = TradeLogger.get_all_entries()
    exits = TradeLogger.get_all_exits()
    return {
        "entries": entries,
        "exits": exits
    }

@router.get("/config")
async def get_config():
    """Get current configuration."""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    return {}

@router.post("/config")
async def update_config(new_config: Dict[str, Any]):
    """Update configuration."""
    # Merge with existing
    config = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            config = json.load(f)
    
    config.update(new_config)
    
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=4)
        
    return {"status": "success"}
