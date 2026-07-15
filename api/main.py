import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from api.db import get_db, check_database_connection, engine, Base
from models.init_db import init_database
from api.router import router as data_router

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)
logger = logging.getLogger("trading.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle events for startup and shutdown of the FastAPI server."""
    logger.info(f"🚀 Starting Personal AI-Assisted Trading System API in [{settings.environment}] mode...")
    logger.info(f"Target Focus Symbols: {settings.target_symbols}")
    
    # Optional: Check database connection on startup
    db_status = await check_database_connection()
    if db_status["status"] == "connected":
        logger.info(f"✅ Database connected successfully! Latency: {db_status['latency_ms']}ms | TimescaleDB: {db_status.get('timescaledb_version', 'N/A')}")
        # Initialize schema and TimescaleDB hypertables if in local development
        if settings.environment.lower() == "development":
            try:
                init_res = await init_database(seed_watchlist=True)
                logger.info(f"✅ Schema & Hypertables initialized: {init_res}")
            except Exception as e:
                logger.error(f"❌ Error initializing hypertables: {e}")
    else:
        logger.warning(f"⚠️ Could not connect to Database on startup: {db_status.get('error', 'unknown error')}. Please check your docker container or .env DATABASE_URL.")

    yield
    
    logger.info("🛑 Shutting down Trading System API and closing DB connections...")
    await engine.dispose()


app = FastAPI(
    title="Personal AI-Assisted Trading System API",
    description="Explainable ML-driven decision-support system for equity, intraday, and F&O trading.",
    version="0.1.0-phase0",
    lifespan=lifespan
)

# Enable CORS (for future Phase 6 Frontend UI)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(data_router)


@app.get("/", tags=["General"])
async def root():
    """Root endpoint providing system identification and navigation."""
    return {
        "system": "Personal AI-Assisted Trading System",
        "current_phase": "Phase 1 — Data Pipeline (MVP)",
        "documentation": "/docs",
        "health_check": "/health",
        "database_check": "/db-check"
    }


@app.get("/health", tags=["Monitoring"])
async def health_check():
    """Returns application health, phase status, environment, and configured focus symbols."""
    return {
        "status": "ok",
        "service": "trading-api",
        "version": "0.1.0-phase1",
        "phase": "Phase 1 (Data Pipeline)",
        "environment": settings.environment,
        "target_symbols": settings.target_symbols,
    }


@app.get("/db-check", tags=["Monitoring"])
async def db_check():
    """Exercises async database connection pool to verify Postgres/TimescaleDB connectivity."""
    status_summary = await check_database_connection()
    return status_summary
