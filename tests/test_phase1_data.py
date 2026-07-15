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


def test_data_cleaner_edge_cases_and_normalization():
    """Verify DataCleaner correctly sanitizes edge cases, negative volumes/dividends/splits, and date check type robustness."""
    now = datetime.datetime.now(datetime.timezone.utc)
    dirty_bars = [
        {
            "time": now - datetime.timedelta(days=2),
            "timeframe": "1d",
            "open": -10.0,  # Negative open price -> should be dropped
            "high": 100.0,
            "low": 90.0,
            "close": 95.0,
            "volume": 1000.0
        },
        {
            "time": now - datetime.timedelta(days=1),
            "timeframe": "1d",
            "open": 100.0,
            "high": 90.0,  # Corrupted envelope (high < low) -> high should be fixed to 105.0
            "low": 95.0,
            "close": 105.0,
            "volume": -500.0,  # Negative volume -> should be clamped to 0.0
            "split_ratio": -2.0,  # Negative split ratio -> should be sanitized to 1.0
            "dividend": -5.0  # Negative dividend -> should be sanitized to 0.0
        }
    ]

    cleaned = DataCleaner.clean_and_verify(dirty_bars, timeframe="1d")
    assert len(cleaned) == 1
    assert cleaned[0]["open"] == 100.0
    assert cleaned[0]["high"] == 105.0
    assert cleaned[0]["low"] == 90.0
    assert cleaned[0]["volume"] == 0.0
    assert cleaned[0]["split_ratio"] == 1.0
    assert cleaned[0]["dividend"] == 0.0

    # Test date detection robustness with both date and datetime types
    missing = DataCleaner.detect_missing_trading_days(cleaned, timeframe="1d")
    assert isinstance(missing, list)


@pytest.mark.asyncio
async def test_case_normalization_api():
    """Verify API endpoints normalize lowercase/mixed-case ticker symbols consistently."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Add lowercase symbol (might return 201 if fresh, or 400 if already exists in persistent DB)
        res = await client.post("/api/v1/symbols", json={"ticker": "tsla", "name": "Tesla Inc."})
        assert res.status_code in (201, 400)
        if res.status_code == 201:
            data = res.json()
            assert data["ticker"] == "TSLA"

        # Query candles using lowercase
        res_candles = await client.get("/api/v1/candles/tsla")
        assert res_candles.status_code == 200


def test_precision_nan_inf_and_string_dates():
    """Verify DataCleaner rejects NaN/Inf price entries and correctly parses string timestamps for missing day checks."""
    import math
    now = datetime.datetime.now(datetime.timezone.utc)
    corrupted_bars = [
        {
            "time": "2026-07-13", # Monday string date (Valid)
            "timeframe": "1d",
            "open": 100.0,
            "high": 105.0,
            "low": 95.0,
            "close": 102.0,
            "volume": 5000.0
        },
        {
            "time": "2026-07-14", # Tuesday string date (NaN price -> must be rejected)
            "timeframe": "1d",
            "open": float("nan"),
            "high": 100.0,
            "low": 90.0,
            "close": 95.0,
            "volume": 1000.0
        },
        {
            "time": "2026-07-15", # Wednesday string date (Inf price -> must be rejected)
            "timeframe": "1d",
            "open": 100.0,
            "high": float("inf"),
            "low": 90.0,
            "close": 95.0,
            "volume": 1000.0
        },
        {
            "time": "2026-07-16", # Thursday string date (Valid)
            "timeframe": "1d",
            "open": 95.0,
            "high": 100.0,
            "low": 90.0,
            "close": 98.0,
            "volume": 2000.0
        }
    ]

    cleaned = DataCleaner.clean_and_verify(corrupted_bars, timeframe="1d")
    # Monday and Thursday valid -> 2 bars kept
    assert len(cleaned) == 2
    assert cleaned[0]["close"] == 102.0
    assert cleaned[1]["close"] == 98.0

    # Verify missing day detection detects both dropped Tuesday (2026-07-14) and Wednesday (2026-07-15)
    missing = DataCleaner.detect_missing_trading_days(cleaned, timeframe="1d")
    missing_strs = {d.strftime("%Y-%m-%d") for d in missing}
    assert "2026-07-14" in missing_strs
    assert "2026-07-15" in missing_strs


@pytest.mark.asyncio
async def test_batch_upsert_duplicate_conflict_keys_immunity():
    """
    Verifies that if DataCleaner or fetchers emit duplicate timestamps for the exact same candle
    or duplicate URLs for news items, the batch upsert deduplicates them cleanly and avoids
    raising 'ON CONFLICT DO UPDATE command cannot affect row a second time'.
    """
    duplicate_bars = [
        {
            "time": datetime.datetime(2026, 7, 13, 10, 0, tzinfo=datetime.timezone.utc),
            "timeframe": "1d",
            "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0, "volume": 5000.0,
            "split_ratio": 1.0, "dividend": 0.0, "adjusted_close": 102.0
        },
        {
            # Exact same timestamp and timeframe with slightly different close (simulating feed re-broadcast)
            "time": datetime.datetime(2026, 7, 13, 10, 0, tzinfo=datetime.timezone.utc),
            "timeframe": "1d",
            "open": 100.0, "high": 105.0, "low": 95.0, "close": 103.5, "volume": 6000.0,
            "split_ratio": 1.0, "dividend": 0.0, "adjusted_close": 103.5
        }
    ]

    cleaned = DataCleaner.clean_and_verify(duplicate_bars, timeframe="1d")
    assert len(cleaned) == 1
    assert cleaned[0]["close"] == 102.0 # First unique timestamp kept

    # Now verify database upsert with mock fetchers returning duplicate rows inside the same chunk
    from data.service import DataIngestionService
    from unittest.mock import patch

    async def mock_duplicate_ohlcv(ticker, period="1mo", interval="1d", start=None, end=None):
        return duplicate_bars

    async def mock_duplicate_news(ticker):
        return [
            {
                "time": datetime.datetime(2026, 7, 13, 12, 0, tzinfo=datetime.timezone.utc),
                "url": "https://finance.yahoo.com/news/test-duplicate-1234.html",
                "title": "Initial Headline",
                "source": "Yahoo Finance",
                "summary": "First broadcast"
            },
            {
                "time": datetime.datetime(2026, 7, 13, 12, 0, tzinfo=datetime.timezone.utc),
                "url": "https://finance.yahoo.com/news/test-duplicate-1234.html",
                "title": "Updated Headline",
                "source": "Yahoo Finance",
                "summary": "Re-broadcasted headline"
            }
        ]

    with patch("data.fetcher.YFinanceFetcher.fetch_ohlcv_bars", side_effect=mock_duplicate_ohlcv):
        res = await DataIngestionService.sync_symbol_ohlcv("RELIANCE.NS")
        assert res["status"] in ("success", "already_up_to_date")
        assert res["bars_synced"] == 1

    with patch("data.news_fetcher.NewsFetcher.fetch_ticker_news", side_effect=mock_duplicate_news):
        res_news = await DataIngestionService.sync_symbol_news("RELIANCE.NS")
        assert res_news["status"] == "success"
        assert res_news["news_synced"] == 1


@pytest.mark.asyncio
async def test_adversarial_empty_tickers_and_scheme_normalization():
    """
    Senior SDET check verifying boundary rejection of empty/whitespace tickers
    and automatic database URL scheme normalization.
    """
    from api.schemas import SymbolCreate
    from pydantic import ValidationError
    from api.config import Settings
    from data.service import DataIngestionService

    # Verify whitespace/empty tickers rejected by Pydantic validation
    with pytest.raises(ValidationError):
        SymbolCreate(ticker="   ")

    # Verify DataIngestionService rejects empty tickers directly
    with pytest.raises(ValueError, match="Ticker symbol cannot be empty"):
        await DataIngestionService.get_or_create_symbol("   ")

    # Verify Settings normalizes standard postgres:// scheme to postgresql+asyncpg://
    s1 = Settings(DATABASE_URL="postgres://user:pass@localhost:5432/db")
    assert s1.database_url == "postgresql+asyncpg://user:pass@localhost:5432/db"

    s2 = Settings(DATABASE_URL="postgresql://user:pass@localhost:5432/db")
    assert s2.database_url == "postgresql+asyncpg://user:pass@localhost:5432/db"


@pytest.mark.asyncio
async def test_granular_ohlcv_and_news_error_isolation():
    """
    Senior SDET check verifying that if news sync throws an exception or network timeout,
    the OHLCV sync status remains completely unaffected and isolated.
    """
    from data.service import DataIngestionService
    from unittest.mock import patch

    async def mock_news_error(ticker):
        raise RuntimeError("Mocked network timeout fetching news")

    async def mock_ohlcv_success(ticker, period="1mo", interval="1d"):
        return {"ticker": ticker, "status": "success", "bars_synced": 10}

    with patch.object(DataIngestionService, "sync_symbol_ohlcv", side_effect=mock_ohlcv_success):
        with patch.object(DataIngestionService, "sync_symbol_news", side_effect=mock_news_error):
            results = await DataIngestionService.sync_watchlist(period="1mo", interval="1d", sync_news=True)
            assert len(results) >= 2  # At least 1 OHLCV + 1 News entry per symbol
            # Check that successful OHLCV entry exists and error News entry exists independently
            statuses = [r["status"] for r in results]
            assert "success" in statuses
            assert any("Mocked network timeout" in str(s) for s in statuses)

