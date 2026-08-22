import os
import json
import logging
import tempfile
from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any, Literal, Optional
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select

from ml.performance_dashboard import PerformanceDashboard
from ml.trade_logger import TradeLogger
from ml.journal_analyzer import JournalAnalyzer
from ml.reinforcement_learner import ReinforcementLearner
from api.db import async_session_factory
from models.models import Account, JournalEvent, Trade
from api.auth import get_api_key, rate_limiter

logger = logging.getLogger("trading.api.dashboard")

router = APIRouter(
    prefix="/api/v1/dashboard",
    tags=["Dashboard"],
    dependencies=[Depends(get_api_key)],
)

CONFIG_PATH = "config.json"

# Whitelist of allowed config keys to prevent arbitrary injection
class ConfigUpdate(BaseModel):
    """Only allow values that preserve the trading configuration invariants."""
    model_config = ConfigDict(extra="forbid")
    environment: Optional[Literal["PAPER", "LIVE"]] = None
    capital: Optional[float] = Field(default=None, gt=0, le=1_000_000_000)
    risk_per_trade_pct: Optional[float] = Field(default=None, gt=0, le=0.05)
    max_portfolio_drawdown_pct: Optional[float] = Field(default=None, gt=0, le=1)
    min_ai_confidence: Optional[float] = Field(default=None, ge=0, le=1)
    min_risk_reward_ratio: Optional[float] = Field(default=None, gt=0, le=100)
    retrain_interval_days: Optional[int] = Field(default=None, ge=1, le=365)
    drift_check_interval_hours: Optional[int] = Field(default=None, ge=1, le=8760)


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
    """Get paper trading portfolio stats and open trades from the database."""
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
    """Compute equity curve, win rate by day, and probability of ruin."""
    async with async_session_factory() as session:
        stmt = select(Trade).where(Trade.is_open == False).order_by(Trade.exit_time.asc())
        res = await session.execute(stmt)
        closed_trades = res.scalars().all()
        
        starting_capital = 100000.0
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    config = json.load(f)
                starting_capital = float(config.get("capital", starting_capital))
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                logger.warning("Unable to read configured starting capital; using fallback.")
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
                
                if t.exit_time:
                    equity_curve.append({
                        "time": t.exit_time.timestamp(),
                        "value": current_capital
                    })
                    
                    day = t.exit_time.weekday()
                    total_by_day[day] += 1
                    if t.pnl_pct > 0:
                        win_by_day[day] += 1
                        wins += 1
                    else:
                        losses += 1
                        
        completed_trades = wins + losses
        win_rate = (wins / completed_trades * 100) if completed_trades > 0 else 0
        probability_of_ruin = max(0.0, 100.0 - (win_rate * 1.5))
        
        return {
            "equity_curve": equity_curve,
            "win_rate": win_rate,
            "total_trades": completed_trades,
            "probability_of_ruin": min(100.0, probability_of_ruin),
            "win_by_day": {
                "Monday": (win_by_day[0] / total_by_day[0] * 100) if total_by_day[0] else 0,
                "Tuesday": (win_by_day[1] / total_by_day[1] * 100) if total_by_day[1] else 0,
                "Wednesday": (win_by_day[2] / total_by_day[2] * 100) if total_by_day[2] else 0,
                "Thursday": (win_by_day[3] / total_by_day[3] * 100) if total_by_day[3] else 0,
                "Friday": (win_by_day[4] / total_by_day[4] * 100) if total_by_day[4] else 0,
            }
        }


@router.get("/trades")
async def get_trades():
    """Get persisted journal events, with legacy JSON fallback."""
    async with async_session_factory() as session:
        result = await session.execute(select(JournalEvent).order_by(JournalEvent.timestamp.asc()))
        events = result.scalars().all()

    if events:
        records = []
        for event in events:
            try:
                records.append(json.loads(event.payload))
            except (TypeError, json.JSONDecodeError):
                logger.warning("Skipping malformed journal event %s", event.id)
        entries = [record for record in records if record.get("event") == "ENTRY"]
        exits = [record for record in records if record.get("event") == "EXIT"]
    else:
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
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                config = json.load(f)
            if not isinstance(config, dict):
                raise ValueError("configuration root is not an object")
            return config
        except (OSError, ValueError, json.JSONDecodeError):
            logger.exception("Configuration store is unreadable")
            raise HTTPException(status_code=503, detail="Configuration store is unavailable.")
    return {}


@router.post("/config")
async def update_config(
    new_config: ConfigUpdate,
    _api_key: str = Depends(get_api_key),
    _rate_limit: bool = Depends(rate_limiter(10))
):
    """Update configuration (authenticated, validated)."""
    filtered = new_config.model_dump(exclude_none=True)
    if not filtered:
        return {"status": "error", "message": "No valid configuration keys provided."}
    
    config = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                config = json.load(f)
            if not isinstance(config, dict):
                raise ValueError("configuration root is not an object")
        except (OSError, ValueError, json.JSONDecodeError):
            logger.exception("Configuration store is unreadable")
            raise HTTPException(status_code=503, detail="Configuration store is unavailable.")
    
    config.update(filtered)
    
    directory = os.path.dirname(os.path.abspath(CONFIG_PATH))
    fd, temp_path = tempfile.mkstemp(dir=directory, prefix=".config-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, CONFIG_PATH)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        
    return {"status": "success", "updated_keys": list(filtered.keys())}


@router.get("/ai-journal")
async def get_ai_journal():
    """
    Returns the AI's self-play journal: current RL weights, profitability
    matrix, recent trade insights, and portfolio summary.
    """
    try:
        analyzer = JournalAnalyzer()
        report = analyzer.analyze()

        learner = ReinforcementLearner()
        rl_weights = learner.get_deterministic_weights()
        diagnostics = learner.get_diagnostics()

        # Get the last 20 trades for display
        recent_exits = TradeLogger.get_recent_exits(n_days=30)
        recent_trades = []
        for exit_rec in recent_exits[-20:]:
            recent_trades.append({
                "trade_id": exit_rec.get("trade_id"),
                "ticker": exit_rec.get("ticker"),
                "direction": exit_rec.get("direction"),
                "exit_reason": exit_rec.get("exit_reason"),
                "pnl_pct": round(exit_rec.get("pnl_pct", 0) * 100, 2) if exit_rec.get("pnl_pct") is not None else None,
                "bars_held": exit_rec.get("bars_held"),
                "regime": exit_rec.get("regime_at_exit"),
            })

        return {
            "summary": report.get("summary", {}),
            "insights": report.get("insights", []),
            "profitability_matrix": report.get("profitability_matrix", {}),
            "rl_weights": rl_weights,
            "rl_diagnostics": diagnostics,
            "recent_trades": recent_trades,
        }
    except Exception as e:
        logger.error(f"AI Journal endpoint failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate AI journal.")

