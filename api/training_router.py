import threading
from fastapi import APIRouter
from pydantic import BaseModel
from typing import List

from ml.continuous_trainer import run_training_loop

router = APIRouter(prefix="/api/v1/training", tags=["Training"])

# Global state
training_thread = None
stop_event = threading.Event()
training_logs = []
cycles_completed = 0
is_training = False

class TrainingStatus(BaseModel):
    is_training: bool
    logs: List[str]

def _log_callback(msg: str):
    global cycles_completed
    training_logs.append(msg)
    if len(training_logs) > 100:
        training_logs.pop(0)
    
    if "[CYCLE" in msg:
        cycles_completed += 1

def _training_worker():
    global is_training
    try:
        run_training_loop(stop_event, _log_callback)
    except Exception as e:
        _log_callback(f"🛑 CRITICAL ERROR in training: {e}")
    finally:
        is_training = False

@router.post("/start")
async def start_training():
    global training_thread, is_training
    
    if is_training:
        return {"status": "already_running"}
        
    stop_event.clear()
    training_logs.clear()
    is_training = True
    
    training_thread = threading.Thread(target=_training_worker, daemon=True)
    training_thread.start()
    
    return {"status": "started"}

@router.post("/stop")
async def stop_training():
    global is_training
    if not is_training:
        return {"status": "not_running"}
        
    stop_event.set()
    # Let the thread terminate on its own flag check
    return {"status": "stopping"}

@router.get("/status", response_model=TrainingStatus)
async def get_status():
    return {
        "is_training": is_training,
        "logs": training_logs
    }
