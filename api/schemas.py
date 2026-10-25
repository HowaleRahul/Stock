import datetime
import re
from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field, ConfigDict, field_validator

# Strict whitelist regex for ticker symbols (supports global equities, crypto pairs, Indian indices, and commodities)
TICKER_REGEX = re.compile(r"^[A-Z0-9\._\-\^\=\&]{1,64}$")

class SymbolCreate(BaseModel):
    ticker: str = Field(..., description="Stock ticker symbol (e.g. RELIANCE.NS or AAPL)")
    name: Optional[str] = Field(None, description="Company or instrument name")
    exchange: Optional[str] = Field(None, description="Exchange name (NSE, BSE, NASDAQ). Auto-detected if omitted.")
    currency: Optional[str] = Field(None, description="Trading currency (INR, USD). Auto-detected if omitted.")

    @field_validator("ticker", mode="before")
    @classmethod
    def clean_ticker(cls, v: Any) -> str:
        if v is None:
            raise ValueError("Ticker symbol cannot be empty.")
        s = str(v)
        if "\x00" in s:
            raise ValueError("Ticker symbol cannot contain null bytes.")
        cleaned = s.upper().strip()[:64]
        if not cleaned:
            raise ValueError("Ticker symbol cannot be empty or purely whitespace.")
        if ".." in cleaned or "/" in cleaned or "\\" in cleaned:
            raise ValueError("Ticker symbol cannot contain path traversal characters.")
        if not TICKER_REGEX.match(cleaned):
            raise ValueError(
                f"Invalid characters in ticker symbol '{s}'. Allowed characters: A-Z, 0-9, '.', '-', '^', '=', '&'."
            )
        return cleaned

    @field_validator("name", "exchange", "currency", mode="before")
    @classmethod
    def clean_optional_strings(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        cleaned = str(v).strip().replace("\x00", "")
        return cleaned if cleaned else None

class SymbolResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str
    name: Optional[str]
    exchange: str
    currency: str
    is_active: bool
    created_at: datetime.datetime

class CandleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    time: datetime.datetime
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    adjusted_close: float
    volume: float
    split_ratio: float
    dividend: float

class NewsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    time: datetime.datetime
    url: str
    title: str
    source: str
    summary: Optional[str]

class SyncRequest(BaseModel):
    ticker: Optional[str] = Field(None, description="Specific ticker to sync. If None and sync_watchlist=True, syncs all.")
    period: str = Field("5y", description="Historical period to download (e.g. 1mo, 1y, 5y, max)")
    interval: str = Field("1d", description="Candle timeframe interval (1d, 1h, 15m)")
    sync_watchlist: bool = Field(False, description="If True, syncs all active watchlist symbols.")
    sync_news: bool = Field(False, description="If True, also pulls financial news headlines.")

    @field_validator("ticker", mode="before")
    @classmethod
    def clean_ticker(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        s = str(v)
        if "\x00" in s:
            raise ValueError("Ticker symbol cannot contain null bytes.")
        cleaned = s.upper().strip()[:64]
        if not cleaned:
            return None
        if not TICKER_REGEX.match(cleaned):
            raise ValueError(
                f"Invalid characters in ticker symbol '{s}'. Allowed characters: A-Z, 0-9, '.', '-', '^', '=', '&'."
            )
        return cleaned

    @field_validator("interval", mode="before")
    @classmethod
    def clean_interval(cls, v: Any) -> str:
        cleaned = str(v).lower().strip() if v is not None else "1d"
        if not cleaned:
            cleaned = "1d"
        valid = {"1m", "2m", "3m", "5m", "10m", "15m", "30m", "45m", "60m", "90m", "1h", "2h", "3h", "4h", "1d", "5d", "1wk", "1mo", "3mo"}
        if cleaned not in valid:
            raise ValueError(f"Invalid interval '{cleaned}'. Allowed: {', '.join(sorted(valid))}")
        return cleaned

    @field_validator("period", mode="before")
    @classmethod
    def clean_period(cls, v: Any) -> str:
        cleaned = str(v).lower().strip() if v is not None else "5y"
        if not cleaned:
            cleaned = "5y"
        valid = {"1d", "5d", "7d", "1mo", "3mo", "6mo", "60d", "1y", "2y", "730d", "5y", "10y", "ytd", "max"}
        if cleaned not in valid:
            raise ValueError(f"Invalid period '{cleaned}'. Allowed: {', '.join(sorted(valid))}")
        return cleaned

class SyncResponse(BaseModel):
    message: str
    results: List[Dict[str, Any]]


# ---------------------------------------------------------------------------
# Phase 2 — Setup Evaluation Schemas
# ---------------------------------------------------------------------------

class SetupSignalResponse(BaseModel):
    """Single setup evaluation result."""
    name: str
    signal: str
    confidence: float
    reasoning: str

class RegimeResponse(BaseModel):
    regime: str
    adx: float
    direction: str

class EnsembleSignalResponse(BaseModel):
    """Machine Learning Stacking Ensemble Master Signal."""
    signal: str
    probability: float
    drivers: List[str]
    alternative_scenario: str
    model_version: str

class SetupEvaluationResponse(BaseModel):
    """Aggregated response from running all setups on a ticker."""
    ticker: str
    timeframe: str
    bars_analyzed: int
    evaluated_at: datetime.datetime
    regime: Optional[RegimeResponse] = None
    meta_model: Optional[EnsembleSignalResponse] = None
    setups: List[SetupSignalResponse]

class IndicatorDataResponse(BaseModel):
    """Raw indicator series for chart overlay rendering."""
    ticker: str
    timeframe: str
    candles: List[CandleResponse]
    ema_20: List[Optional[float]]
    ema_50: List[Optional[float]]
    rsi_14: List[Optional[float]]
    macd_line: List[Optional[float]]
    macd_signal: List[Optional[float]]
    macd_histogram: List[Optional[float]]
    bb_upper: List[Optional[float]]
    bb_middle: List[Optional[float]]
    bb_lower: List[Optional[float]]
    support_levels: List[float]
    resistance_levels: List[float]

