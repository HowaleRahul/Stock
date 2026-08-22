import uuid

import pytest
from sqlalchemy import delete, select

from api.db import async_session_factory
from models.models import JournalEvent, Trade, TradeContext
from papertrade.persistence import ensure_schema, load_open_trades, persist_portfolio


@pytest.mark.asyncio
async def test_paper_trade_and_journal_round_trip():
    await ensure_schema()
    trade_id = f"test-{uuid.uuid4()}"
    trade = {
        "id": trade_id,
        "ticker": "TEST.NS",
        "direction": "LONG",
        "entry_price": 100.0,
        "quantity": 2,
        "invested": 200.0,
        "tp": 110.0,
        "sl": 95.0,
        "status": "OPEN",
        "opened_at": "2026-01-02T09:15:00+00:00",
        "setup_signals": [{"name": "TestSetup", "signal": "bullish", "confidence": 0.8}],
    }
    account = {"capital": 100000.0, "peak_capital": 100000.0, "status": "ACTIVE"}
    entry_event = {"event": "ENTRY", "trade_id": trade_id, "timestamp": "2026-01-02T09:15:00+00:00"}

    try:
        await persist_portfolio(account, [trade], [entry_event])

        open_trades = await load_open_trades()
        loaded = next(item for item in open_trades if item["id"] == trade_id)
        assert loaded["setup_signals"][0]["name"] == "TestSetup"

        trade["status"] = "CLOSED_WIN"
        trade["exit_price"] = 110.0
        trade["pnl_pct"] = 0.1
        trade["closed_at"] = "2026-01-02T10:15:00+00:00"
        await persist_portfolio(
            {"capital": 100020.0, "peak_capital": 100020.0, "status": "ACTIVE"},
            [trade],
            [{"event": "EXIT", "trade_id": trade_id, "timestamp": "2026-01-02T10:15:00+00:00"}],
        )

        async with async_session_factory() as session:
            row = (await session.execute(select(Trade).where(Trade.order_id == trade_id))).scalar_one()
            events = (await session.execute(
                select(JournalEvent).where(JournalEvent.trade_id == trade_id)
            )).scalars().all()
            assert row.is_open is False
            assert row.pnl_pct == pytest.approx(10.0)
            assert {event.event for event in events} == {"ENTRY", "EXIT"}
    finally:
        async with async_session_factory() as session:
            await session.execute(delete(JournalEvent).where(JournalEvent.trade_id == trade_id))
            await session.execute(delete(TradeContext).where(TradeContext.order_id == trade_id))
            await session.execute(delete(Trade).where(Trade.order_id == trade_id))
            await session.commit()