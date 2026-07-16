import asyncio
import datetime
import logging
import httpx
import urllib.parse
from typing import Any, List, Optional, Dict
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import pandas as pd
import math
import difflib

from api.db import get_db
from models.models import Symbol, OHLCVBar, NewsHeadline
from api.schemas import (
    SymbolResponse, SymbolCreate, CandleResponse, NewsResponse,
    SyncRequest, SyncResponse,
    SetupSignalResponse, SetupEvaluationResponse, IndicatorDataResponse,
)
from data.service import DataIngestionService
from setups.engine import SetupEngine
from setups.indicators import ema, rsi, macd, bollinger_bands, find_support_resistance
from api.config import settings

logger = logging.getLogger("trading.api.router")

router = APIRouter(prefix="/api/v1", tags=["Data Pipeline & Watchlist"])

_SYNC_LOCKS: Dict[str, asyncio.Lock] = {}

def _get_sync_lock(key: str) -> asyncio.Lock:
    if key not in _SYNC_LOCKS:
        _SYNC_LOCKS[key] = asyncio.Lock()
    return _SYNC_LOCKS[key]

# Shared engine instance
_setup_engine = SetupEngine()

# Pre-curated instant dictionary of top stocks for zero-latency autocomplete
_INSTANT_CATALOG = [
    # Indian Stocks (NSE/BSE)
    {"symbol": "RELIANCE.NS", "name": "Reliance Industries Limited", "exchange": "NSE", "market": "india"},
    {"symbol": "TCS.NS", "name": "Tata Consultancy Services Limited", "exchange": "NSE", "market": "india"},
    {"symbol": "HDFCBANK.NS", "name": "HDFC Bank Limited", "exchange": "NSE", "market": "india"},
    {"symbol": "ICICIBANK.NS", "name": "ICICI Bank Limited", "exchange": "NSE", "market": "india"},
    {"symbol": "INFY.NS", "name": "Infosys Limited", "exchange": "NSE", "market": "india"},
    {"symbol": "SBIN.NS", "name": "State Bank of India", "exchange": "NSE", "market": "india"},
    {"symbol": "BHARTIARTL.NS", "name": "Bharti Airtel Limited", "exchange": "NSE", "market": "india"},
    {"symbol": "ITC.NS", "name": "ITC Limited", "exchange": "NSE", "market": "india"},
    {"symbol": "TATAMOTORS.NS", "name": "Tata Motors Limited", "exchange": "NSE", "market": "india"},
    {"symbol": "TATASTEEL.NS", "name": "Tata Steel Limited", "exchange": "NSE", "market": "india"},
    {"symbol": "TATAPOWER.NS", "name": "Tata Power Company Limited", "exchange": "NSE", "market": "india"},
    {"symbol": "TATATECH.NS", "name": "Tata Technologies Limited", "exchange": "NSE", "market": "india"},
    {"symbol": "LTIM.NS", "name": "LTIMindtree Limited", "exchange": "NSE", "market": "india"},
    {"symbol": "WIPRO.NS", "name": "Wipro Limited", "exchange": "NSE", "market": "india"},
    {"symbol": "ADANIENT.NS", "name": "Adani Enterprises Limited", "exchange": "NSE", "market": "india"},
    {"symbol": "ADANIPORTS.NS", "name": "Adani Ports & SEZ Limited", "exchange": "NSE", "market": "india"},
    {"symbol": "SUNPHARMA.NS", "name": "Sun Pharmaceutical Industries", "exchange": "NSE", "market": "india"},
    {"symbol": "MARUTI.NS", "name": "Maruti Suzuki India Limited", "exchange": "NSE", "market": "india"},
    {"symbol": "TITAN.NS", "name": "Titan Company Limited", "exchange": "NSE", "market": "india"},
    {"symbol": "BAJFINANCE.NS", "name": "Bajaj Finance Limited", "exchange": "NSE", "market": "india"},
    {"symbol": "ASIANPAINT.NS", "name": "Asian Paints Limited", "exchange": "NSE", "market": "india"},
    {"symbol": "HINDUNILVR.NS", "name": "Hindustan Unilever Limited", "exchange": "NSE", "market": "india"},
    {"symbol": "KOTAKBANK.NS", "name": "Kotak Mahindra Bank Limited", "exchange": "NSE", "market": "india"},
    {"symbol": "AXISBANK.NS", "name": "Axis Bank Limited", "exchange": "NSE", "market": "india"},
    {"symbol": "LT.NS", "name": "Larsen & Toubro Limited", "exchange": "NSE", "market": "india"},
    {"symbol": "HAL.NS", "name": "Hindustan Aeronautics Limited", "exchange": "NSE", "market": "india"},
    {"symbol": "DLF.NS", "name": "DLF Limited", "exchange": "NSE", "market": "india"},
    {"symbol": "PAYTM.NS", "name": "One 97 Communications (Paytm)", "exchange": "NSE", "market": "india"},
    {"symbol": "NYKAA.NS", "name": "FSN E-Commerce Ventures (Nykaa)", "exchange": "NSE", "market": "india"},
    {"symbol": "POLICYBZR.NS", "name": "PB Fintech (Policybazaar)", "exchange": "NSE", "market": "india"},
    {"symbol": "BANKNIFTY.NS", "name": "Nifty Bank Index", "exchange": "NSE", "market": "india"},
    {"symbol": "NIFTY", "name": "Nifty 50 Index", "exchange": "NSE", "market": "india"},
    {"symbol": "BANKNIFTY", "name": "Nifty Bank Index", "exchange": "NSE", "market": "india"},
    {"symbol": "SENSEX", "name": "BSE Sensex Index", "exchange": "BSE", "market": "india"},
    # Global / US Stocks
    {"symbol": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ", "market": "global"},
    {"symbol": "NVDA", "name": "NVIDIA Corporation", "exchange": "NASDAQ", "market": "global"},
    {"symbol": "MSFT", "name": "Microsoft Corporation", "exchange": "NASDAQ", "market": "global"},
    {"symbol": "GOOGL", "name": "Alphabet Inc.", "exchange": "NASDAQ", "market": "global"},
    {"symbol": "AMZN", "name": "Amazon.com Inc.", "exchange": "NASDAQ", "market": "global"},
    {"symbol": "META", "name": "Meta Platforms Inc.", "exchange": "NASDAQ", "market": "global"},
    {"symbol": "TSLA", "name": "Tesla Inc.", "exchange": "NASDAQ", "market": "global"},
    {"symbol": "BRK-B", "name": "Berkshire Hathaway Inc.", "exchange": "NYSE", "market": "global"},
    {"symbol": "JPM", "name": "JPMorgan Chase & Co.", "exchange": "NYSE", "market": "global"},
    {"symbol": "V", "name": "Visa Inc.", "exchange": "NYSE", "market": "global"},
    {"symbol": "WMT", "name": "Walmart Inc.", "exchange": "NYSE", "market": "global"},
    {"symbol": "MA", "name": "Mastercard Inc.", "exchange": "NYSE", "market": "global"},
    {"symbol": "PG", "name": "Procter & Gamble Co.", "exchange": "NYSE", "market": "global"},
    {"symbol": "HD", "name": "The Home Depot Inc.", "exchange": "NYSE", "market": "global"},
    {"symbol": "CVX", "name": "Chevron Corporation", "exchange": "NYSE", "market": "global"},
    {"symbol": "LLY", "name": "Eli Lilly and Company", "exchange": "NYSE", "market": "global"},
    {"symbol": "AMD", "name": "Advanced Micro Devices Inc.", "exchange": "NASDAQ", "market": "global"},
    {"symbol": "INTC", "name": "Intel Corporation", "exchange": "NASDAQ", "market": "global"},
    {"symbol": "NFLX", "name": "Netflix Inc.", "exchange": "NASDAQ", "market": "global"},
    {"symbol": "ADBE", "name": "Adobe Inc.", "exchange": "NASDAQ", "market": "global"},
    {"symbol": "CRM", "name": "Salesforce Inc.", "exchange": "NYSE", "market": "global"},
    {"symbol": "BTC-USD", "name": "Bitcoin USD", "exchange": "CRYPTO", "market": "global"},
    {"symbol": "ETH-USD", "name": "Ethereum USD", "exchange": "CRYPTO", "market": "global"},
]


def _clean_ticker_param(ticker: str) -> str:
    """Validate and clean ticker path parameter, preventing null byte injection and length overflow."""
    if not ticker or not isinstance(ticker, str):
        raise HTTPException(status_code=400, detail="Ticker symbol cannot be empty.")
    cleaned = ticker.upper().strip().replace("\x00", "")
    if not cleaned or len(cleaned) > 64 or any(c in cleaned for c in ["/", "\\", ";", "'", '"']):
        raise HTTPException(status_code=400, detail="Invalid ticker symbol format or length.")
    return cleaned


def _score_fuzzy_suggestion(q_upper: str, sym: str, name: str) -> float:
    """Calculate an algorithmic similarity and relevance score for search suggestions."""
    score = 0.0
    sym_upper = sym.upper()
    name_upper = name.upper() if name else ""
    sym_clean = sym_upper.split(".")[0]

    # Exact match on symbol prefix gets highest rank boost
    if sym_upper.startswith(q_upper) or sym_clean.startswith(q_upper):
        score += 1.0 + (len(q_upper) / max(len(sym_clean), 1)) * 0.5
    elif q_upper in sym_upper:
        score += 0.85
    elif q_upper in name_upper:
        score += 0.75
    else:
        # Algorithmic Levenshtein SequenceMatcher for typo-tolerance (e.g. RELINCE -> RELIANCE, APPEL -> AAPL)
        ratio_sym = difflib.SequenceMatcher(None, q_upper, sym_clean).ratio()
        ratio_name = difflib.SequenceMatcher(None, q_upper, name_upper[:len(q_upper)+6]).ratio()
        max_fuzzy = max(ratio_sym, ratio_name)
        if max_fuzzy >= 0.60:
            score += max_fuzzy * 0.80

    # Boost popular flagship indicators/stocks slightly when scores tie
    if sym_upper in ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "AAPL", "NVDA", "BTC-USD", "BANKNIFTY", "NIFTY"]:
        score += 0.05

    return score


@router.get("/search", summary="Search stock and index tickers with autocomplete")
async def search_symbols_endpoint(
    q: str = Query(..., min_length=1, description="Search query string"),
    market: str = Query("all", description="Filter market: india, global, or all"),
    db: AsyncSession = Depends(get_db)
):
    """Search for matching stocks using algorithmic fuzzy matching, local DB, instant catalog, and live Yahoo queries."""
    clean_q = q.strip().replace("\x00", "")[:64]
    market_clean = market.lower().strip() if market else "all"
    if market_clean not in {"all", "india", "global"}:
        market_clean = "all"
    if not clean_q:
        return {"query": q, "market": market_clean, "suggestions": []}
    query_upper = clean_q.upper()
    scored_results = []
    seen = set()

    # 1. First check local database symbols
    try:
        stmt = select(Symbol)
        res = await db.execute(stmt)
        for sym in res.scalars().all():
            if sym.ticker in seen:
                continue
            is_india = sym.ticker.endswith(".NS") or sym.ticker.endswith(".BO") or sym.ticker in ["NIFTY", "BANKNIFTY", "SENSEX"]
            sym_market = "india" if is_india else "global"
            if market_clean != "all" and sym_market != market_clean:
                continue
            score = _score_fuzzy_suggestion(query_upper, sym.ticker, sym.name or sym.ticker)
            if score > 0.0:
                seen.add(sym.ticker)
                scored_results.append({
                    "symbol": sym.ticker,
                    "name": sym.name or sym.ticker,
                    "exchange": sym.exchange or ("NSE" if is_india else "US"),
                    "market": sym_market,
                    "score": score
                })
    except Exception as e:
        logger.warning(f"Error querying local DB for search: {e}")

    # 2. Check instant catalog with fuzzy scoring
    for item in _INSTANT_CATALOG:
        if item["symbol"] in seen:
            continue
        if market_clean != "all" and item["market"] != market_clean:
            continue
        score = _score_fuzzy_suggestion(query_upper, item["symbol"], item["name"])
        if score > 0.0:
            seen.add(item["symbol"])
            scored_results.append({**item, "score": score})

    # 3. Query Yahoo Finance search API for live matches if needed
    if len(scored_results) < 12:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                encoded_q = urllib.parse.quote_plus(clean_q)
                url = f"https://query2.finance.yahoo.com/v1/finance/search?q={encoded_q}&quotesCount=12&newsCount=0"
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    for quote in data.get("quotes", []):
                        sym = quote.get("symbol", "").upper()
                        if not sym or sym in seen:
                            continue
                        if "=" in sym and sym not in ["BTC-USD", "ETH-USD"] and not sym.endswith("=F"):
                            continue
                        name = quote.get("shortname") or quote.get("longname") or sym
                        exch = quote.get("exchange", "")
                        is_india = sym.endswith(".NS") or sym.endswith(".BO") or exch in ["NSI", "BSE", "NSE"]
                        quote_market = "india" if is_india else "global"
                        if market_clean != "all" and quote_market != market_clean:
                            continue
                        score = _score_fuzzy_suggestion(query_upper, sym, name)
                        if score > 0.0 or query_upper in sym or query_upper in name.upper():
                            seen.add(sym)
                            scored_results.append({
                                "symbol": sym,
                                "name": name,
                                "exchange": exch or ("NSE" if is_india else "US"),
                                "market": quote_market,
                                "score": max(score, 0.5)
                            })
        except Exception as e:
            logger.debug(f"Live Yahoo search query failed or timed out for '{q}': {e}")

    # 4. Sort results descending by score
    scored_results.sort(key=lambda x: x.get("score", 0.0), reverse=True)

    # Strip score before returning to frontend
    final_suggestions = [{k: v for k, v in item.items() if k != "score"} for item in scored_results[:15]]
    return {"query": q, "market": market_clean, "suggestions": final_suggestions}


@router.get("/symbols", response_model=List[SymbolResponse], summary="List all watchlist symbols")
async def list_symbols(db: AsyncSession = Depends(get_db)):
    """Retrieve all financial instruments currently configured in the database."""
    stmt = (
        select(Symbol)
        .where(Symbol.ticker.notin_(["TEST_IDEMPOTENT.NS", "DOESNOTEXIST999"]))
        .order_by(Symbol.ticker)
    )
    res = await db.execute(stmt)
    symbols = res.scalars().all()
    return symbols


@router.post("/init", status_code=status.HTTP_200_OK, summary="Initialize schema and seed watchlist")
async def init_schema_and_seed(seed_watchlist: bool = Query(True, description="Whether to seed default/target symbols")):
    """
    On-demand initialization of database tables, TimescaleDB hypertables ('ohlcv_bars' & 'news_headlines'),
    and seeding of target focus tickers.
    """
    if getattr(settings, "environment", "development").lower() == "production":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public schema initialization is disabled in production."
        )
    from models.init_db import init_database
    res = await init_database(seed_watchlist=seed_watchlist)
    return {
        "status": "success",
        "message": "Database schema, hypertables, and watchlist initialization completed.",
        "details": res
    }


@router.post("/symbols", response_model=SymbolResponse, status_code=status.HTTP_201_CREATED, summary="Add symbol to watchlist")
async def add_symbol(payload: SymbolCreate, db: AsyncSession = Depends(get_db)):
    """Register a new ticker in the watchlist."""
    ticker_clean = payload.ticker.upper().strip()
    # Check existing
    stmt = select(Symbol).where(Symbol.ticker == ticker_clean)
    res = await db.execute(stmt)
    existing = res.scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail=f"Symbol {ticker_clean} is already registered.")

    custom_info = {
        "name": payload.name,
        "exchange": payload.exchange,
        "currency": payload.currency
    }
    # Remove keys where value is None so yfinance / fallback defaults can trigger cleanly
    custom_info = {k: v for k, v in custom_info.items() if v is not None}
    sym = await DataIngestionService.get_or_create_symbol(ticker_clean, custom_info=custom_info, db=db)
    return sym


@router.post("/sync", response_model=SyncResponse, summary="Trigger data ingestion synchronization")
async def trigger_sync(payload: SyncRequest):
    """
    On-demand execution of data synchronization for OHLCV bars and/or news headlines.
    Supports either single symbol sync (`ticker="RELIANCE.NS"`) or whole watchlist (`sync_watchlist=True`).
    """
    results = []

    if payload.sync_watchlist:
        logger.info("APIRouter: Triggered watchlist sync")
        ohlcv_res = await DataIngestionService.sync_watchlist(
            period=payload.period,
            interval=payload.interval,
            sync_news=payload.sync_news
        )
        results.extend(ohlcv_res)
    elif payload.ticker:
        ticker_clean = payload.ticker.upper().strip()
        logger.info(f"APIRouter: Triggered sync for {ticker_clean}")
        try:
            res = await DataIngestionService.sync_symbol_ohlcv(
                ticker=ticker_clean,
                period=payload.period,
                interval=payload.interval
            )
            results.append(res)
        except Exception as e:
            logger.error(f"Error syncing OHLCV for {ticker_clean} via API: {e}")
            results.append({
                "ticker": ticker_clean,
                "status": f"error: {str(e)}"
            })

        if payload.sync_news:
            try:
                news_res = await DataIngestionService.sync_symbol_news(ticker_clean)
                results.append(news_res)
            except Exception as e:
                logger.error(f"Error syncing News for {ticker_clean} via API: {e}")
                results.append({
                    "ticker": ticker_clean,
                    "status": f"error: {str(e)}"
                })
    else:
        raise HTTPException(
            status_code=400,
            detail="Must provide either 'ticker' or set 'sync_watchlist=True'."
        )

    return SyncResponse(
        message=f"Synchronization completed for {len(results)} tasks.",
        results=results
    )


@router.get("/candles/{ticker}", response_model=List[CandleResponse], summary="Get historical OHLCV candles")
async def get_candles(
    ticker: str,
    timeframe: str = Query("1d", description="Timeframe interval (e.g. 1d, 1h)"),
    limit: int = Query(500, ge=1, le=5000, description="Max bars to return"),
    db: AsyncSession = Depends(get_db)
):
    """Query stored candlestick data from TimescaleDB hypertable."""
    ticker_clean = _clean_ticker_param(ticker)
    timeframe_clean = timeframe.lower().strip() if timeframe else "1d"
    valid_timeframes = {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"}
    if timeframe_clean not in valid_timeframes:
        raise HTTPException(status_code=400, detail=f"Invalid timeframe '{timeframe_clean}'. Must be one of: {', '.join(sorted(valid_timeframes))}.")
    stmt = select(Symbol).where(Symbol.ticker == ticker_clean)
    res = await db.execute(stmt)
    sym = res.scalar_one_or_none()
    if not sym:
        raise HTTPException(status_code=404, detail=f"Symbol {ticker_clean} not found in database.")

    stmt_candles = (
        select(OHLCVBar)
        .where(OHLCVBar.symbol_id == sym.id, OHLCVBar.timeframe == timeframe_clean)
        .order_by(OHLCVBar.time.desc())
        .limit(limit)
    )
    res_candles = await db.execute(stmt_candles)
    bars = res_candles.scalars().all()
    # Return in ascending chronological order for charts/indicators
    return list(reversed(bars))


@router.get("/news/{ticker}", response_model=List[NewsResponse], summary="Get financial news headlines")
async def get_news(
    ticker: str,
    limit: int = Query(50, ge=1, le=500, description="Max news items to return"),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve raw financial news headlines from TimescaleDB hypertable."""
    ticker_clean = _clean_ticker_param(ticker)
    stmt = select(Symbol).where(Symbol.ticker == ticker_clean)
    res = await db.execute(stmt)
    sym = res.scalar_one_or_none()
    if not sym:
        raise HTTPException(status_code=404, detail=f"Symbol {ticker_clean} not found in database.")

    stmt_news = (
        select(NewsHeadline)
        .where(NewsHeadline.symbol_id == sym.id)
        .order_by(NewsHeadline.time.desc())
        .limit(limit)
    )
    res_news = await db.execute(stmt_news)
    news = res_news.scalars().all()
    return news


# ---------------------------------------------------------------------------
# Phase 2 — Setup Evaluation & Indicator Endpoints
# ---------------------------------------------------------------------------

import numpy as np

def _safe_json_float(v: Any) -> Optional[float]:
    """Convert a float/numpy number to JSON-safe value (None if NaN/Inf)."""
    if v is None or pd.isna(v):
        return None
    try:
        val = float(v)
        if math.isnan(val) or math.isinf(val):
            return None
        return val
    except (ValueError, TypeError):
        return None


async def _load_ohlcv_df(
    ticker: str, timeframe: str, limit: int, db: AsyncSession
) -> tuple:
    """Load OHLCV bars from DB into a pandas DataFrame.

    Returns (symbol, df) or raises HTTPException.
    """
    ticker_clean = _clean_ticker_param(ticker)

    stmt = select(Symbol).where(Symbol.ticker == ticker_clean)
    res = await db.execute(stmt)
    sym = res.scalar_one_or_none()

    timeframe_clean = timeframe.lower().strip() if timeframe else "1d"
    valid_timeframes = {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"}
    if timeframe_clean not in valid_timeframes:
        raise HTTPException(status_code=400, detail=f"Invalid timeframe '{timeframe_clean}'. Must be one of: {', '.join(sorted(valid_timeframes))}.")
    bars = []
    if sym:
        stmt_bars = (
            select(OHLCVBar)
            .where(OHLCVBar.symbol_id == sym.id, OHLCVBar.timeframe == timeframe_clean)
            .order_by(OHLCVBar.time.desc())
            .limit(limit)
        )
        res_bars = await db.execute(stmt_bars)
        bars = list(res_bars.scalars().all())

    # Auto-trigger on-demand sync from Yahoo Finance if symbol is missing or has insufficient history
    if not sym or len(bars) < 10:
        lock = _get_sync_lock(f"{ticker_clean}:{timeframe_clean}")
        async with lock:
            # End any stale read transaction on db so we see whatever another concurrent request just committed inside the lock!
            try:
                await db.commit()
            except Exception:
                await db.rollback()

            stmt = select(Symbol).where(Symbol.ticker == ticker_clean)
            res = await db.execute(stmt)
            sym = res.scalar_one_or_none()
            if sym:
                stmt_bars = (
                    select(OHLCVBar)
                    .where(OHLCVBar.symbol_id == sym.id, OHLCVBar.timeframe == timeframe_clean)
                    .order_by(OHLCVBar.time.desc())
                    .limit(limit)
                )
                res_bars = await db.execute(stmt_bars)
                bars = list(res_bars.scalars().all())

            if not sym or len(bars) < 10:
                logger.info(f"On-demand sync triggered for {ticker_clean} (timeframe={timeframe_clean})...")
                try:
                    from data.service import DataIngestionService
                    await DataIngestionService.sync_symbol_ohlcv(ticker_clean, period="5y", interval=timeframe_clean)
                    # End open transaction on db so the re-query sees the newly synced rows cleanly
                    try:
                        await db.commit()
                    except Exception:
                        await db.rollback()

                    # Re-query symbol and bars
                    stmt = select(Symbol).where(Symbol.ticker == ticker_clean)
                    res = await db.execute(stmt)
                    sym = res.scalar_one_or_none()
                    if sym:
                        stmt_bars = (
                            select(OHLCVBar)
                            .where(OHLCVBar.symbol_id == sym.id, OHLCVBar.timeframe == timeframe_clean)
                            .order_by(OHLCVBar.time.desc())
                            .limit(limit)
                        )
                        res_bars = await db.execute(stmt_bars)
                        bars = list(res_bars.scalars().all())
                except Exception as e:
                    logger.warning(f"On-demand sync failed for {ticker_clean}: {e}")

    if not sym:
        raise HTTPException(status_code=404, detail=f"Symbol {ticker_clean} not found.")

    if not bars:
        raise HTTPException(
            status_code=404,
            detail=f"No OHLCV data found for {ticker_clean} (timeframe={timeframe_clean})."
        )

    # Ensure strict ascending chronological order and deduplicate by timestamp
    bars.sort(key=lambda b: b.time)
    unique_bars = []
    seen_times = set()
    for b in bars:
        if b.time not in seen_times:
            seen_times.add(b.time)
            unique_bars.append(b)
    bars = unique_bars

    df = pd.DataFrame(
        [
            {
                "time": b.time,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "adjusted_close": b.adjusted_close,
                "volume": b.volume,
            }
            for b in bars
        ]
    )
    return sym, bars, df


@router.get(
    "/setups/{ticker}",
    response_model=SetupEvaluationResponse,
    summary="Evaluate all technical setups for a symbol",
    tags=["Technical Setups"],
)
async def evaluate_setups(
    ticker: str,
    timeframe: str = Query("1d", description="Candle timeframe"),
    period: int = Query(200, ge=10, le=5000, description="Number of bars to analyze"),
    db: AsyncSession = Depends(get_db),
):
    """Run all 5 technical setups (MA Crossover, RSI, MACD, Bollinger Bands,
    S/R Breakout) against the stored OHLCV data and return signals."""
    sym, bars, df = await _load_ohlcv_df(ticker, timeframe, period, db)

    signals = _setup_engine.evaluate_all(df)

    return SetupEvaluationResponse(
        ticker=sym.ticker,
        timeframe=timeframe.lower().strip(),
        bars_analyzed=len(df),
        evaluated_at=datetime.datetime.now(datetime.timezone.utc),
        setups=[
            SetupSignalResponse(
                name=s.name,
                signal=s.signal,
                confidence=s.confidence,
                reasoning=s.reasoning,
            )
            for s in signals
        ],
    )


@router.get(
    "/indicators/{ticker}",
    response_model=IndicatorDataResponse,
    summary="Get indicator overlay data for charting",
    tags=["Technical Setups"],
)
async def get_indicators(
    ticker: str,
    timeframe: str = Query("1d", description="Candle timeframe"),
    limit: int = Query(500, ge=10, le=5000, description="Max bars to return"),
    db: AsyncSession = Depends(get_db),
):
    """Return OHLCV candles together with pre-computed indicator series
    (EMA, RSI, MACD, Bollinger Bands, S/R levels) for chart overlays."""
    sym, bars, df = await _load_ohlcv_df(ticker, timeframe, limit, db)

    close = df["close"]
    high = df["high"]
    low = df["low"]

    # Compute all indicators
    ema_20 = ema(close, 20)
    ema_50 = ema(close, 50)
    rsi_14 = rsi(close, 14)
    macd_line, macd_signal_line, macd_hist = macd(close, 12, 26, 9)
    bb_upper, bb_middle, bb_lower = bollinger_bands(close, 20, 2.0)
    sr_levels = find_support_resistance(close, high, low)

    # Convert to JSON-safe lists
    def to_list(s: pd.Series) -> list:
        return [_safe_json_float(v) for v in s.values]

    return IndicatorDataResponse(
        ticker=sym.ticker,
        timeframe=timeframe.lower().strip(),
        candles=[CandleResponse.model_validate(b) for b in bars],
        ema_20=to_list(ema_20),
        ema_50=to_list(ema_50),
        rsi_14=to_list(rsi_14),
        macd_line=to_list(macd_line),
        macd_signal=to_list(macd_signal_line),
        macd_histogram=to_list(macd_hist),
        bb_upper=to_list(bb_upper),
        bb_middle=to_list(bb_middle),
        bb_lower=to_list(bb_lower),
        support_levels=[_safe_json_float(v) for v in sr_levels["support"] if _safe_json_float(v) is not None],
        resistance_levels=[_safe_json_float(v) for v in sr_levels["resistance"] if _safe_json_float(v) is not None],
    )
