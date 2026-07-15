import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import get_db
from models.models import Symbol, OHLCVBar, NewsHeadline
from api.schemas import (
    SymbolResponse, SymbolCreate, CandleResponse, NewsResponse,
    SyncRequest, SyncResponse
)
from data.service import DataIngestionService

logger = logging.getLogger("trading.api.router")

router = APIRouter(prefix="/api/v1", tags=["Data Pipeline & Watchlist"])


@router.get("/symbols", response_model=List[SymbolResponse], summary="List all watchlist symbols")
async def list_symbols(db: AsyncSession = Depends(get_db)):
    """Retrieve all financial instruments currently configured in the database."""
    stmt = select(Symbol).order_by(Symbol.ticker)
    res = await db.execute(stmt)
    symbols = res.scalars().all()
    return symbols


@router.post("/init", status_code=status.HTTP_200_OK, summary="Initialize schema and seed watchlist")
async def init_schema_and_seed(seed_watchlist: bool = Query(True, description="Whether to seed default/target symbols")):
    """
    On-demand initialization of database tables, TimescaleDB hypertables ('ohlcv_bars' & 'news_headlines'),
    and seeding of target focus tickers.
    """
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
    ticker_clean = ticker.upper().strip()
    if not ticker_clean:
        raise HTTPException(status_code=400, detail="Ticker symbol cannot be empty.")
    timeframe_clean = timeframe.lower().strip() if timeframe else "1d"
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
    ticker_clean = ticker.upper().strip()
    if not ticker_clean:
        raise HTTPException(status_code=400, detail="Ticker symbol cannot be empty.")
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
