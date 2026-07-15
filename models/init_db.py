import asyncio
import logging
from sqlalchemy import text, select
from api.db import engine, Base, async_session_factory
from models.models import Symbol, OHLCVBar, NewsHeadline

logger = logging.getLogger("trading.init_db")

DEFAULT_WATCHLIST = [
    # Indian Markets (NSE)
    {"ticker": "RELIANCE.NS", "name": "Reliance Industries Limited", "exchange": "NSE", "currency": "INR"},
    {"ticker": "TCS.NS", "name": "Tata Consultancy Services Limited", "exchange": "NSE", "currency": "INR"},
    {"ticker": "INFY.NS", "name": "Infosys Limited", "exchange": "NSE", "currency": "INR"},
    {"ticker": "SBIN.NS", "name": "State Bank of India", "exchange": "NSE", "currency": "INR"},
    {"ticker": "HDFCBANK.NS", "name": "HDFC Bank Limited", "exchange": "NSE", "currency": "INR"},
    # US Markets (Optional expansion)
    {"ticker": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ", "currency": "USD"},
    {"ticker": "NVDA", "name": "NVIDIA Corporation", "exchange": "NASDAQ", "currency": "USD"},
    {"ticker": "MSFT", "name": "Microsoft Corporation", "exchange": "NASDAQ", "currency": "USD"},
]

async def init_database(seed_watchlist: bool = True) -> dict:
    """
    Creates tables, converts them into TimescaleDB hypertables partitioned on 'time',
    and seeds default watchlist tickers if requested.
    """
    logger.info("Initializing database schemas and TimescaleDB hypertables...")
    results = {
        "tables_created": True,
        "hypertables_configured": [],
        "seeded_symbols_count": 0
    }

    # Create tables via SQLAlchemy metadata
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Convert tables to TimescaleDB hypertables
    async with async_session_factory() as session:
        try:
            # Create hypertable for ohlcv_bars
            await session.execute(
                text("SELECT create_hypertable('ohlcv_bars', 'time', if_not_exists => TRUE);")
            )
            results["hypertables_configured"].append("ohlcv_bars")
            logger.info("Successfully configured hypertable: ohlcv_bars")
        except Exception as e:
            logger.warning(f"Could not configure hypertable 'ohlcv_bars' (might be standard postgres or already created): {e}")

        try:
            # Create hypertable for news_headlines
            await session.execute(
                text("SELECT create_hypertable('news_headlines', 'time', if_not_exists => TRUE);")
            )
            results["hypertables_configured"].append("news_headlines")
            logger.info("Successfully configured hypertable: news_headlines")
        except Exception as e:
            logger.warning(f"Could not configure hypertable 'news_headlines': {e}")

        try:
            await session.commit()
        except Exception as commit_err:
            await session.rollback()
            logger.debug(f"Hypertable commit notice (or no transaction active): {commit_err}")

        # Seed default watchlist if requested
        if seed_watchlist:
            try:
                from api.config import settings
                from data.cleaner import DataCleaner

                added_count = 0
                # Combine DEFAULT_WATCHLIST with any target symbols configured via environment settings
                seed_items = list(DEFAULT_WATCHLIST)
                existing_seed_tickers = {item["ticker"].upper().strip() for item in seed_items}
                for t in settings.target_symbols:
                    clean_t = t.upper().strip()
                    if clean_t and clean_t not in existing_seed_tickers:
                        seed_items.append({
                            "ticker": clean_t,
                            "name": clean_t,
                            "exchange": "NSE" if ".NS" in clean_t else ("BSE" if ".BO" in clean_t else "NASDAQ"),
                            "currency": "INR" if (".NS" in clean_t or ".BO" in clean_t) else "USD"
                        })
                        existing_seed_tickers.add(clean_t)

                for item in seed_items:
                    clean_ticker = DataCleaner.sanitize_text(item["ticker"].upper().strip(), max_len=64)
                    if not clean_ticker:
                        continue
                    stmt = select(Symbol).where(Symbol.ticker == clean_ticker)
                    res = await session.execute(stmt)
                    existing = res.scalar_one_or_none()
                    if not existing:
                        sym = Symbol(
                            ticker=clean_ticker,
                            name=DataCleaner.sanitize_text(item.get("name", clean_ticker), max_len=256),
                            exchange=DataCleaner.sanitize_text(item.get("exchange", "NSE"), max_len=32) or "NSE",
                            currency=DataCleaner.sanitize_text(item.get("currency", "INR"), max_len=16) or "INR",
                            is_active=True
                        )
                        session.add(sym)
                        added_count += 1
                await session.commit()
                results["seeded_symbols_count"] = added_count
                logger.info(f"Seeded {added_count} new symbols into watchlist.")
            except Exception as e:
                await session.rollback()
                logger.warning(f"Failed to seed watchlist or concurrent initialization detected: {e}")

    return results

async def main():
    logging.basicConfig(level=logging.INFO)
    print("Running database initialization script...")
    try:
        res = await init_database(seed_watchlist=True)
        print("Initialization completed:", res)
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
