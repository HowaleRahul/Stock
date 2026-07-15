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
    async def get_or_create_symbol(cls, ticker: str, custom_info: Optional[Dict[str, Any]] = None, db: Optional[Any] = None) -> Symbol:
        """
        Retrieves a Symbol by ticker or creates a new entry using yfinance metadata / overrides.
        Supports session reuse if `db` (AsyncSession) is provided.
        """
        ticker = ticker.upper().strip()
        if not ticker:
            raise ValueError("Ticker symbol cannot be empty.")
        async def _execute(session):
            stmt = select(Symbol).where(Symbol.ticker == ticker)
            res = await session.execute(stmt)
            sym = res.scalar_one_or_none()

            if not sym:
                info = await YFinanceFetcher.fetch_symbol_info(ticker)
                if custom_info:
                    if custom_info.get("name"):
                        info["name"] = custom_info["name"]
                    if custom_info.get("exchange"):
                        info["exchange"] = custom_info["exchange"]
                    if custom_info.get("currency"):
                        info["currency"] = custom_info["currency"]

                default_ex = "NSE" if ticker.endswith(".NS") else ("BSE" if ticker.endswith(".BO") else "NASDAQ")
                default_cur = "INR" if (ticker.endswith(".NS") or ticker.endswith(".BO")) else "USD"

                sym = Symbol(
                    ticker=DataCleaner.sanitize_text(ticker, 64) or ticker[:64],
                    name=DataCleaner.sanitize_text(info.get("name") or ticker, 256) or ticker[:256],
                    exchange=DataCleaner.sanitize_text(info.get("exchange") or default_ex, 32) or default_ex,
                    currency=DataCleaner.sanitize_text(info.get("currency") or default_cur, 16) or default_cur,
                    is_active=True
                )
                session.add(sym)
                try:
                    await session.commit()
                    await session.refresh(sym)
                    logger.info(f"Created new symbol record: {sym}")
                except Exception as e:
                    await session.rollback()
                    logger.warning(f"Concurrent insert detected or commit failed for {ticker}: {e}")
                    res = await session.execute(select(Symbol).where(Symbol.ticker == ticker))
                    sym = res.scalar_one_or_none()
                    if not sym:
                        raise e
            return sym

        if db is not None:
            return await _execute(db)
        else:
            async with async_session_factory() as session:
                return await _execute(session)

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
        ticker = ticker.upper().strip()
        if not ticker:
            raise ValueError("Ticker symbol cannot be empty.")
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
            try:
                for i in range(0, len(cleaned_bars), chunk_size):
                    chunk = cleaned_bars[i : i + chunk_size]
                    if not chunk:
                        continue
                    records = [
                        {
                            "time": b["time"],
                            "symbol_id": symbol.id,
                            "timeframe": str(b["timeframe"])[:16],
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
                        if "time" in b
                    ]
                    if not records:
                        continue

                    # Deduplicate chunk records by composite unique key before insert
                    records = list({(r["symbol_id"], r["time"], r["timeframe"]): r for r in records}.values())

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
                    total_synced += len(records)

                await session.commit()
            except Exception as e:
                await session.rollback()
                logger.error(f"Database error during OHLCV upsert for {ticker}: {e}")
                raise e

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
        ticker = ticker.upper().strip()
        if not ticker:
            raise ValueError("Ticker symbol cannot be empty.")
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
            try:
                records = []
                for h in headlines:
                    if not (h.get("time") and h.get("url") and h.get("title")):
                        continue
                    clean_url = DataCleaner.sanitize_text(h["url"], 1024)
                    clean_title = DataCleaner.sanitize_text(h["title"], 512)
                    if not clean_url or not clean_title:
                        continue
                    records.append({
                        "time": h["time"],
                        "url": clean_url,
                        "symbol_id": symbol.id,
                        "title": clean_title,
                        "source": DataCleaner.sanitize_text(h.get("source"), 128) or "Unknown",
                        "summary": DataCleaner.sanitize_text(h.get("summary"), 65000)
                    })
                if not records:
                    return {
                        "ticker": ticker,
                        "symbol_id": symbol.id,
                        "news_synced": 0,
                        "status": "no_valid_news"
                    }

                # Deduplicate records by composite unique key (time, url)
                records = list({(r["time"], r["url"]): r for r in records}.values())

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
            except Exception as e:
                await session.rollback()
                logger.error(f"Database error during news upsert for {ticker}: {e}")
                raise e

        logger.info(f"Successfully synced {len(records)} news headlines for {ticker}.")
        return {
            "ticker": ticker,
            "symbol_id": symbol.id,
            "news_synced": len(records),
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

        if not symbols:
            logger.info("No active symbols found in database. Auto-seeding from settings.target_symbols...")
            from api.config import settings
            symbols = []
            for t in settings.target_symbols:
                try:
                    sym = await cls.get_or_create_symbol(t)
                    symbols.append(sym)
                except Exception as seed_err:
                    logger.warning(f"Failed to auto-seed {t} during watchlist sync: {seed_err}")

        results = []
        for sym in symbols:
            try:
                res = await cls.sync_symbol_ohlcv(
                    ticker=sym.ticker,
                    period=period,
                    interval=interval
                )
                results.append(res)
            except Exception as e:
                logger.error(f"Error syncing OHLCV for {sym.ticker}: {e}")
                results.append({
                    "ticker": sym.ticker,
                    "symbol_id": sym.id,
                    "bars_synced": 0,
                    "status": f"error: {str(e)}"
                })

            if sync_news:
                try:
                    news_res = await cls.sync_symbol_news(ticker=sym.ticker)
                    results.append(news_res)
                except Exception as e:
                    logger.error(f"Error syncing News for {sym.ticker}: {e}")
                    results.append({
                        "ticker": sym.ticker,
                        "symbol_id": sym.id,
                        "news_synced": 0,
                        "status": f"error: {str(e)}"
                    })

            # Brief pause to avoid hammering yfinance API
            await asyncio.sleep(0.5)

        return results
