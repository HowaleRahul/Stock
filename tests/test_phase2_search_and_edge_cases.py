import pytest
import asyncio
from httpx import AsyncClient, ASGITransport
from api.main import app
from api.db import async_session_factory
from models.models import Symbol, OHLCVBar
import datetime


@pytest.mark.asyncio
async def test_search_endpoint_adversarial_queries():
    """Verify search endpoint handles extreme lengths, special characters, and invalid markets gracefully."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Very long query (500 chars) -> should not timeout or crash
        long_q = "A" * 500
        res = await client.get(f"/api/v1/search?q={long_q}")
        assert res.status_code == 200
        data = res.json()
        assert "suggestions" in data
        assert isinstance(data["suggestions"], list)

        # 2. Special characters only
        res_spec = await client.get("/api/v1/search?q=%25%25%24%24%23%23")
        assert res_spec.status_code == 200
        assert isinstance(res_spec.json()["suggestions"], list)

        # 3. Typo fuzzy matching check (e.g. RELINCE)
        res_typo = await client.get("/api/v1/search?q=RELINCE&market=india")
        assert res_typo.status_code == 200
        suggs = res_typo.json()["suggestions"]
        assert any("RELIANCE" in s["symbol"] for s in suggs), f"Expected RELIANCE in {suggs}"

        # 4. Market filter enforcement
        res_india = await client.get("/api/v1/search?q=TATA&market=india")
        assert res_india.status_code == 200
        for s in res_india.json()["suggestions"]:
            assert s["market"] == "india" or s["symbol"].endswith(".NS") or s["symbol"].endswith(".BO") or s["symbol"] in ["NIFTY", "BANKNIFTY", "SENSEX"]


@pytest.mark.asyncio
async def test_indicators_and_setups_timeframes_and_limits():
    """Verify that indicators and setups endpoints handle all valid timeframes and clamp out-of-bounds limits."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Check 15m, 1h, 1wk, 1mo timeframes on a known seeded symbol (AAPL)
        for tf in ["15m", "1h", "1d", "1wk", "1mo"]:
            res_ind = await client.get(f"/api/v1/indicators/AAPL?timeframe={tf}&limit=100")
            # If data doesn't exist for 15m/1h/1wk yet, it might trigger sync or return what is available
            assert res_ind.status_code in [200, 404]
            if res_ind.status_code == 200:
                body = res_ind.json()
                assert body["timeframe"] == tf
                assert len(body["candles"]) <= 100

        # Out-of-bounds limit check (< 10 should fail validation or clamp)
        res_low_limit = await client.get("/api/v1/indicators/AAPL?limit=1")
        assert res_low_limit.status_code in [422, 400], "Limit < 10 should fail validation schema"


@pytest.mark.asyncio
async def test_concurrent_setups_and_indicators_on_new_symbol():
    """Verify that 4 concurrent requests for a completely new symbol do not deadlock, race, or return 500 errors."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Use a fresh ticker symbol that has not been queried before
        fresh_ticker = "ADANIPORTS.NS"
        
        # Fire 4 concurrent requests across indicators and setups
        tasks = [
            client.get(f"/api/v1/indicators/{fresh_ticker}?timeframe=1d&limit=100"),
            client.get(f"/api/v1/setups/{fresh_ticker}?timeframe=1d&period=200"),
            client.get(f"/api/v1/indicators/{fresh_ticker}?timeframe=1d&limit=50"),
            client.get(f"/api/v1/setups/{fresh_ticker}?timeframe=1d&period=100"),
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            assert not isinstance(r, Exception), f"Task raised exception: {r}"
            assert r.status_code in [200, 404], f"Unexpected status code {r.status_code}: {r.text}"
            if r.status_code == 200:
                data = r.json()
                if "setups" in data:
                    assert len(data["setups"]) == 5
                elif "candles" in data:
                    assert isinstance(data["candles"], list)


@pytest.mark.asyncio
async def test_invalid_timeframe_and_schema_rejection():
    """Verify that malformed or invalid timeframes/periods are strictly rejected by the API layer."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Invalid timeframe to indicators
        res_ind = await client.get("/api/v1/indicators/AAPL?timeframe=invalid_tf")
        assert res_ind.status_code == 400
        assert "Invalid timeframe" in res_ind.text

        # 2. Invalid timeframe to setups
        res_setup = await client.get("/api/v1/setups/AAPL?timeframe=999x")
        assert res_setup.status_code == 400
        assert "Invalid timeframe" in res_setup.text

        # 3. Invalid timeframe to candles
        res_candles = await client.get("/api/v1/candles/AAPL?timeframe=bad_interval")
        assert res_candles.status_code == 400
        assert "Invalid timeframe" in res_candles.text

        # 4. Invalid interval to sync endpoint
        res_sync = await client.post("/api/v1/sync", json={"ticker": "AAPL", "interval": "invalid_int"})
        assert res_sync.status_code == 422

