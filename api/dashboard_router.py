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

@router.get("/portfolio")
async def get_portfolio():
    async with async_session_factory() as session:
        acc_stmt = select(Account)
        acc_res = await session.execute(acc_stmt)
        account = acc_res.scalar_one_or_none()
        
        trade_stmt = select(Trade).where(Trade.is_open == True)
        trade_res = await session.execute(trade_stmt)
        open_trades = trade_res.scalars().all()
        
        account_data = {
            "capital": account.capital if account else 0.0,
            "peak_capital": account.peak_capital if account else 0.0,
            "status": account.status if account else "UNKNOWN"
        }
        
        trades_data = []
        for t in open_trades:
            trades_data.append({
                "order_id": t.order_id,
                "ticker": t.ticker,
                "direction": t.direction,
                "entry_price": t.entry_price,
                "quantity": t.quantity,
                "invested": t.invested,
                "take_profit": t.take_profit,
                "stop_loss": t.stop_loss
            })
            
        return {
            "account": account_data,
            "open_trades": trades_data
        }

@router.get("/analytics")
async def get_analytics():
    async with async_session_factory() as session:
        # Fetch all closed trades to compute equity curve
        stmt = select(Trade).where(Trade.is_open == False).order_by(Trade.exit_time.asc())
        res = await session.execute(stmt)
        closed_trades = res.scalars().all()
        
        acc_stmt = select(Account)
        acc_res = await session.execute(acc_stmt)
        account = acc_res.scalar_one_or_none()
        
        starting_capital = 100000.0
        current_capital = starting_capital
        
        equity_curve = []
        win_by_day = {0:0, 1:0, 2:0, 3:0, 4:0, 5:0, 6:0}
        total_by_day = {0:0, 1:0, 2:0, 3:0, 4:0, 5:0, 6:0}
        
        wins = 0
        losses = 0
        
        for t in closed_trades:
            if t.pnl_pct is not None:
                pnl_amt = (t.pnl_pct / 100.0) * t.invested
                current_capital += pnl_amt
                
                # Append to equity curve
                if t.exit_time:
                    equity_curve.append({
                        "time": t.exit_time.timestamp(),
                        "value": current_capital
                    })
                    
                    # Group by day of week
                    day = t.exit_time.weekday()
                    total_by_day[day] += 1
                    if t.pnl_pct > 0:
                        win_by_day[day] += 1
                        wins += 1
                    else:
                        losses += 1
                        
        win_rate = (wins / len(closed_trades) * 100) if len(closed_trades) > 0 else 0
        
        # Calculate Risk of Ruin (simplified formula based on win rate and reward/risk ratio)
        # For this prototype, if win_rate > 50, risk of ruin is low.
        probability_of_ruin = max(0.0, 100.0 - (win_rate * 1.5))
        
        return {
            "equity_curve": equity_curve,
            "win_rate": win_rate,
            "total_trades": len(closed_trades),
            "probability_of_ruin": min(100.0, probability_of_ruin),
            "win_by_day": {
                "Monday": (win_by_day[0] / total_by_day[0] * 100) if total_by_day[0] else 0,
                "Tuesday": (win_by_day[1] / total_by_day[1] * 100) if total_by_day[1] else 0,
                "Wednesday": (win_by_day[2] / total_by_day[2] * 100) if total_by_day[2] else 0,
                "Thursday": (win_by_day[3] / total_by_day[3] * 100) if total_by_day[3] else 0,
                "Friday": (win_by_day[4] / total_by_day[4] * 100) if total_by_day[4] else 0,
            }
        }
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
