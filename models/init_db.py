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

        # Seed default watchlist if requested
        if seed_watchlist:
            added_count = 0
            for item in DEFAULT_WATCHLIST:
                stmt = select(Symbol).where(Symbol.ticker == item["ticker"])
                res = await session.execute(stmt)
                existing = res.scalar_one_or_none()
                if not existing:
                    sym = Symbol(
                        ticker=item["ticker"],
                        name=item["name"],
                        exchange=item["exchange"],
                        currency=item["currency"],
                        is_active=True
                    )
                    session.add(sym)
                    added_count += 1
            await session.commit()
            results["seeded_symbols_count"] = added_count
            logger.info(f"Seeded {added_count} new symbols into watchlist.")

    return results

async def main():
    logging.basicConfig(level=logging.INFO)
    print("Running database initialization script...")
    res = await init_database(seed_watchlist=True)
    print("Initialization completed:", res)

if __name__ == "__main__":
    asyncio.run(main())
