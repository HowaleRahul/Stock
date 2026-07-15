import datetime
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, func

from api.main import app
from api.db import async_session_factory
from models.models import Symbol, OHLCVBar, NewsHeadline
from data.cleaner import DataCleaner
from data.service import DataIngestionService


def test_data_cleaner_sanity_and_splits():
    """Verify DataCleaner drops corrupted prices, fixes OHLC envelopes, and detects stock splits."""
    now = datetime.datetime(2026, 7, 1, 15, 30, tzinfo=datetime.timezone.utc)
    mock_bars = [
        # Normal bar
        {"time": now - datetime.timedelta(days=3), "timeframe": "1d", "open": 100.0, "high": 105.0, "low": 98.0, "close": 102.0, "adjusted_close": 102.0, "volume": 1000.0, "split_ratio": 1.0, "dividend": 0.0},
        # Corrupted non-positive close -> must be dropped
        {"time": now - datetime.timedelta(days=2), "timeframe": "1d", "open": 102.0, "high": 104.0, "low": 99.0, "close": 0.0, "adjusted_close": 0.0, "volume": 500.0, "split_ratio": 1.0, "dividend": 0.0},
        # Inverted envelope (high < low) -> must be corrected
        {"time": now - datetime.timedelta(days=1), "timeframe": "1d", "open": 102.0, "high": 95.0, "low": 106.0, "close": 101.0, "adjusted_close": 101.0, "volume": 1200.0, "split_ratio": 1.0, "dividend": 0.0},
        # Stock split 2:1 -> must verify without error
        {"time": now, "timeframe": "1d", "open": 51.0, "high": 53.0, "low": 50.0, "close": 52.0, "adjusted_close": 52.0, "volume": 3000.0, "split_ratio": 2.0, "dividend": 0.0},
    ]

    cleaned = DataCleaner.clean_and_verify(mock_bars, timeframe="1d")
    
    # Verify corrupted bar dropped (4 -> 3 bars)
    assert len(cleaned) == 3
    # Verify chronological sort and envelope fix on inverted bar
    assert cleaned[1]["high"] == 106.0
    assert cleaned[1]["low"] == 95.0
    # Verify split bar retained
    assert cleaned[2]["split_ratio"] == 2.0


@pytest.mark.asyncio
async def test_idempotent_bulk_upsert():
    """Verify that re-inserting the same candlestick records executes ON CONFLICT DO UPDATE without duplication."""
    ticker = "TEST_IDEMPOTENT.NS"
    sym = await DataIngestionService.get_or_create_symbol(ticker)

    now = datetime.datetime(2026, 1, 15, 9, 15, tzinfo=datetime.timezone.utc)
    mock_bar = {
        "time": now,
        "timeframe": "1d",
        "open": 200.0,
        "high": 210.0,
        "low": 195.0,
        "close": 205.0,
        "adjusted_close": 205.0,
        "volume": 50000.0,
        "split_ratio": 1.0,
        "dividend": 0.0
    }

    # First insert via DataCleaner & session upsert logic directly or via mocked fetcher
    # Let's insert directly via DataIngestionService helper using a mock list
    cleaned = DataCleaner.clean_and_verify([mock_bar])
    from sqlalchemy.dialects.postgresql import insert
    
    async with async_session_factory() as session:
        stmt = insert(OHLCVBar).values([
            {
                "time": b["time"],
                "symbol_id": sym.id,
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
            for b in cleaned
        ])
        upsert_stmt = stmt.on_conflict_do_update(
            index_elements=["symbol_id", "time", "timeframe"],
            set_={"close": stmt.excluded.close, "volume": stmt.excluded.volume}
        )
        await session.execute(upsert_stmt)
        await session.commit()

        # Check row count for sym.id
        c1 = (await session.execute(select(func.count()).select_from(OHLCVBar).where(OHLCVBar.symbol_id == sym.id))).scalar()
        assert c1 == 1

        # Run upsert again with modified volume
        mock_bar["volume"] = 75000.0
        cleaned2 = DataCleaner.clean_and_verify([mock_bar])
        stmt2 = insert(OHLCVBar).values([
            {
                "time": b["time"],
                "symbol_id": sym.id,
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
            for b in cleaned2
        ])
        upsert_stmt2 = stmt2.on_conflict_do_update(
            index_elements=["symbol_id", "time", "timeframe"],
            set_={"close": stmt2.excluded.close, "volume": stmt2.excluded.volume}
        )
        await session.execute(upsert_stmt2)
        await session.commit()

        c2 = (await session.execute(select(func.count()).select_from(OHLCVBar).where(OHLCVBar.symbol_id == sym.id))).scalar()
        assert c2 == 1  # No duplicate rows!

        # Verify updated volume
        bar_db = (await session.execute(select(OHLCVBar).where(OHLCVBar.symbol_id == sym.id, OHLCVBar.time == now))).scalar_one()
        assert bar_db.volume == 75000.0


@pytest.mark.asyncio
async def test_api_symbols_and_candles_endpoints():
    """Test REST API endpoints for listing symbols and retrieving synced candles and news."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Get Symbols
        res_sym = await client.get("/api/v1/symbols")
        assert res_sym.status_code == 200
        symbols = res_sym.json()
        assert isinstance(symbols, list)
        assert any(s["ticker"] == "RELIANCE.NS" for s in symbols)

        # 2. Get Candles for RELIANCE.NS (which was synced in CLI verification)
        res_can = await client.get("/api/v1/candles/RELIANCE.NS?timeframe=1d&limit=100")
        assert res_can.status_code == 200
        candles = res_can.json()
        assert isinstance(candles, list)
        if candles:
            assert "time" in candles[0]
            assert "close" in candles[0]
            assert "split_ratio" in candles[0]

        # 3. Get News for RELIANCE.NS
        res_news = await client.get("/api/v1/news/RELIANCE.NS?limit=20")
        assert res_news.status_code == 200
        news = res_news.json()
        assert isinstance(news, list)


@pytest.mark.asyncio
async def test_api_trigger_sync_endpoint():
    """Verify POST /api/v1/sync endpoint handles both single symbol and watchlist sync triggers without error."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Test single ticker sync
        payload = {
            "ticker": "RELIANCE.NS",
            "period": "5d",
            "interval": "1d",
            "sync_news": True
        }
        res = await client.post("/api/v1/sync", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert "Synchronization completed" in data["message"]
        assert len(data["results"]) >= 1
        assert any(r["ticker"] == "RELIANCE.NS" and r["status"] == "success" for r in data["results"])

        # Test invalid payload (no ticker and sync_watchlist=False)
        res_bad = await client.post("/api/v1/sync", json={"period": "1mo"})
        assert res_bad.status_code == 400
