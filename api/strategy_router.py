import asyncio
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List
import json
import os
import tempfile

from api.auth import get_api_key, rate_limiter

router = APIRouter(
    prefix="/api/v1/strategy",
    tags=["Strategy Builder"],
    dependencies=[Depends(get_api_key)],
)

STRATEGY_FILE = "custom_strategies.json"
MAX_STRATEGIES = 50
_file_lock = asyncio.Lock()


class StrategyCondition(BaseModel):
    indicator: str = Field(..., max_length=64)
    operator: str = Field(..., max_length=16)
    value: str = Field(..., max_length=64)


class CustomStrategy(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field("", max_length=512)
    bullish_conditions: List[StrategyCondition] = Field(default_factory=list, max_length=50)
    bearish_conditions: List[StrategyCondition] = Field(default_factory=list, max_length=50)

    def model_post_init(self, __context) -> None:
        self.name = self.name.strip()
        self.description = self.description.strip()
        if not self.name:
            raise ValueError("Strategy name cannot be blank.")


@router.get("/list")
async def list_strategies():
    async with _file_lock:
        if not os.path.exists(STRATEGY_FILE):
            return {"strategies": []}
        try:
            with open(STRATEGY_FILE, "r", encoding="utf-8") as f:
                strategies = json.load(f)
            if not isinstance(strategies, list):
                raise ValueError("strategy store is not a list")
            return {"strategies": strategies}
        except (OSError, ValueError, json.JSONDecodeError):
            logger = __import__("logging").getLogger("trading.api.strategy")
            logger.exception("Strategy store is unreadable")
            raise HTTPException(status_code=503, detail="Strategy store is unavailable.")


@router.post("/create")
async def create_strategy(
    strategy: CustomStrategy,
    _api_key: str = Depends(get_api_key),
    _rate_limit: bool = Depends(rate_limiter(10))
):
    async with _file_lock:
        strategies = []
        if os.path.exists(STRATEGY_FILE):
            try:
                with open(STRATEGY_FILE, "r", encoding="utf-8") as f:
                    strategies = json.load(f)
                if not isinstance(strategies, list):
                    raise ValueError("strategy store is not a list")
            except (OSError, ValueError, json.JSONDecodeError):
                raise HTTPException(status_code=503, detail="Strategy store is unavailable.")

        if len(strategies) >= MAX_STRATEGIES:
            raise HTTPException(status_code=400, detail=f"Maximum of {MAX_STRATEGIES} strategies reached.")

        # Prevent duplicate names
        if any(str(s.get("name", "")).casefold() == strategy.name.casefold() for s in strategies):
            raise HTTPException(status_code=409, detail=f"Strategy '{strategy.name}' already exists.")

        strategies.append(strategy.model_dump())

        # Replace atomically: a restart or full disk must not leave invalid JSON.
        directory = os.path.dirname(os.path.abspath(STRATEGY_FILE))
        fd, temp_path = tempfile.mkstemp(dir=directory, prefix=".strategies-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(strategies, f, indent=4)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, STRATEGY_FILE)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    return {"status": "success", "strategy": strategy}
