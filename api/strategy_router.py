import asyncio
import json
import logging
import os
import re
import tempfile
from typing import List, Set
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from api.auth import get_api_key, rate_limiter

logger = logging.getLogger("trading.api.strategy")

router = APIRouter(
    prefix="/api/v1/strategy",
    tags=["Strategy Builder"],
    dependencies=[Depends(get_api_key)],
)

import threading

# Pin strategy file strictly to project directory
STRATEGY_FILE = os.path.abspath("custom_strategies.json")
MAX_STRATEGIES = 50
_file_lock = asyncio.Lock()
_thread_lock = threading.RLock()

VALID_OPERATORS: Set[str] = {
    ">", "<", ">=", "<=", "==", "!=",
    "crosses_above", "crosses_below", "crosses"
}


class StrategyCondition(BaseModel):
    indicator: str = Field(..., min_length=1, max_length=64)
    operator: str = Field(..., min_length=1, max_length=16)
    value: str = Field(..., min_length=1, max_length=64)

    @field_validator("indicator")
    @classmethod
    def validate_indicator(cls, v: str) -> str:
        clean = v.strip().replace("\x00", "")
        if clean.lower() in ("nan", "inf", "infinity", "-inf", "-infinity", "null", "none"):
            raise ValueError(f"Indicator identifier cannot be reserved keyword '{clean}'.")
        if not re.match(r"^[A-Za-z0-9_]{1,64}$", clean):
            raise ValueError(f"Invalid indicator identifier '{clean}'. Must be alphanumeric with underscores.")
        return clean

    @field_validator("operator")
    @classmethod
    def validate_operator(cls, v: str) -> str:
        clean = v.strip()
        lower_clean = clean.lower()
        if lower_clean in VALID_OPERATORS:
            return lower_clean
        if clean in VALID_OPERATORS:
            return clean
        raise ValueError(f"Invalid condition operator '{v}'. Allowed: {', '.join(sorted(VALID_OPERATORS))}")

    @field_validator("value")
    @classmethod
    def validate_value(cls, v: str) -> str:
        clean = v.strip().replace("\x00", "")
        if clean.lower() in ("nan", "inf", "infinity", "-inf", "-infinity", "null", "none"):
            raise ValueError(f"Condition value cannot be reserved keyword '{clean}'.")
        # Either numeric (integer/float) or a valid indicator identifier
        if not (re.match(r"^-?\d+(\.\d+)?$", clean) or re.match(r"^[A-Za-z0-9_]{1,64}$", clean)):
            raise ValueError(f"Invalid condition value '{clean}'. Must be numeric or a valid indicator identifier.")
        return clean


class CustomStrategy(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field("", max_length=512)
    bullish_conditions: List[StrategyCondition] = Field(default_factory=list, max_length=50)
    bearish_conditions: List[StrategyCondition] = Field(default_factory=list, max_length=50)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        clean = v.strip().replace("\x00", "")
        if not clean:
            raise ValueError("Strategy name cannot be blank.")
        if ".." in clean or "/" in clean or "\\" in clean:
            raise ValueError("Strategy name contains forbidden path traversal characters.")
        if not re.match(r"^[A-Za-z0-9_\-\s]{1,128}$", clean):
            raise ValueError("Strategy name contains invalid characters. Only alphanumeric, spaces, dashes, and underscores allowed.")
        return clean

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        clean = v.strip().replace("\x00", "")
        return clean[:512]


def _atomic_write_strategies(strategies: list) -> None:
    directory = os.path.dirname(os.path.abspath(STRATEGY_FILE))
    fd, temp_path = tempfile.mkstemp(dir=directory, prefix=".strategies-", suffix=".json")
    with _thread_lock:
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(strategies, f, indent=4)
                f.flush()
                os.fsync(f.fileno())
            replaced = False
            last_pe = None
            import time
            for attempt in range(5):
                try:
                    os.replace(temp_path, STRATEGY_FILE)
                    replaced = True
                    break
                except PermissionError as pe:
                    last_pe = pe
                    time.sleep(0.02 * (attempt + 1))
            if not replaced and last_pe:
                raise last_pe
        finally:
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass


def _read_strategies() -> list:
    with _thread_lock:
        if not os.path.exists(STRATEGY_FILE):
            return []
        try:
            with open(STRATEGY_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return []
                strategies = json.loads(content)
            if not isinstance(strategies, list):
                logger.warning("Strategy store is not a list; returning empty list.")
                return []
            return strategies
        except json.JSONDecodeError as jde:
            logger.warning("Strategy store is corrupted JSON (%s); returning empty list.", jde)
            return []
        except HTTPException:
            raise
        except OSError as e:
            logger.exception("Strategy store I/O error: %s", e)
            raise HTTPException(status_code=503, detail="Strategy store is unavailable.")


@router.get("/list")
async def list_strategies():
    async with _file_lock:
        with _thread_lock:
            return {"strategies": _read_strategies()}


@router.post("/create")
async def create_strategy(
    strategy: CustomStrategy,
    _api_key: str = Depends(get_api_key),
    _rate_limit: bool = Depends(rate_limiter(10))
):
    async with _file_lock:
        with _thread_lock:
            strategies = _read_strategies()

            if len(strategies) >= MAX_STRATEGIES:
                raise HTTPException(status_code=400, detail=f"Maximum of {MAX_STRATEGIES} strategies reached.")

            # Prevent duplicate names
            if any(str(s.get("name", "")).casefold() == strategy.name.casefold() for s in strategies):
                raise HTTPException(status_code=409, detail=f"Strategy '{strategy.name}' already exists.")

            strategies.append(strategy.model_dump())
            _atomic_write_strategies(strategies)

    return {"status": "success", "strategy": strategy}


@router.delete("/{name}")
async def delete_strategy(
    name: str,
    _api_key: str = Depends(get_api_key),
    _rate_limit: bool = Depends(rate_limiter(10))
):
    """Delete a custom strategy by name."""
    clean_name = name.strip().replace("\x00", "")
    if not clean_name:
        raise HTTPException(status_code=400, detail="Strategy name cannot be empty.")
    if ".." in clean_name or "/" in clean_name or "\\" in clean_name:
        raise HTTPException(status_code=400, detail="Invalid strategy name: path traversal characters detected.")
    if not re.match(r"^[A-Za-z0-9_\-\s]{1,128}$", clean_name):
        raise HTTPException(status_code=400, detail="Invalid strategy name characters.")
    
    async with _file_lock:
        with _thread_lock:
            strategies = _read_strategies()

            new_strategies = [s for s in strategies if str(s.get("name", "")).casefold() != clean_name.casefold()]
            if len(new_strategies) == len(strategies):
                raise HTTPException(status_code=404, detail=f"Strategy '{clean_name}' not found.")

            _atomic_write_strategies(new_strategies)

    return {"status": "success", "message": f"Strategy '{clean_name}' deleted."}

