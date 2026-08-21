import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from api.db import get_db, check_database_connection, engine, Base
from models.init_db import init_database
from api.router import router as data_router
from api.dashboard_router import router as dashboard_router
from api.auth import get_api_key

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
    "http://127.0.0.1:8000",
    "http://localhost:5173",
    "http://127.0.0.1:5173"
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

from starlette.responses import Response

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    # Always set these headers regardless of environment
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if settings.environment.lower() == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' https://unpkg.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; connect-src 'self'; img-src 'self' data:;"
    return response

from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        # Keep FastAPI's standard `detail` field for compatible clients while
        # retaining the API's structured error shape.
        content={"error": True, "detail": exc.detail, "message": exc.detail, "status_code": exc.status_code},
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled Exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": True, "message": "Internal Server Error", "status_code": 500},
    )

from api.backtest_router import router as backtest_router
from api.training_router import router as training_router
from api.strategy_router import router as strategy_router

# Include API routes
app.include_router(data_router)
app.include_router(dashboard_router)
app.include_router(backtest_router)
app.include_router(training_router)
app.include_router(strategy_router)

# Serve frontend static files (Phase 2 Chart UI)
_frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
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
async def db_check(_api_key: str = Depends(get_api_key)):
    """Exercises async database connection pool to verify Postgres/TimescaleDB connectivity."""
    status_summary = await check_database_connection()
    return status_summary
