import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from api.db import Base

class Symbol(Base):
    """
    Tracks tradable financial instruments (e.g. RELIANCE.NS, TCS.NS, AAPL).
    """
    __tablename__ = "symbols"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    ticker = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(256), nullable=True)
    exchange = Column(String(32), default="NSE", nullable=False)
    currency = Column(String(16), default="INR", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    candles = relationship("OHLCVBar", back_populates="symbol", cascade="all, delete-orphan")
    news = relationship("NewsHeadline", back_populates="symbol", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Symbol(id={self.id}, ticker='{self.ticker}', exchange='{self.exchange}')>"


class OHLCVBar(Base):
    """
    Partitioned TimescaleDB hypertable storing historical and near-live OHLCV candlestick data.
    Includes corporate action fields (split_ratio, dividend, adjusted_close) for accurate indicator calculations.
    """
    __tablename__ = "ohlcv_bars"

    # Composite Primary Key required for TimescaleDB hypertable partitioning on 'time'
    time = Column(DateTime(timezone=True), primary_key=True, nullable=False, index=True)
    symbol_id = Column(Integer, ForeignKey("symbols.id", ondelete="CASCADE"), primary_key=True, nullable=False, index=True)
    timeframe = Column(String(16), primary_key=True, default="1d", nullable=False)

    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    adjusted_close = Column(Float, nullable=False)
    volume = Column(Float, default=0.0, nullable=False)

    # Corporate Actions
    split_ratio = Column(Float, default=1.0, nullable=False)
    dividend = Column(Float, default=0.0, nullable=False)

    # Relationship
    symbol = relationship("Symbol", back_populates="candles")

    def __repr__(self) -> str:
        return f"<OHLCVBar(symbol_id={self.symbol_id}, time={self.time}, timeframe='{self.timeframe}', close={self.close})>"


class NewsHeadline(Base):
    """
    Partitioned TimescaleDB hypertable storing raw financial news headlines linked to symbols.
    """
    __tablename__ = "news_headlines"

    time = Column(DateTime(timezone=True), primary_key=True, nullable=False, index=True)
    url = Column(String(1024), primary_key=True, nullable=False)
    symbol_id = Column(Integer, ForeignKey("symbols.id", ondelete="CASCADE"), nullable=True, index=True)
    title = Column(String(512), nullable=False)
    source = Column(String(128), default="Yahoo Finance", nullable=False)
    summary = Column(Text, nullable=True)

    # Relationship
    symbol = relationship("Symbol", back_populates="news")

    __table_args__ = (
        Index("ix_news_symbol_time", "symbol_id", "time"),
    )

    def __repr__(self) -> str:
        return f"<NewsHeadline(time={self.time}, symbol_id={self.symbol_id}, title='{self.title[:30]}...')>"
class Account(Base):
    __tablename__ = 'accounts'
    id = Column(Integer, primary_key=True, autoincrement=True)
    capital = Column(Float, nullable=False)
    peak_capital = Column(Float, nullable=False)
    status = Column(String(32), default='ACTIVE')
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class Trade(Base):
    __tablename__ = 'trades'
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(64), unique=True, index=True)
    ticker = Column(String(64), index=True, nullable=False)
    direction = Column(String(16), nullable=False)
    entry_price = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False)
    invested = Column(Float, nullable=False)
    take_profit = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    is_open = Column(Boolean, default=True)
    exit_price = Column(Float, nullable=True)
    pnl_pct = Column(Float, nullable=True)
    entry_time = Column(DateTime(timezone=True), default=func.now())
    exit_time = Column(DateTime(timezone=True), nullable=True)
