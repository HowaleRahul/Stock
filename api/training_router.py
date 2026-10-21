import threading
import collections
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

from ml.continuous_trainer import run_training_loop, get_training_telemetry
from data.market_hours import get_market_status
from api.auth import get_api_key, rate_limiter

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


class StartTrainingRequest(BaseModel):
    mode: Optional[str] = Field(
        default="auto",
        description="Training mode: 'auto' (live during NSE hours, replay when closed), 'simulate_live' (force live execution), 'offline_only' (historical only)"
    )
    capital: Optional[float] = Field(
        default=None,
        gt=0,
        description="Custom trading capital in INR (e.g. 10000 for 10k, 50000, 100000, etc.)"
    )
    target_index: Optional[str] = Field(
        default="ALL",
        description="Target index: 'NIFTY', 'BANKNIFTY', 'FINNIFTY', or 'ALL'"
    )
    derivative_type: Optional[str] = Field(
        default="AUTO",
        description="Derivative instrument: 'AUTO' (budget-optimized), 'OPTIONS' (CE/PE), 'FUTURES', 'EQUITY'"
    )
    strike_preference: Optional[str] = Field(
        default="AUTO",
        description="Strike selection preference: 'AUTO' (AI learned), 'ITM', 'ATM', 'OTM'"
    )


class TrainingStatus(BaseModel):
    is_training: bool
    mode: str
    market_status: Dict[str, Any]
    portfolio: Optional[Dict[str, Any]] = None
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


@router.post("/start")
async def start_training(
    payload: Optional[StartTrainingRequest] = None,
    _api_key: str = Depends(get_api_key),
    _rate_limit: bool = Depends(rate_limiter(5))
):
    global training_thread, is_training, current_training_mode

    chosen_mode = payload.mode if payload and payload.mode else "auto"
    chosen_capital = payload.capital if payload and payload.capital else None
    chosen_target_index = payload.target_index if payload and payload.target_index else "ALL"
    chosen_derivative_type = payload.derivative_type if payload and payload.derivative_type else "AUTO"
    chosen_strike_pref = payload.strike_preference if payload and payload.strike_preference else "AUTO"

    # Persist choices to config
    try:
        import json, os
        cfg = {}
        if os.path.exists("config.json"):
            with open("config.json", "r", encoding="utf-8") as f:
                cfg = json.load(f)
        if chosen_capital is not None:
            cfg["capital"] = chosen_capital
        cfg["target_index"] = chosen_target_index
        cfg["derivative_type"] = chosen_derivative_type
        cfg["strike_preference"] = chosen_strike_pref
        with open("config.json.tmp", "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4)
        os.replace("config.json.tmp", "config.json")
    except Exception:
        pass

    with _lock:
        if is_training or (training_thread is not None and training_thread.is_alive()):
            return {"status": "already_running", "mode": current_training_mode}

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
            logger = __import__("logging").getLogger("trading.api.training")
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
    global is_training
    with _lock:
        if not is_training and (training_thread is None or not training_thread.is_alive()):
            return {"status": "not_running"}

    stop_event.set()
    return {"status": "stopping"}


@router.get("/status", response_model=TrainingStatus)
async def get_status(
    _rate_limit: bool = Depends(rate_limiter(60))
):
    with _lock:
        still_running = is_training or (training_thread is not None and training_thread.is_alive())
        telemetry = get_training_telemetry()
        current_logs = list(training_logs)

        p_data = telemetry.get("portfolio") or {}
        return {
            "is_training": still_running,
            "mode": telemetry.get("mode", current_training_mode if still_running else "IDLE"),
            "market_status": telemetry.get("market_status", get_market_status("NSE")),
            "portfolio": telemetry.get("portfolio"),
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
