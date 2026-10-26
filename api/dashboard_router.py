import os
import json
import logging
import tempfile
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.concurrency import run_in_threadpool
from typing import Dict, Any, Literal, Optional
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select

from ml.performance_dashboard import PerformanceDashboard
from ml.trade_logger import TradeLogger
from ml.journal_analyzer import JournalAnalyzer
from ml.reinforcement_learner import ReinforcementLearner
from api.db import async_session_factory
from models.models import Account, JournalEvent, Trade, TradeContext
from api.auth import get_api_key, rate_limiter
from api.config_store import (
    CONFIG_PATH,
    _config_file_lock,
    load_config_atomic,
    save_config_atomic,
    update_config_atomic,
)

logger = logging.getLogger("trading.api.dashboard")

router = APIRouter(
    prefix="/api/v1/dashboard",
    tags=["Dashboard"],
    dependencies=[Depends(get_api_key)],
)

# Whitelist of allowed config keys to prevent arbitrary injection
class ConfigUpdate(BaseModel):
    """Only allow values that preserve the trading configuration invariants."""
    model_config = ConfigDict(extra="forbid")
    environment: Optional[Literal["PAPER", "LIVE"]] = None
    capital: Optional[float] = Field(default=None, gt=0, le=1_000_000_000, allow_inf_nan=False)
    risk_per_trade_pct: Optional[float] = Field(default=None, gt=0, le=0.05, allow_inf_nan=False)
    max_portfolio_drawdown_pct: Optional[float] = Field(default=None, gt=0, le=1, allow_inf_nan=False)
    min_ai_confidence: Optional[float] = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    min_consensus_weight: Optional[float] = Field(default=None, ge=0.4, le=3.0, allow_inf_nan=False)
    min_risk_reward_ratio: Optional[float] = Field(default=None, gt=0, le=100, allow_inf_nan=False)
    retrain_interval_days: Optional[int] = Field(default=None, ge=1, le=365)
    drift_check_interval_hours: Optional[int] = Field(default=None, ge=1, le=8760)


from fastapi import APIRouter, Depends, HTTPException, Query

@router.get("/metrics")
async def get_metrics(_rate_limit: bool = Depends(rate_limiter(60))):
    """Get portfolio summary, regime performance, and setup performance."""
    def _compute_metrics():
        perf_board = PerformanceDashboard()
        return {
            "summary": perf_board.portfolio_summary(),
            "setup_perf": perf_board.per_setup_performance(),
            "regime_perf": perf_board.per_regime_performance(),
            "rolling_win_rate": perf_board.rolling_win_rate()
        }
    return await run_in_threadpool(_compute_metrics)


@router.get("/portfolio")
async def get_portfolio(_rate_limit: bool = Depends(rate_limiter(60))):
    """Get paper trading portfolio stats and open trades from the database, with JSON fallback."""
    try:
        async with async_session_factory() as session:
            try:
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
                    # Extract context if present for F&O Greeks
                    ctx = {}
                    try:
                        ctx_stmt = select(TradeContext).where(TradeContext.order_id == t.order_id)
                        ctx_row = (await session.execute(ctx_stmt)).scalar_one_or_none()
                        if ctx_row:
                            ctx = json.loads(ctx_row.payload)
                    except Exception:
                        pass

                    trades_data.append({
                        "order_id": t.order_id,
                        "ticker": t.ticker,
                        "direction": t.direction,
                        "action": ctx.get("action", "BUY" if t.direction == "BUY" else "SELL"),
                        "strategy_type": ctx.get("strategy_type", "DIRECTIONAL"),
                        "entry_price": t.entry_price,
                        "quantity": t.quantity,
                        "invested": t.invested,
                        "take_profit": t.take_profit,
                        "stop_loss": t.stop_loss,
                        "is_fo": ctx.get("is_fo", True),
                        "instrument_type": ctx.get("instrument_type", "OPTION" if ("CE" in t.ticker or "PE" in t.ticker) else "FUTURE"),
                        "opt_type": ctx.get("opt_type", "CE" if "CE" in t.ticker else ("PE" if "PE" in t.ticker else "FUT")),
                        "opt_strike": ctx.get("opt_strike", 0.0),
                        "opt_delta": ctx.get("opt_delta", 0.5),
                        "opt_theta": ctx.get("opt_theta", 0.0),
                        "opt_gamma": ctx.get("opt_gamma", 0.0),
                        "opt_vega": ctx.get("opt_vega", 0.0),
                        "opt_rho": ctx.get("opt_rho", 0.0),
                        "opt_iv": ctx.get("opt_iv", 0.0),
                        "unrealized_pnl": ctx.get("unrealized_pnl", 0.0),
                        "strike_type": ctx.get("strike_type", "ATM"),
                        "lot_size": ctx.get("lot_size", 25),
                        "hedge_strike_price": ctx.get("hedge_strike_price"),
                        "hedge_entry_price": ctx.get("hedge_entry_price"),
                        "net_credit": ctx.get("net_credit"),
                        "short_put_strike": ctx.get("short_put_strike"),
                        "long_put_strike": ctx.get("long_put_strike"),
                        "short_call_strike": ctx.get("short_call_strike"),
                        "long_call_strike": ctx.get("long_call_strike"),
                        "lower_breakeven": ctx.get("lower_breakeven"),
                        "upper_breakeven": ctx.get("upper_breakeven"),
                    })
                    
                return {
                    "account": account_data,
                    "open_trades": trades_data
                }
            except Exception:
                await session.rollback()
                raise
    except Exception as db_err:
        logger.warning(f"Database query failed in /portfolio; using local fallback: {db_err}")
        account_data = {"capital": 1000000.0, "peak_capital": 1000000.0, "status": "ACTIVE"}
        if os.path.exists("paper_account.json"):
            try:
                with open("paper_account.json", "r", encoding="utf-8") as f:
                    account_data = json.load(f)
            except Exception:
                pass

        trades_data = []
        if os.path.exists("paper_trades.json"):
            try:
                with open("paper_trades.json", "r", encoding="utf-8") as f:
                    all_trades = json.load(f)
                    for t in all_trades:
                        if t.get("status") == "OPEN":
                            trades_data.append({
                                "order_id": t.get("id"),
                                "ticker": t.get("ticker"),
                                "direction": t.get("direction"),
                                "action": t.get("action", "BUY" if t.get("direction") == "BUY" else "SELL"),
                                "strategy_type": t.get("strategy_type", "DIRECTIONAL"),
                                "entry_price": t.get("entry_price"),
                                "quantity": t.get("quantity"),
                                "invested": t.get("invested"),
                                "take_profit": t.get("tp"),
                                "stop_loss": t.get("sl"),
                                "is_fo": t.get("is_fo", True),
                                "instrument_type": t.get("instrument_type", "OPTION" if ("CE" in str(t.get("ticker")) or "PE" in str(t.get("ticker"))) else "FUTURE"),
                                "opt_type": t.get("opt_type", "CE" if "CE" in str(t.get("ticker")) else "PE"),
                                "opt_strike": t.get("opt_strike", 0.0),
                                "opt_delta": t.get("opt_delta", 0.5),
                                "opt_theta": t.get("opt_theta", 0.0),
                                "opt_gamma": t.get("opt_gamma", 0.0),
                                "opt_vega": t.get("opt_vega", 0.0),
                                "opt_rho": t.get("opt_rho", 0.0),
                                "opt_iv": t.get("opt_iv", 0.0),
                                "unrealized_pnl": t.get("unrealized_pnl", 0.0),
                                "strike_type": t.get("strike_type", "ATM"),
                                "lot_size": t.get("lot_size", 25),
                                "hedge_strike_price": t.get("hedge_strike_price"),
                                "hedge_entry_price": t.get("hedge_entry_price"),
                                "net_credit": t.get("net_credit"),
                                "short_put_strike": t.get("short_put_strike"),
                                "long_put_strike": t.get("long_put_strike"),
                                "short_call_strike": t.get("short_call_strike"),
                                "long_call_strike": t.get("long_call_strike"),
                                "lower_breakeven": t.get("lower_breakeven"),
                                "upper_breakeven": t.get("upper_breakeven"),
                            })
            except Exception:
                pass

        return {
            "account": account_data,
            "open_trades": trades_data
        }


@router.get("/analytics")
async def get_analytics(_rate_limit: bool = Depends(rate_limiter(30))):
    """Compute equity curve, win rate by day, and probability of ruin, with local fallback."""
    closed_trades = []
    try:
        async with async_session_factory() as session:
            try:
                stmt = select(Trade).where(Trade.is_open == False).order_by(Trade.exit_time.asc())
                res = await session.execute(stmt)
                closed_trades = list(res.scalars().all())
            except Exception:
                await session.rollback()
                raise
    except Exception as db_err:
        logger.warning(f"Database query failed in /analytics; using local fallback: {db_err}")
        if os.path.exists("paper_trades.json"):
            try:
                import types
                from datetime import datetime
                with open("paper_trades.json", "r", encoding="utf-8") as f:
                    all_trades = json.load(f)
                    for pt in all_trades:
                        if pt.get("status") in ("CLOSED_WIN", "CLOSED_LOSS", "TRAILING_SL", "TIME_EXIT", "STOP_LOSS", "TAKE_PROFIT", "INTRADAY_SQUARE_OFF"):
                            t_obj = types.SimpleNamespace()
                            # Database schema stores percentage as e.g. 2.5 for 2.5%
                            t_obj.pnl_pct = (pt.get("pnl_pct", 0.0) or 0.0) * 100.0
                            t_obj.invested = float(pt.get("invested", 10000.0))
                            t_str = pt.get("closed_at")
                            try:
                                t_obj.exit_time = datetime.fromisoformat(t_str) if t_str else None
                            except Exception:
                                t_obj.exit_time = None
                            closed_trades.append(t_obj)
            except Exception as json_err:
                logger.debug(f"JSON fallback in analytics failed: {json_err}")

    import math
    starting_capital = 100000.0
    try:
        config = load_config_atomic(CONFIG_PATH)
        cfg_cap = float(config.get("capital", starting_capital))
        if cfg_cap > 0 and math.isfinite(cfg_cap):
            starting_capital = cfg_cap
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        logger.warning("Unable to read configured starting capital; using fallback.")
    current_capital = starting_capital

    equity_curve = []
    win_by_day = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0}
    total_by_day = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0}

    wins = 0
    losses = 0

    for t in closed_trades:
        raw_pnl = getattr(t, "pnl_pct", None)
        if raw_pnl is not None and math.isfinite(raw_pnl):
            invested = float(getattr(t, "invested", 10000.0) or 10000.0)
            if not math.isfinite(invested) or invested <= 0:
                invested = 10000.0
            pnl_amt = (raw_pnl / 100.0) * invested
            current_capital += pnl_amt
            if raw_pnl > 0:
                wins += 1
            else:
                losses += 1

            exit_t = getattr(t, "exit_time", None)
            if exit_t:
                equity_curve.append({
                    "time": exit_t.timestamp(),
                    "value": round(current_capital, 2)
                })

                day = exit_t.weekday()
                total_by_day[day] += 1
                if raw_pnl > 0:
                    win_by_day[day] += 1

    completed_trades = wins + losses
    win_rate = (wins / completed_trades * 100) if completed_trades > 0 else 0

    # Mathematically rigorous probability of ruin (Gambler's Ruin with asymmetric payoffs)
    if completed_trades >= 5 and wins > 0 and losses > 0:
        win_pnls = [t.pnl_pct for t in closed_trades if getattr(t, "pnl_pct", None) is not None and t.pnl_pct > 0]
        loss_pnls = [abs(t.pnl_pct) for t in closed_trades if getattr(t, "pnl_pct", None) is not None and t.pnl_pct <= 0]
        avg_w = float(sum(win_pnls) / len(win_pnls)) if win_pnls else 1.0
        avg_l = float(sum(loss_pnls) / len(loss_pnls)) if loss_pnls else 1.0
        p = max(0.01, min(0.99, wins / completed_trades))
        q = 1.0 - p
        payoff = avg_w / avg_l if avg_l > 0 else 1.0
        edge = (p * payoff) - q
        if edge <= 0:
            probability_of_ruin = 99.0
        else:
            ratio = q / (p * payoff) if (p * payoff) > 0 else 1.0
            n_units = -math.log(0.5) / 0.02  # 50% account drawdown threshold at 2% risk
            try:
                ruin_val = (ratio ** n_units) * 100.0
                probability_of_ruin = round(min(100.0, max(0.0, ruin_val)), 2)
            except (OverflowError, ValueError):
                probability_of_ruin = 99.0
    elif completed_trades > 0 and wins == 0:
        probability_of_ruin = 99.0
    elif completed_trades > 0 and losses == 0:
        probability_of_ruin = 0.01
    else:
        probability_of_ruin = 0.0

    return {
        "equity_curve": equity_curve,
        "win_rate": round(win_rate, 2),
        "total_trades": completed_trades,
        "probability_of_ruin": probability_of_ruin,
        "win_by_day": {
            "Monday": round(win_by_day[0] / total_by_day[0] * 100, 2) if total_by_day[0] else 0,
            "Tuesday": round(win_by_day[1] / total_by_day[1] * 100, 2) if total_by_day[1] else 0,
            "Wednesday": round(win_by_day[2] / total_by_day[2] * 100, 2) if total_by_day[2] else 0,
            "Thursday": round(win_by_day[3] / total_by_day[3] * 100, 2) if total_by_day[3] else 0,
            "Friday": round(win_by_day[4] / total_by_day[4] * 100, 2) if total_by_day[4] else 0,
            "Saturday": round(win_by_day[5] / total_by_day[5] * 100, 2) if total_by_day[5] else 0,
            "Sunday": round(win_by_day[6] / total_by_day[6] * 100, 2) if total_by_day[6] else 0,
        }
    }


@router.get("/trades")
async def get_trades(
    limit: int = Query(500, ge=1, le=5000, description="Max journal events to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    _rate_limit: bool = Depends(rate_limiter(60))
):
    """Get persisted journal events, with legacy JSON fallback."""
    events = []
    try:
        async with async_session_factory() as session:
            try:
                result = await session.execute(
                    select(JournalEvent)
                    .order_by(JournalEvent.timestamp.desc())
                    .offset(offset)
                    .limit(limit)
                )
                events = list(reversed(result.scalars().all()))
            except Exception:
                await session.rollback()
                raise
    except Exception as db_err:
        logger.warning(f"Database query failed in /trades; using JSON fallback: {db_err}")

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
async def get_config(_rate_limit: bool = Depends(rate_limiter(60))):
    """Get current configuration."""
    try:
        return load_config_atomic(CONFIG_PATH)
    except (OSError, ValueError, json.JSONDecodeError):
        logger.exception("Configuration store is unreadable")
        raise HTTPException(status_code=503, detail="Configuration store is unavailable.")


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
    
    try:
        update_config_atomic(filtered, CONFIG_PATH)
        return {"status": "success", "updated_keys": list(filtered.keys())}
    except (OSError, ValueError, json.JSONDecodeError):
        logger.exception("Configuration store is unreadable")
        raise HTTPException(status_code=503, detail="Configuration store is unavailable.")


@router.get("/ai-journal")
async def get_ai_journal(_rate_limit: bool = Depends(rate_limiter(20))):
    """
    Returns the AI's self-play journal: current RL weights, profitability
    matrix, recent trade insights, and portfolio summary.
    """
    try:
        def _analyze():
            analyzer = JournalAnalyzer()
            report = analyzer.analyze()
            learner = ReinforcementLearner()
            rl_weights = learner.get_deterministic_weights()
            diagnostics = learner.get_diagnostics()
            recent_exits = TradeLogger.get_recent_exits(n_days=30)
            return report, rl_weights, diagnostics, recent_exits

        report, rl_weights, diagnostics, recent_exits = await run_in_threadpool(_analyze)

        # Get the last 20 trades for display
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


