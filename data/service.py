import asyncio
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from api.db import async_session_factory
from models.models import Symbol, OHLCVBar, NewsHeadline
from data.fetcher import YFinanceFetcher
from data.cleaner import DataCleaner
from data.news_fetcher import NewsFetcher

logger = logging.getLogger("trading.data.service")

class DataIngestionService:
    """
    Orchestrates data fetching, cleaning, and idempotent TimescaleDB bulk upserts for financial instruments.
    """

    @classmethod
    async def get_or_create_symbol(cls, ticker: str) -> Symbol:
        """
        Retrieves a Symbol by ticker or creates a new entry using yfinance metadata.
        """
        async with async_session_factory() as session:
            stmt = select(Symbol).where(Symbol.ticker == ticker)
            res = await session.execute(stmt)
            sym = res.scalar_one_or_none()

            if not sym:
                info = await YFinanceFetcher.fetch_symbol_info(ticker)
                sym = Symbol(
                    ticker=ticker,
                    name=info["name"],
                    exchange=info["exchange"],
                    currency=info["currency"],
                    is_active=True
                )
                session.add(sym)
                await session.commit()
                await session.refresh(sym)
                logger.info(f"Created new symbol record: {sym}")
            return sym

    @classmethod
    async def sync_symbol_ohlcv(
        cls,
        ticker: str,
        period: str = "5y",
        interval: str = "1d",
        start: Optional[str] = None,
        end: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Fetches OHLCV bars for a ticker, cleans/verifies them, and performs idempotent chunked upserts.
        """
        logger.info(f"Starting OHLCV sync for {ticker} (interval={interval})...")
        symbol = await cls.get_or_create_symbol(ticker)

        # 1. Fetch raw data
        raw_bars = await YFinanceFetcher.fetch_ohlcv_bars(
            ticker=ticker,
            period=period,
            interval=interval,
            start=start,
            end=end
        )

        if not raw_bars:
            return {
                "ticker": ticker,
                "symbol_id": symbol.id,
                "bars_synced": 0,
                "status": "no_data"
            }

        # 2. Clean and verify corporate actions
        cleaned_bars = DataCleaner.clean_and_verify(raw_bars, timeframe=interval)

        if not cleaned_bars:
            return {
                "ticker": ticker,
                "symbol_id": symbol.id,
                "bars_synced": 0,
                "status": "all_dropped"
            }

        # 3. Batch upsert into ohlcv_bars hypertable using ON CONFLICT DO UPDATE
        chunk_size = 1000
        total_synced = 0

        async with async_session_factory() as session:
            for i in range(0, len(cleaned_bars), chunk_size):
                chunk = cleaned_bars[i : i + chunk_size]
                records = [
                    {
                        "time": b["time"],
                        "symbol_id": symbol.id,
                        "timeframe": b["timeframe"],
                        "open": b["open"],
                        "high": b["high"],
                        "low": b["low"],
                        "close": b["close"],
                        "adjusted_close": b["adjusted_close"],
                        "volume": b["volume"],
                        "split_ratio": b["split_ratio"],
                        "dividend": b["dividend"]
                    }
                    for b in chunk
                ]

                stmt = insert(OHLCVBar).values(records)
                upsert_stmt = stmt.on_conflict_do_update(
                    index_elements=["symbol_id", "time", "timeframe"],
                    set_={
                        "open": stmt.excluded.open,
                        "high": stmt.excluded.high,
                        "low": stmt.excluded.low,
                        "close": stmt.excluded.close,
                        "adjusted_close": stmt.excluded.adjusted_close,
                        "volume": stmt.excluded.volume,
                        "split_ratio": stmt.excluded.split_ratio,
                        "dividend": stmt.excluded.dividend
                    }
                )

                await session.execute(upsert_stmt)
                total_synced += len(chunk)

            await session.commit()

        logger.info(f"Successfully synced {total_synced} OHLCV bars for {ticker} into hypertable.")
        return {
            "ticker": ticker,
            "symbol_id": symbol.id,
            "bars_synced": total_synced,
            "status": "success"
        }

    @classmethod
    async def sync_symbol_news(cls, ticker: str) -> Dict[str, Any]:
        """
        Fetches financial news headlines for a ticker and upserts them idempotently into news_headlines hypertable.
        """
        logger.info(f"Starting news sync for {ticker}...")
        symbol = await cls.get_or_create_symbol(ticker)

        headlines = await NewsFetcher.fetch_ticker_news(ticker)
        if not headlines:
            return {
                "ticker": ticker,
                "symbol_id": symbol.id,
                "news_synced": 0,
                "status": "no_news"
            }

        async with async_session_factory() as session:
            records = [
                {
                    "time": h["time"],
                    "url": h["url"],
                    "symbol_id": symbol.id,
                    "title": h["title"],
                    "source": h["source"],
                    "summary": h["summary"]
                }
                for h in headlines
            ]

            stmt = insert(NewsHeadline).values(records)
            upsert_stmt = stmt.on_conflict_do_update(
                index_elements=["time", "url"],
                set_={
                    "title": stmt.excluded.title,
                    "source": stmt.excluded.source,
                    "summary": stmt.excluded.summary,
                    "symbol_id": stmt.excluded.symbol_id
                }
            )

            await session.execute(upsert_stmt)
            await session.commit()

        logger.info(f"Successfully synced {len(headlines)} news headlines for {ticker}.")
        return {
            "ticker": ticker,
            "symbol_id": symbol.id,
            "news_synced": len(headlines),
            "status": "success"
        }

    @classmethod
    async def sync_watchlist(cls, period: str = "1mo", interval: str = "1d", sync_news: bool = False) -> List[Dict[str, Any]]:
        """
        Synchronizes OHLCV data (and optionally news) for all active symbols in the database sequentially/with gentle concurrency.
        """
        logger.info(f"Starting sync for all active watchlist symbols (sync_news={sync_news})...")
        async with async_session_factory() as session:
            stmt = select(Symbol).where(Symbol.is_active == True)
            res = await session.execute(stmt)
            symbols = res.scalars().all()

        results = []
        for sym in symbols:
            try:
                res = await cls.sync_symbol_ohlcv(
                    ticker=sym.ticker,
                    period=period,
                    interval=interval
                )
                results.append(res)
                if sync_news:
                    news_res = await cls.sync_symbol_news(ticker=sym.ticker)
                    results.append(news_res)
                # Brief pause to avoid hammering yfinance API
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Error syncing {sym.ticker}: {e}")
                results.append({
                    "ticker": sym.ticker,
                    "symbol_id": sym.id,
                    "bars_synced": 0,
                    "status": f"error: {str(e)}"
                })

        return results
