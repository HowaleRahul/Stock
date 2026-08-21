import threading
import collections
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List

from ml.continuous_trainer import run_training_loop
from api.auth import get_api_key, rate_limiter

router = APIRouter(prefix="/api/v1/training", tags=["Training"])

# Thread-safe state using deque and lock
_lock = threading.Lock()
training_thread = None
stop_event = threading.Event()
training_logs = collections.deque(maxlen=200)
is_training = False


class TrainingStatus(BaseModel):
    is_training: bool
    logs: List[str]


def _log_callback(msg: str):
    with _lock:
        training_logs.append(msg)


def _training_worker():
    global is_training
    try:
        run_training_loop(stop_event, _log_callback)
    except Exception as e:
        _log_callback(f"🛑 CRITICAL ERROR in training: {e}")
    finally:
        with _lock:
            is_training = False


@router.post("/start")
async def start_training(
    _api_key: str = Depends(get_api_key),
    _rate_limit: bool = Depends(rate_limiter(5))
):
    global training_thread, is_training

    with _lock:
        if is_training:
            return {"status": "already_running"}

        stop_event.clear()
        training_logs.clear()
        is_training = True

    training_thread = threading.Thread(target=_training_worker, daemon=True)
    training_thread.start()

    return {"status": "started"}


@router.post("/stop")
async def stop_training(
    _api_key: str = Depends(get_api_key)
):
    global is_training
    with _lock:
        if not is_training:
            return {"status": "not_running"}

    stop_event.set()
    return {"status": "stopping"}


@router.get("/status", response_model=TrainingStatus)
async def get_status():
    with _lock:
        return {
            "is_training": is_training,
            "logs": list(training_logs)
        }
