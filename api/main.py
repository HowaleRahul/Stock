import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
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
    version="0.2.0-phase2",
    lifespan=lifespan
)

# Enable CORS cleanly according to W3C specification
# Default to strict local origins if not overridden
_cors_origins = getattr(settings, "cors_origins", [
    "http://localhost",
    "http://localhost:8000",
    "http://127.0.0.1",
    "http://127.0.0.1:8000"
])
_allow_creds = False if "*" in _cors_origins else True
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_allow_creds,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Enforce Strict-Transport-Security (HSTS) in production
from fastapi import Request
from starlette.responses import Response

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    if settings.environment.lower() == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
    return response

# Include API routes
app.include_router(data_router)

# Serve frontend static files (Phase 2 Chart UI)
_frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/app", StaticFiles(directory=_frontend_dir, html=True), name="frontend")


@app.get("/", tags=["General"])
async def root():
    """Root endpoint providing system identification and navigation."""
    return {
        "system": "Personal AI-Assisted Trading System",
        "current_phase": "Phase 2 — Technical Setups + Chart UI",
        "documentation": "/docs",
        "health_check": "/health",
        "database_check": "/db-check",
        "dashboard": "/app/",
    }


@app.get("/health", tags=["Monitoring"])
async def health_check():
    """Returns application health, phase status, environment, and configured focus symbols."""
    return {
        "status": "ok",
        "service": "trading-api",
        "version": "0.2.0-phase2",
        "phase": "Phase 2 (Technical Setups + Chart UI)",
        "environment": settings.environment,
        "target_symbols": settings.target_symbols,
    }


@app.get("/db-check", tags=["Monitoring"])
async def db_check():
    """Exercises async database connection pool to verify Postgres/TimescaleDB connectivity."""
    status_summary = await check_database_connection()
    return status_summary
