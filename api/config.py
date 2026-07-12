from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """
    Application settings and secrets loaded securely from environment variables or .env file.
    Never hardcode secrets in source code.
    """
    # App Environment
    environment: str = Field(default="development", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    api_port: int = Field(default=8000, alias="API_PORT")
    api_host: str = Field(default="127.0.0.1", alias="API_HOST")

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:trading_secret_pwd@127.0.0.1:5432/trading_db",
        alias="DATABASE_URL"
    )

    # Initial Focus Target Symbols (Indices & Equities for F&O / Intraday)
    target_symbols: List[str] = Field(
        default=["NIFTY", "BANKNIFTY", "RELIANCE.NS", "HDFCBANK.NS", "TCS.NS"],
        alias="TARGET_SYMBOLS"
    )

    # Broker API placeholders (for Phase 1+)
    kite_api_key: Optional[str] = Field(default=None, alias="KITE_API_KEY")
    kite_api_secret: Optional[str] = Field(default=None, alias="KITE_API_SECRET")
    angel_api_key: Optional[str] = Field(default=None, alias="ANGEL_API_KEY")
    upstox_api_key: Optional[str] = Field(default=None, alias="UPSTOX_API_KEY")
    polygon_api_key: Optional[str] = Field(default=None, alias="POLYGON_API_KEY")
    alphavantage_api_key: Optional[str] = Field(default=None, alias="ALPHAVANTAGE_API_KEY")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )


# Global settings singleton
settings = Settings()
