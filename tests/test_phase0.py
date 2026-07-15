import pytest
from httpx import AsyncClient, ASGITransport
from api.main import app
from api.config import settings


@pytest.mark.asyncio
async def test_root_endpoint():
    """Verify root endpoint returns correct Phase 0 identity."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["system"] == "Personal AI-Assisted Trading System"
        assert "Phase" in data["current_phase"]


@pytest.mark.asyncio
async def test_health_endpoint():
    """Verify health check endpoint returns 200 OK and correct target symbols."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "trading-api"
        assert "target_symbols" in data
        assert isinstance(data["target_symbols"], list)
        assert len(data["target_symbols"]) >= 3


@pytest.mark.asyncio
async def test_db_check_endpoint():
    """
    Verify db-check endpoint responds cleanly (whether connected to live Docker Postgres
    or gracefully reporting disconnection without throwing 500 errors).
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/db-check")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] in ("connected", "disconnected", "error")
        assert "latency_ms" in data


def test_mask_db_url_various_formats():
    """Verify _mask_db_url handles passwords, user-only, and passwordless DB connection URLs safely."""
    from api.db import _mask_db_url

    assert _mask_db_url("postgresql+asyncpg://admin:supersecret@localhost:5432/trading") == "postgresql+asyncpg://admin:***@localhost:5432/trading"
    assert _mask_db_url("postgresql+asyncpg://postgres@localhost:5432/trading") == "postgresql+asyncpg://postgres@localhost:5432/trading"
    assert _mask_db_url("postgresql+asyncpg://localhost:5432/trading") == "postgresql+asyncpg://localhost:5432/trading"
    assert _mask_db_url("") == "unknown_db_url"


@pytest.mark.asyncio
async def test_api_lifespan_startup_and_shutdown():
    """Verify lifespan startup initialize database tables and handles both connected and error branches safely."""
    from unittest.mock import patch, AsyncMock, MagicMock
    from api.main import lifespan, app

    mock_engine = MagicMock()
    mock_engine.dispose = AsyncMock()

    # Case 1: DB Connected
    mock_status_connected = {"status": "connected", "latency_ms": 1.5, "timescaledb_version": "2.14"}
    async def mock_init(seed_watchlist=True):
        return {"tables_created": True}

    with patch("api.main.check_database_connection", side_effect=lambda: mock_status_connected):
        with patch("api.main.init_database", side_effect=mock_init) as mock_init_call:
            with patch("api.main.engine", mock_engine):
                async with lifespan(app):
                    assert mock_init_call.call_count == 1
                assert mock_engine.dispose.call_count == 1

    # Case 2: DB Disconnected / Error
    mock_engine.dispose.reset_mock()
    mock_status_error = {"status": "error", "latency_ms": 0.0, "error": "connection refused"}
    with patch("api.main.check_database_connection", side_effect=lambda: mock_status_error):
        with patch("api.main.engine", mock_engine):
            async with lifespan(app):
                pass
            assert mock_engine.dispose.call_count == 1
