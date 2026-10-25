"""
Swing Toolkit & Momentum Masters API Router.

Provides endpoints for:
- Running the 3 Scanners (Momentum, DWIB Inside Bar, ATH Contraction)
- Evaluating the 8-Factor Quality Filter Checklist
- Managing the Active Swing Watchlist (add, delete, list)
- Real-time 15m Opening Range Breakout (ORB) and 5m/15m Volume Gate checks
"""

from __future__ import annotations

import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel, Field

from api.auth import get_api_key, rate_limiter
from setups.swing_toolkit.toolkit import SwingToolkitManager
from setups.swing_toolkit.universe import DEFAULT_SWING_UNIVERSE, STOCK_SECTORS

logger = logging.getLogger("trading.api.swing_router")

router = APIRouter(
    prefix="/api/v1/swing",
    tags=["Swing Toolkit & Momentum Scanners"],
    dependencies=[Depends(get_api_key)],
)

_toolkit_mgr = SwingToolkitManager()


import re
from pydantic import BaseModel, Field, field_validator


def _validate_swing_ticker(ticker: str) -> str:
    if not ticker or not isinstance(ticker, str):
        raise ValueError("Ticker symbol cannot be empty.")
    if "\x00" in ticker:
        raise ValueError("Null byte injection detected in ticker.")
    clean = ticker.strip().upper()
    if not clean or len(clean) > 32 or ".." in clean or "/" in clean or "\\" in clean:
        raise ValueError("Invalid ticker symbol: forbidden characters or length.")
    if not re.match(r"^[A-Z0-9\._\-\^\=]+$", clean):
        raise ValueError("Invalid characters in ticker symbol.")
    return clean


def _sanitize_swing_ticker(ticker: str) -> str:
    try:
        return _validate_swing_ticker(ticker)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))


class AddWatchlistRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=32)
    sector: Optional[str] = Field(default=None, max_length=64)
    source_scanners: List[str] = Field(default_factory=list, max_length=20)
    composite_score: float = Field(0.0, ge=0.0, le=100.0, allow_inf_nan=False)
    vcp_detected: bool = False
    stage_2: bool = False
    notes: Optional[str] = Field(default="", max_length=1024)

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, v: str) -> str:
        return _validate_swing_ticker(v)


class ChecklistEvaluateRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=32)

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, v: str) -> str:
        return _validate_swing_ticker(v)


@router.get("/universe", summary="Get curated liquid Indian swing trading universe")
async def get_universe(
    _rate_limit: bool = Depends(rate_limiter(60)),
):
    """Returns the default curated list of liquid momentum stocks and sector tags."""
    return {
        "count": len(DEFAULT_SWING_UNIVERSE),
        "universe": [
            {"ticker": sym, "sector": STOCK_SECTORS.get(sym, "General")}
            for sym in DEFAULT_SWING_UNIVERSE
        ],
    }


@router.get("/scanners/run", summary="Run the 3 Momentum Masters scanners & filter checklist")
async def run_scanners(
    universe_size: int = Query(25, ge=5, le=50, description="Number of symbols from universe to scan"),
    custom_tickers: Optional[str] = Query(None, max_length=512, description="Comma-separated custom tickers (e.g. HAL,TRENT,BEL)"),
    _rate_limit: bool = Depends(rate_limiter(15)),
):
    """
    Executes the Weekly Routine:
    1. Scans candidates with Momentum, DWIB Inside Bar, and ATH Contraction screeners.
    2. Runs every hit through the 8-Factor Quality Checklist.
    3. Ranks candidates by score and watchlist qualification.
    """
    if custom_tickers:
        raw_list = [t.strip().upper() for t in custom_tickers.split(",") if t.strip()]
        tickers = [_sanitize_swing_ticker(t) for t in raw_list[:50]]
    else:
        tickers = DEFAULT_SWING_UNIVERSE[:universe_size]

    results = await _toolkit_mgr.run_scanners_and_filter(universe=tickers)
    return results


@router.get("/watchlist", summary="Get the active swing watchlist")
async def get_watchlist(
    _rate_limit: bool = Depends(rate_limiter(60)),
):
    """Returns all currently approved candidates on the winning watchlist."""
    items = _toolkit_mgr.load_watchlist()
    return {
        "count": len(items),
        "watchlist": items,
    }


@router.post("/watchlist", summary="Add or update a candidate on the swing watchlist")
async def add_to_watchlist(
    payload: AddWatchlistRequest,
    _rate_limit: bool = Depends(rate_limiter(60)),
):
    """Adds a validated candidate to the active watchlist."""
    import datetime
    ticker = payload.ticker  # Already sanitized via field_validator
    sector = payload.sector or STOCK_SECTORS.get(ticker, "General")

    candidate_record = {
        "ticker": ticker,
        "sector": sector,
        "source_scanners": payload.source_scanners,
        "composite_score": payload.composite_score,
        "vcp_detected": payload.vcp_detected,
        "stage_2": payload.stage_2,
        "added_at": datetime.date.today().isoformat(),
        "notes": payload.notes or "Added from Swing Toolkit.",
    }

    updated = _toolkit_mgr.add_to_watchlist(candidate_record)
    return {
        "success": True,
        "message": f"Added {ticker} to swing watchlist.",
        "watchlist": updated,
    }


@router.delete("/watchlist/{ticker}", summary="Remove a candidate from the swing watchlist")
async def remove_from_watchlist(
    ticker: str,
    _rate_limit: bool = Depends(rate_limiter(60)),
):
    """Removes a symbol from the active swing watchlist."""
    clean_ticker = _sanitize_swing_ticker(ticker)
    updated = _toolkit_mgr.remove_from_watchlist(clean_ticker)
    return {
        "success": True,
        "message": f"Removed {clean_ticker} from swing watchlist.",
        "watchlist": updated,
    }


@router.get("/orb-check/{ticker}", summary="Check 15m ORB breakout trigger and 5m/15m volume gates")
async def check_orb_breakout(
    ticker: str,
    capital: float = Query(1000000.0, ge=10000.0, le=1_000_000_000.0, allow_inf_nan=False, description="Account capital in INR"),
    risk_pct: float = Query(0.015, ge=0.001, le=0.05, allow_inf_nan=False, description="Risk per trade percentage (e.g. 0.015 for 1.5%)"),
    _rate_limit: bool = Depends(rate_limiter(60)),
):
    """
    Evaluates real-time / intraday Opening Range Breakout (ORB) entry conditions:
    - 5m Volume Gate: Cumulative volume >= 7-10% of 20d ADV.
    - 15m Volume Gate: Cumulative volume >= 17-20% of 20d ADV.
    - 15m ORB Breakout: Price crossing above high of first 15 mins.
    - Stop loss, target 2R/3R, and position sizing.
    """
    clean_ticker = _sanitize_swing_ticker(ticker)
    orb_plan = await _toolkit_mgr.evaluate_orb_breakout(
        clean_ticker, capital=capital, risk_per_trade_pct=risk_pct
    )
    return orb_plan
