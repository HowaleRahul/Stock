# Data Ingestion & Storage Module (`/data`)

## Responsibilities
- **Ingestion Scripts:** Scheduled tasks and background workers to fetch historical OHLCV data across timeframes (`1m`, `5m`, `15m`, `1d`) from brokers and market data APIs.
- **Websocket Handlers:** Live tick/bar streaming for real-time paper trading and live setup evaluations.
- **TimescaleDB Schema & Models:** SQLAlchemy/Alembic models for hyper-tables (`ohlcv_bars`, `tick_data`, `corporate_actions`).
- **Feature Store & Caching:** Precomputing and caching clean technical indicators (`RSI`, `EMA`, `ATR`, `VWAP`, `Bollinger Bands`) for rapid setup evaluation.

## Roadmap Status
- **Phase 0:** Directory initialized, ready for Phase 1 ingestion pipelines.
