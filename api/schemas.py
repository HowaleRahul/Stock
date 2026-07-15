import datetime
from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field, ConfigDict, field_validator

class SymbolCreate(BaseModel):
    ticker: str = Field(..., description="Stock ticker symbol (e.g. RELIANCE.NS or AAPL)")
    name: Optional[str] = Field(None, description="Company or instrument name")
    exchange: Optional[str] = Field(None, description="Exchange name (NSE, BSE, NASDAQ). Auto-detected if omitted.")
    currency: Optional[str] = Field(None, description="Trading currency (INR, USD). Auto-detected if omitted.")

    @field_validator("ticker", mode="before")
    @classmethod
    def clean_ticker(cls, v: Any) -> str:
        if isinstance(v, str):
            cleaned = v.upper().strip()
            if not cleaned:
                raise ValueError("Ticker symbol cannot be empty or purely whitespace.")
            return cleaned
        if v is None or not str(v).strip():
            raise ValueError("Ticker symbol cannot be empty.")
        return str(v).upper().strip()

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
        if isinstance(v, str):
            cleaned = v.upper().strip()
            return cleaned if cleaned else None
        return str(v).upper().strip()

class SyncResponse(BaseModel):
    message: str
    results: List[Dict[str, Any]]
