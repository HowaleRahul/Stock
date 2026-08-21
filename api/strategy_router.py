import asyncio
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List
import json
import os

from api.auth import get_api_key, rate_limiter

router = APIRouter(prefix="/api/v1/strategy", tags=["Strategy Builder"])

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
    bullish_conditions: List[StrategyCondition]
    bearish_conditions: List[StrategyCondition]


@router.get("/list")
async def list_strategies():
    async with _file_lock:
        if not os.path.exists(STRATEGY_FILE):
            return {"strategies": []}
        with open(STRATEGY_FILE, "r") as f:
            return {"strategies": json.load(f)}


@router.post("/create")
async def create_strategy(
    strategy: CustomStrategy,
    _api_key: str = Depends(get_api_key),
    _rate_limit: bool = Depends(rate_limiter(10))
):
    async with _file_lock:
        strategies = []
        if os.path.exists(STRATEGY_FILE):
            with open(STRATEGY_FILE, "r") as f:
                strategies = json.load(f)

        if len(strategies) >= MAX_STRATEGIES:
            raise HTTPException(status_code=400, detail=f"Maximum of {MAX_STRATEGIES} strategies reached.")

        # Prevent duplicate names
        if any(s.get("name") == strategy.name for s in strategies):
            raise HTTPException(status_code=409, detail=f"Strategy '{strategy.name}' already exists.")

        strategies.append(strategy.dict())

        with open(STRATEGY_FILE, "w") as f:
            json.dump(strategies, f, indent=4)

    return {"status": "success", "strategy": strategy}
