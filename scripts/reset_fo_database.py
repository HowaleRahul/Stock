"""
Reset database and local paper state cleanly for Indian F&O trading.
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from sqlalchemy import text
from api.db import engine, async_session_factory, Base
from models.models import Symbol, Account, Trade, OHLCVBar, NewsHeadline
from models.init_db import init_database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("reset_fo_db")

async def reset_all():
    logger.info("Connecting to database and dropping existing tables...")
    try:
        async with engine.begin() as conn:
            # Drop tables with cascade if PostgreSQL
            await conn.execute(text("DROP TABLE IF EXISTS trades CASCADE;"))
            await conn.execute(text("DROP TABLE IF EXISTS ohlcv_bars CASCADE;"))
            await conn.execute(text("DROP TABLE IF EXISTS news_headlines CASCADE;"))
            await conn.execute(text("DROP TABLE IF EXISTS symbols CASCADE;"))
            await conn.execute(text("DROP TABLE IF EXISTS accounts CASCADE;"))
            logger.info("Existing tables dropped cleanly.")
    except Exception as e:
        logger.warning(f"Error while dropping tables (may not exist yet): {e}")

    logger.info("Initializing database schemas and seeding F&O indices...")
    init_res = await init_database(seed_watchlist=True)
    logger.info(f"Database initialized: {init_res}")

    # Reset local paper account & trade files
    base_dir = Path(__file__).resolve().parent.parent
    paper_acc_path = base_dir / "paper_account.json"
    paper_trades_path = base_dir / "paper_trades.json"
    trade_journal_path = base_dir / "trade_journal.jsonl"

    paper_acc_path.write_text(json.dumps({
        "account_id": "ACC_PAPER_DEFAULT",
        "initial_capital": 100000.0,
        "cash_balance": 100000.0,
        "peak_capital": 100000.0,
        "realized_pnl": 0.0,
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": 0.0,
        "updated_at": "2026-10-23T00:00:00"
    }, indent=2), encoding="utf-8")
    logger.info("Reset paper_account.json with ₹1,00,000 initial capital.")

    paper_trades_path.write_text("[]", encoding="utf-8")
    logger.info("Reset paper_trades.json to empty list.")

    trade_journal_path.write_text("", encoding="utf-8")
    logger.info("Reset trade_journal.jsonl to empty.")

    await engine.dispose()
    logger.info("F&O Database & Local Paper State Reset Complete!")

if __name__ == "__main__":
    asyncio.run(reset_all())
