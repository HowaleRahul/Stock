import logging
import time
from typing import AsyncGenerator, Dict, Any
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
    AsyncEngine
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from api.config import settings

logger = logging.getLogger("trading.db")

# Create async engine with connection pooling
engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=(settings.environment.lower() == "development" and settings.log_level.upper() == "DEBUG"),
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

# Async session factory
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy ORM models."""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def check_database_connection() -> Dict[str, Any]:
    """
    Checks connection status to the database and detects if TimescaleDB extension is enabled.
    Returns status summary dict.
    """
    start_time = time.perf_counter()
    try:
        async with async_session_factory() as session:
            # Check basic connection
            result = await session.execute(text("SELECT 1;"))
            row = result.scalar()
            if row != 1:
                return {
                    "status": "error",
                    "message": "Database ping returned unexpected result.",
                    "latency_ms": round((time.perf_counter() - start_time) * 1000, 2)
                }

            # Check if TimescaleDB extension is active
            timescaledb_version = None
            try:
                ext_res = await session.execute(
                    text("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb';")
                )
                timescaledb_version = ext_res.scalar()
            except Exception as ext_err:
                logger.debug(f"Could not check timescaledb extension: {ext_err}")

            latency = round((time.perf_counter() - start_time) * 1000, 2)
            return {
                "status": "connected",
                "database_url_masked": _mask_db_url(settings.database_url),
                "timescaledb_version": timescaledb_version or "not_installed/standard_postgres",
                "latency_ms": latency
            }
    except Exception as e:
        logger.error(f"Database connection check failed: {str(e)}")
        return {
            "status": "disconnected",
            "error": str(e),
            "latency_ms": round((time.perf_counter() - start_time) * 1000, 2)
        }


def _mask_db_url(url: str) -> str:
    """Helper to mask password in database connection URL for safe logging/display."""
    if "@" in url and ":" in url:
        try:
            prefix, rest = url.split("://", 1)
            user_info, host_info = rest.split("@", 1)
            if ":" in user_info:
                user, _ = user_info.split(":", 1)
                return f"{prefix}://{user}:***@{host_info}"
        except Exception:
            pass
    return "postgresql+asyncpg://***:***@***"
