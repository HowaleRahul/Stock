import asyncio
import threading
import collections
import json
import logging
import os
import tempfile
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Literal, Optional

from ml.continuous_trainer import run_training_loop, get_training_telemetry
from data.market_hours import get_market_status
from api.auth import get_api_key, rate_limiter
from api.config_store import _config_file_lock, update_config_atomic

router = APIRouter(
    prefix="/api/v1/training",
    tags=["Training"],
    dependencies=[Depends(get_api_key)],
)

# Thread-safe state using deque and lock
_lock = threading.Lock()
training_thread = None
stop_event = threading.Event()
training_logs = collections.deque(maxlen=200)
is_training = False
current_training_mode = "auto"
CONFIG_PATH = "config.json"
logger = logging.getLogger("trading.api.training")


class StartTrainingRequest(BaseModel):
    mode: Optional[Literal["auto", "simulate_live", "offline_only", "force_live", "live_only"]] = Field(
        default="auto",
        description="Training mode: 'auto' (live during NSE hours, replay when closed), 'simulate_live' (force live execution), 'offline_only' (historical only)"
    )
    capital: Optional[float] = Field(
        default=None,
        gt=0,
        le=1_000_000_000,
        allow_inf_nan=False,
        description="Custom trading capital in INR (e.g. 10000 for 10k, 50000, 100000, etc.)"
    )
    target_index: Optional[Literal["NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY", "MIDCPNIFTY", "ALL"]] = Field(
        default="ALL",
        description="Target index: 'NIFTY', 'BANKNIFTY', 'SENSEX', 'FINNIFTY', 'MIDCPNIFTY', or 'ALL'"
    )
    derivative_type: Optional[Literal["AUTO", "OPTIONS", "FUTURES", "SELL_OPTIONS", "CREDIT_SPREAD", "IRON_CONDOR"]] = Field(
        default="AUTO",
        description="Derivative instrument: 'AUTO' (budget-optimized), 'OPTIONS' (CE/PE), 'FUTURES', 'SELL_OPTIONS', 'CREDIT_SPREAD', 'IRON_CONDOR'"
    )
    strike_preference: Optional[Literal["AUTO", "ITM", "ATM", "OTM"]] = Field(
        default="AUTO",
        description="Strike selection preference: 'AUTO' (AI learned), 'ITM', 'ATM', 'OTM'"
    )


class TrainingStatus(BaseModel):
    is_training: bool
    mode: str
    market_status: Dict[str, Any]
    portfolio: Optional[Dict[str, Any]] = None
    replay_telemetry: Optional[Dict[str, Any]] = None
    cycles: int = 0
    logs: List[str]
    target_index: Optional[str] = "ALL"
    derivative_type: Optional[str] = "AUTO"
    strike_preference: Optional[str] = "AUTO"


def _log_callback(msg: str):
    with _lock:
        training_logs.append(msg)


def _training_worker(
    mode: str,
    capital: Optional[float] = None,
    target_index: Optional[str] = None,
    derivative_type: Optional[str] = None,
    strike_preference: Optional[str] = None,
):
    global is_training
    try:
        run_training_loop(
            stop_event,
            _log_callback,
            mode=mode,
            capital=capital,
            target_index=target_index,
            derivative_type=derivative_type,
            strike_preference=strike_preference
        )
    except Exception as e:
        _log_callback(f"🛑 CRITICAL ERROR in training: {e}")
    finally:
        with _lock:
            is_training = False


def _persist_training_config(
    capital: Optional[float],
    target_index: str,
    derivative_type: str,
    strike_preference: str,
) -> None:
    updates: Dict[str, Any] = {
        "target_index": target_index,
        "derivative_type": derivative_type,
        "strike_preference": strike_preference,
    }
    if capital is not None:
        updates["capital"] = capital

    try:
        update_config_atomic(updates, CONFIG_PATH)
    except Exception as exc:
        logger.exception("Unable to persist training configuration.")
        raise HTTPException(
            status_code=500,
            detail="Unable to persist training configuration; training was not started.",
        ) from exc


@router.post("/start")
async def start_training(
    payload: Optional[StartTrainingRequest] = None,
    _api_key: str = Depends(get_api_key),
    _rate_limit: bool = Depends(rate_limiter(60))
):
    global training_thread, is_training, current_training_mode

    chosen_mode = payload.mode if payload and payload.mode else "auto"
    chosen_capital = payload.capital if payload and payload.capital else None
    chosen_target_index = payload.target_index if payload and payload.target_index else "ALL"
    chosen_derivative_type = payload.derivative_type if payload and payload.derivative_type else "AUTO"
    chosen_strike_pref = payload.strike_preference if payload and payload.strike_preference else "AUTO"

    with _lock:
        if training_thread is not None and training_thread.is_alive():
            if stop_event.is_set():
                return {"status": "stopping_in_progress", "detail": "Previous training loop is terminating. Please retry in a few seconds."}
            return {"status": "already_running", "mode": current_training_mode}
        if is_training:
            return {"status": "already_running", "mode": current_training_mode}

        _persist_training_config(
            chosen_capital, chosen_target_index, chosen_derivative_type, chosen_strike_pref
        )

        stop_event.clear()
        training_logs.clear()
        is_training = True
        current_training_mode = chosen_mode

        try:
            training_thread = threading.Thread(
                target=_training_worker,
                args=(chosen_mode, chosen_capital, chosen_target_index, chosen_derivative_type, chosen_strike_pref),
                daemon=True
            )
            training_thread.start()
        except Exception as e:
            is_training = False
            logger.error(f"Failed to start training thread: {e}")
            raise HTTPException(status_code=500, detail="Failed to start training thread.")

    return {
        "status": "started",
        "mode": chosen_mode,
        "target_index": chosen_target_index,
        "derivative_type": chosen_derivative_type,
        "strike_preference": chosen_strike_pref,
        "market_status": get_market_status("NSE")
    }


@router.post("/stop")
async def stop_training(
    _api_key: str = Depends(get_api_key),
    _rate_limit: bool = Depends(rate_limiter(10))
):
    global is_training, training_thread
    with _lock:
        if not is_training and (training_thread is None or not training_thread.is_alive()):
            return {"status": "not_running"}

        stop_event.set()
        is_training = False

    # Perform cooperative join with brief timeout in background thread to avoid blocking event loop
    if training_thread and training_thread.is_alive():
        try:
            await asyncio.to_thread(training_thread.join, 1.5)
        except Exception:
            pass

    return {"status": "stopped"}


@router.get("/status", response_model=TrainingStatus)
async def get_status(
    _rate_limit: bool = Depends(rate_limiter(60))
):
    with _lock:
        is_stopping = stop_event.is_set()
        still_running = (not is_stopping) and (is_training or (training_thread is not None and training_thread.is_alive()))
        telemetry = get_training_telemetry()
        current_logs = list(training_logs)

        p_data = telemetry.get("portfolio") or {}
        return {
            "is_training": still_running,
            "mode": "IDLE" if is_stopping else telemetry.get("mode", current_training_mode if still_running else "IDLE"),
            "market_status": telemetry.get("market_status", get_market_status("NSE")),
            "portfolio": telemetry.get("portfolio"),
            "replay_telemetry": telemetry.get("replay_telemetry"),
            "cycles": telemetry.get("cycles", 0),
            "logs": current_logs,
            "target_index": p_data.get("target_index", "ALL"),
            "derivative_type": p_data.get("derivative_type", "AUTO"),
            "strike_preference": p_data.get("strike_preference", "AUTO")
        }


@router.get("/live-portfolio")
async def get_live_portfolio(
    _rate_limit: bool = Depends(rate_limiter(60))
):
    """
    Returns real-time ticking Mark-to-Market (MTM) PnL and active open positions.
    """
    telemetry = get_training_telemetry()
    return {
        "portfolio": telemetry.get("portfolio"),
        "market_status": telemetry.get("market_status", get_market_status("NSE")),
        "mode": telemetry.get("mode", "IDLE")
    }
