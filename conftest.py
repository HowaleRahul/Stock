import asyncio
import pytest
import pytest_asyncio
from api.db import engine

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
