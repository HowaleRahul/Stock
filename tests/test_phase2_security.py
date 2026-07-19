import pytest
import asyncio
import os
from httpx import AsyncClient, ASGITransport
from fastapi import status
from unittest.mock import patch

from api.main import app
from api.auth import _RATE_LIMITS
from api.router import _SYNC_LOCKS, _get_sync_lock
from unittest.mock import patch, AsyncMock

@pytest.fixture(autouse=True)
def mock_db_init():
    """Mock the database initialization to allow tests to run without Docker running."""
    with patch("models.init_db.init_database", new_callable=AsyncMock) as mock_init:
        mock_init.return_value = {"status": "success", "message": "Mocked"}
        yield mock_init

@pytest.mark.asyncio
async def test_api_key_authentication_rejection():
    """Verify that when API_KEY is set in environment, mutating endpoints require it."""
    # Mock environment to require an API key
    with patch.dict(os.environ, {"API_KEY": "super_secret_test_key_123"}):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            
            # 1. Without API Key -> 403 Forbidden
            res = await client.post("/api/v1/init?seed_watchlist=false")
            assert res.status_code == status.HTTP_403_FORBIDDEN
            
            # 2. With Wrong API Key -> 403 Forbidden
            res = await client.post(
                "/api/v1/init?seed_watchlist=false",
                headers={"X-API-Key": "wrong_key"}
            )
            assert res.status_code == status.HTTP_403_FORBIDDEN
            
            # 3. With Correct API Key -> Should pass auth (might return 200 or 403 if production check fails, but not auth error)
            res = await client.post(
                "/api/v1/init?seed_watchlist=false",
                headers={"X-API-Key": "super_secret_test_key_123"}
            )
            # Either 200 (dev) or 403 (prod disabled), but NOT the generic API Key Forbidden
            assert res.json().get("detail") != "Invalid or missing API Key"


@pytest.mark.asyncio
async def test_rate_limiter_triggered_429():
    """Verify that hitting the rate limit returns a 429 Too Many Requests response."""
    # Clear rate limits for clean test state
    _RATE_LIMITS.clear()
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Search endpoint has a limit of 100 per minute
        # We will hit init endpoint which has a limit of 10 per minute to speed up test
        success_count = 0
        blocked = False
        
        for _ in range(15):
            res = await client.post("/api/v1/init?seed_watchlist=false")
            if res.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                blocked = True
                break
            success_count += 1
            
        assert blocked is True
        assert success_count == 10  # First 10 should pass, 11th should block


@pytest.mark.asyncio
async def test_sync_locks_memory_leak_cleanup():
    """Verify that _get_sync_lock automatically garbage collects locks when ref_count == 0"""
    test_key = "MEMORY_LEAK_TEST:1d"
    
    assert test_key not in _SYNC_LOCKS
    
    async with _get_sync_lock(test_key):
        # Inside the context, the lock must exist in the dictionary and ref_count == 1
        assert test_key in _SYNC_LOCKS
        assert _SYNC_LOCKS[test_key].ref_count == 1
        
    # Once completely exited, the lock should be garbage collected out of the dict!
    assert test_key not in _SYNC_LOCKS
    
    # Second independent access should recreate and then garbage collect again
    async with _get_sync_lock(test_key):
        assert _SYNC_LOCKS[test_key].ref_count == 1
        
    assert test_key not in _SYNC_LOCKS
