import asyncio
import json
import os
import sys
from datetime import datetime

# Add the parent directory to sys.path so we can import from models and api
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from api.db import async_session_factory
from models.models import Account, Trade
from models.init_db import init_database

async def migrate():
    # Ensure tables exist
    await init_database()

    async with async_session_factory() as session:
        # Load account
        if os.path.exists("paper_account.json"):
            with open("paper_account.json", "r") as f:
                acc_data = json.load(f)
            
            stmt = select(Account)
            res = await session.execute(stmt)
            account = res.scalar_one_or_none()
            
            if not account:
                account = Account(
                    capital=acc_data.get("capital", 100000.0),
                    peak_capital=acc_data.get("peak_capital", 100000.0),
                    status=acc_data.get("status", "ACTIVE")
                )
                session.add(account)
            else:
                account.capital = acc_data.get("capital", account.capital)
                account.peak_capital = acc_data.get("peak_capital", account.peak_capital)
                account.status = acc_data.get("status", account.status)
        
        # Load trades
        if os.path.exists("paper_trades.json"):
            with open("paper_trades.json", "r") as f:
                trades = json.load(f)
                
            for t in trades:
                # Check if it already exists
                stmt = select(Trade).where(Trade.order_id == t["order_id"])
                res = await session.execute(stmt)
                existing = res.scalar_one_or_none()
                
                if not existing:
                    new_trade = Trade(
                        order_id=t.get("order_id", t.get("id")),
                        ticker=t["ticker"],
                        direction=t["direction"],
                        entry_price=t["entry_price"],
                        quantity=t["quantity"],
                        invested=t["invested"],
                        take_profit=t["take_profit"],
                        stop_loss=t["stop_loss"],
                        is_open=True, # In JSON, only open trades are stored
                    )
                    session.add(new_trade)
                    
        await session.commit()
        print("Migration complete!")

if __name__ == "__main__":
    asyncio.run(migrate())
