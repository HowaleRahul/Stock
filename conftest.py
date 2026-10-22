import asyncio
import socket
from urllib.parse import urlparse
import pytest
import pytest_asyncio
from api.db import engine
from api.config import settings

def is_database_online(timeout: float = 0.5) -> bool:
    try:
        url = settings.database_url
        if "+asyncpg" in url:
            url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
        parsed = urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 5432
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ConnectionRefusedError):
        return False
    return False

DB_AVAILABLE = is_database_online()

DB_INTEGRATION_TESTS = {
    "tests/test_paper_persistence.py::test_paper_trade_and_journal_round_trip",
    "tests/test_phase1_data.py::test_idempotent_bulk_upsert",
    "tests/test_phase1_data.py::test_api_symbols_and_candles_endpoints",
    "tests/test_phase1_data.py::test_case_normalization_api",
    "tests/test_phase1_data.py::test_batch_upsert_duplicate_conflict_keys_immunity",
    "tests/test_phase1_data.py::test_granular_ohlcv_and_news_error_isolation",
    "tests/test_phase1_data.py::test_candles_and_news_endpoints_404_and_empty_ticker",
    "tests/test_phase1_data.py::test_sync_symbol_ohlcv_no_data_and_all_dropped",
    "tests/test_phase1_data.py::test_sync_symbol_news_filters_missing_fields",
    "tests/test_phase1_data.py::test_add_symbol_duplicate_returns_400",
    "tests/test_phase2_search_and_edge_cases.py::test_indicators_and_setups_timeframes_and_limits",
    "tests/test_phase2_search_and_edge_cases.py::test_concurrent_setups_and_indicators_on_new_symbol",
    "tests/test_phase2_search_and_edge_cases.py::test_invalid_timeframe_and_schema_rejection",
    "tests/test_phase2_setups.py::test_setups_endpoint_returns_5_signals",
    "tests/test_phase2_setups.py::test_setups_endpoint_404_unknown_ticker",
    "tests/test_phase2_setups.py::test_indicators_endpoint_returns_all_series",
    "tests/test_phase2_setups.py::test_indicators_endpoint_series_lengths_match",
}

def pytest_collection_modifyitems(config, items):
    for item in items:
        norm_nodeid = item.nodeid.replace("\\", "/")
        if norm_nodeid in DB_INTEGRATION_TESTS or "database" in item.keywords:
            item.add_marker(pytest.mark.database)
            if not DB_AVAILABLE:
                item.add_marker(
                    pytest.mark.skip(
                        reason="PostgreSQL/TimescaleDB is offline (run 'docker compose up -d' to enable integration tests)"
                    )
                )

@pytest_asyncio.fixture(autouse=True)
async def dispose_db_engine():
    """
    Ensure SQLAlchemy async engine connection pool is cleanly disposed
    between tests so asyncpg connections don't cross event loop boundaries.
    """
    yield
    await engine.dispose()
    # Give Windows ProactorEventLoop a tick to close asyncpg socket FDs
    await asyncio.sleep(0.01)
