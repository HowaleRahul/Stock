from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Dict, Any
import json
import os

router = APIRouter(prefix="/api/v1/strategy", tags=["Strategy Builder"])

STRATEGY_FILE = "custom_strategies.json"

class StrategyCondition(BaseModel):
    indicator: str
    operator: str
    value: str # Can be a number or another indicator

class CustomStrategy(BaseModel):
    name: str
    description: str
    bullish_conditions: List[StrategyCondition]
    bearish_conditions: List[StrategyCondition]

@router.get("/list")
async def list_strategies():
    if not os.path.exists(STRATEGY_FILE):
        return {"strategies": []}
    with open(STRATEGY_FILE, "r") as f:
        return {"strategies": json.load(f)}

@router.post("/create")
async def create_strategy(strategy: CustomStrategy):
    strategies = []
    if os.path.exists(STRATEGY_FILE):
        with open(STRATEGY_FILE, "r") as f:
            strategies = json.load(f)
            
    strategies.append(strategy.dict())
    
    with open(STRATEGY_FILE, "w") as f:
        json.dump(strategies, f, indent=4)
        
    return {"status": "success", "strategy": strategy}
