# Current Implementation State

This document provides a comprehensive, factual snapshot of the architecture, components, workflows, and operational state of the **Personal AI-Assisted Trading System (Signal Desk)** as it exists in the codebase today.

---

## 1. Project Purpose

The **Personal AI-Assisted Trading System (Signal Desk)** is an end-to-end algorithmic trading and decision-support workstation. It combines classical technical analysis setups, machine learning meta-models, reinforcement learning setup reweighting, real-time market data streaming, and risk management. 

Primary focus:
1. **Indian Markets (NSE/BSE)**: Intraday and swing trading on major indices (`^NSEI` / NIFTY 50, `^NSEBANK` / BANK NIFTY, `^BSESN` / SENSEX) and liquid blue-chip equities.
2. **Derivatives (F&O)**: Long call/put options buying (`CE`/`PE`) with Black-Scholes Greeks evaluation and SEBI 2026 retail algo compliance constraints.
3. **Momentum Swing Toolkit**: 3 scanning strategies (Momentum, DWIB, ATH Contraction), 8-factor quality scoring, and 15-minute Opening Range Breakout (ORB) execution.
4. **Multi-Asset Extensibility**: Strict asset-class policies supporting US Equities (`^GSPC`, `^DJI`, `^IXIC`, `AAPL`, `NVDA`, `MSFT`) and Cryptocurrencies (`BTC-USD`, `ETH-USD`, `SOL-USD`).

---

## 2. Technology Stack

### Backend
- **Runtime**: Python 3.13
- **Web Framework**: FastAPI $\ge 0.110.0$, Uvicorn $\ge 0.28.0$
- **Data Validation & Settings**: Pydantic $\ge 2.6.0$, Pydantic Settings $\ge 2.2.0$, python-dotenv $\ge 1.0.1$
- **Database ORM & Drivers**: SQLAlchemy $\ge 2.0.28$ (AsyncIO), asyncpg $\ge 0.29.0$, Alembic $\ge 1.13.1$
- **Data & Scientific Computing**: pandas 2.2.3, numpy 1.26.0, scikit-learn 1.4.0, scipy 1.14.1, joblib 1.3.2
- **Financial & Indicator Libraries**: yfinance 0.2.52, tradingview-ta $\ge 3.3.0$, ta 0.11.0, pandas-ta 0.3.14b0, vaderSentiment 3.3.2
- **Utilities & Networking**: httpx $\ge 0.27.0$, requests, cachetools 7.1.4

### Database & Infrastructure
- **Relational / Time-Series Database**: PostgreSQL 16 with TimescaleDB extension
- **Containerization**: Docker & Docker Compose (Alpine-based `Dockerfile.postgres-local`)

### Frontend
- **Framework**: React 19 (`19.2.8`), React DOM 19
- **Language**: TypeScript (`7.0.2`)
- **Build Tool & Bundler**: Vite (`8.2.2`) with `@vitejs/plugin-react`
- **Routing**: React Router DOM (`7.18.2`) with lazy route splitting
- **Styling**: Tailwind CSS 4 (`4.3.3`), PostCSS, custom CSS theme (`index.css`)
- **Charting**: TradingView Lightweight Charts (`5.2.1`), TradingView Embedded Iframe Widgets
- **Icons**: Lucide React (`1.33.0`)
- **HTTP Client**: Axios (`1.19.0`)
- **Linter**: Oxlint (`1.75.0`)

### Testing
- **Test Framework**: pytest $\ge 8.0.0$, pytest-asyncio $\ge 0.23.5$

---

## 3. Directory Structure

```
Stock/
├── .env / .env.example       # Environment configuration & secrets
├── config.json               # Runtime trading & risk configuration
├── docker-compose.yml        # Docker service definition for TimescaleDB
├── Dockerfile.postgres-local # Alpine + TimescaleDB container build
├── entrypoint.sh             # Database container init & bridge subnet auth
├── start.py                  # Master process launcher (FastAPI, Trader, Vite)
├── requirements.txt          # Python dependencies
├── paper_account.json        # Fallback local account balance state
├── paper_trades.json         # Fallback local paper trades state
├── paper_trader.py           # Autonomous background paper-trading daemon
├── live_trader.py            # Live broker trading daemon (fails closed)
├── REVIEW_LOG.md             # Running production review and verification log
├── iterate.txt               # Adversarial SDET and RL self-play specifications
├── backtest_report.md        # Walk-forward backtest summary report
│
├── api/                      # FastAPI Backend Application
│   ├── main.py               # Application entrypoint, CORS, lifespan, security headers
│   ├── auth.py               # API key authentication & rate limiting
│   ├── config.py             # Pydantic Settings management
│   ├── db.py                 # Async SQLAlchemy engine & connection check
│   ├── schemas.py            # Pydantic input/output models
│   ├── broker.py             # Broker API scaffolding & static IP check
│   ├── notifier.py           # Telegram notification dispatcher
│   ├── catalog.py            # Hardcoded ticker autocomplete catalog
│   ├── router.py             # Data pipeline & watchlist endpoints
│   ├── dashboard_router.py   # Metrics, portfolio, analytics, config endpoints
│   ├── market_router.py      # Real-time quotes, candles, TradingView TA, options
│   ├── backtest_router.py    # Walk-forward backtest runner endpoint
│   ├── training_router.py    # Continuous model training controls & telemetry
│   ├── strategy_router.py    # No-code strategy persistence & rule evaluation
│   └── swing_router.py       # Momentum Masters swing scanners & watchlist endpoints
│
├── data/                     # Ingestion & Market Feeds
│   ├── cleaner.py            # Corporate actions cleaning & string sanitization
│   ├── fetcher.py            # Synchronous-to-async yfinance wrapper & aliases
│   ├── market_hours.py       # IST market session management & holiday schedules
│   ├── news_fetcher.py       # Financial news headline scraper
│   ├── realtime_feed.py      # TradingView-ta & yfinance live quote cache
│   ├── service.py            # TimescaleDB idempotent bulk upsert service
│   ├── swing_watchlist.json  # Persisted active swing candidates
│   └── sync_cli.py           # Scheduled historical data CLI ingestion
│
├── models/                   # Database ORM Models
│   ├── models.py             # SQLAlchemy models (Symbol, OHLCVBar, NewsHeadline, etc.)
│   └── init_db.py            # Hypertable initialization & default watchlist seeding
│
├── setups/                   # Technical Analysis Setups
│   ├── base.py               # BaseSetup abstract interface & SetupSignal dataclass
│   ├── engine.py             # SetupEngine orchestrator (5 core setups + regime)
│   ├── indicators.py         # Pure mathematical indicators (SMA, EMA, RSI, MACD, BB)
│   ├── regime.py             # ADX-based Market Regime detector
│   ├── ma_crossover.py       # Moving average crossover setup
│   ├── rsi_setup.py          # RSI overbought/oversold & divergence setup
│   ├── macd_setup.py         # MACD signal line crossover setup
│   ├── bollinger_setup.py    # Bollinger Band squeeze & breakout setup
│   ├── breakout_setup.py     # Donchian channel support/resistance breakout
│   ├── swing_toolkit_setup.py# BaseSetup adapter for Momentum Masters
│   ├── swing_toolkit/        # Specialized Momentum Masters suite
│   │   ├── universe.py       # Curated 50+ liquid Indian swing universe
│   │   ├── scanners.py       # Momentum, DWIB, ATH Contraction scanners
│   │   ├── checklist.py      # 8-factor quality scoring engine
│   │   ├── orb_entry.py      # 15m ORB breakout with early volume gates
│   │   └── toolkit.py        # SwingToolkitManager orchestrator
│   └── (experimental setups) # options, sentiment, psychology, ichimoku, fibonacci, etc.
│
├── ml/                       # Machine Learning & AI Feedback Engine
│   ├── assets.py             # Canonical asset-class policy (IN, US, CRYPTO)
│   ├── features.py           # Triple-barrier labeling & synthetic Greeks
│   ├── ensemble.py           # Stacking Logistic Regression ensemble & XAI
│   ├── train.py              # Batch model training script
│   ├── continuous_trainer.py # Incremental SGDClassifier online learner
│   ├── risk_engine.py        # Kelly criterion, ATR stops, probability of ruin
│   ├── options_engine.py     # Long options contract selection & Greek math
│   ├── trade_logger.py       # Structured trade event logger
│   ├── reinforcement_learner.py # Contextual Bandit (Beta prior + Thompson Sampling)
│   ├── journal_analyzer.py   # Meta-pattern profitability matrix & setup gating
│   ├── replay_engine.py      # Historical bar-by-bar RL self-play simulator
│   ├── drift_detector.py     # Kolmogorov-Smirnov distribution drift detector
│   ├── performance_dashboard.py # Rolling Sharpe, Sortino, max drawdown analyzer
│   ├── models/               # Model weights & scaler artifacts
│   └── registry/             # Serialized model bundles per timeframe
│
├── papertrade/               # Persistence & Portfolio State
│   └── persistence.py        # PostgreSQL transaction boundary for paper trades
│
├── frontend/                 # Active React 19 + TypeScript + Vite SPA
│   ├── src/
│   │   ├── App.tsx           # Shell layout, navigation sidebar, route declarations
│   │   ├── main.tsx          # Axios auth interceptors, query param sanitization
│   │   ├── components/       # ChartWidget, OptionChartViewer, SettingsModal, etc.
│   │   └── pages/            # 8 operational workspace pages
│   └── package.json          # Node dependencies & Vite config
│
├── scripts/                  # Migration & maintenance scripts
└── tests/                    # 14 test suites covering 148 test cases (131 hermetic unit, 17 database)
```

---

## 4. Major Components

### 4.1 Backend API Gateway (`api/main.py`)
FastAPI application configured with:
- Lifespan context manager that validates authentication configuration and runs startup database checks.
- Security headers middleware (`nosniff`, `DENY`, strict referrer policy, HSTS and CSP in production).
- Exception handlers returning standardized JSON error envelopes.
- SPA static file handler serving `frontend/dist` under `/app/`.

### 4.2 Database Layer (`models/models.py`, `api/db.py`)
PostgreSQL 16 with TimescaleDB extension. Defines:
1. `symbols`: Tradable assets metadata.
2. `ohlcv_bars`: TimescaleDB hypertable partitioned on `time`, composite primary key `(time, symbol_id, timeframe)`.
3. `news_headlines`: TimescaleDB hypertable partitioned on `time`, composite primary key `(time, url)`.
4. `accounts`: Virtual capital balance, peak capital, operational status.
5. `trades`: Open and closed trade records.
6. `trade_context`: Serialized JSON payload containing technical setups and model weights at entry.
7. `journal_events`: Immutable audit trail for all trading events (`ENTRY`, `EXIT`, `REJECTION`, `KILL_SWITCH`, `RL_DECISION`).

### 4.3 Technical Setups Engine (`setups/engine.py`)
Runs 5 deterministic core setups:
- `MACrossoverSetup`: EMA 9/21 and SMA 50/200 crossovers.
- `RSISetup`: 14-period RSI overbought/oversold and basic divergence.
- `MACDSetup`: 12/26/9 MACD signal line crossovers.
- `BollingerBandsSetup`: 20-period, 2-standard-deviation band squeezes.
- `BreakoutSetup`: 20-period Donchian channel breakout confirmed by volume.

Gated by `RegimeDetector`:
- `trending-bullish` / `trending-bearish`: Trends reinforced.
- `range-bound`: Trend setups slashed in confidence by 50%.
- `crash`: Bullish setups gated to confidence 0.0 ("falling knife" protection).

### 4.4 Machine Learning & Risk Intelligence
- **Stacking Ensemble (`ml/ensemble.py`)**: Predicts directional probability and outputs feature contributions (XAI) using logistic regression weights. Falls back to unweighted heuristic voting when model artifacts or scalers are incompatible.
- **Risk Engine (`ml/risk_engine.py`)**: Computes trade plans using Kelly criterion position sizing (capped at 2% capital risk), ATR-based stops and targets, minimum 1.5:1 Risk-to-Reward gating, and probability of ruin.
- **Options Engine (`ml/options_engine.py`)**: Maps directional index signals to near-the-money long calls or puts (`CE`/`PE`), calculates Black-Scholes Greeks (delta, gamma, theta), and sizes contracts to round lot sizes.
- **RL Contextual Bandit (`ml/reinforcement_learner.py`)**: Uses Thompson Sampling over Beta posteriors to adjust setup weights based on trade outcomes per market regime.
- **Journal Analyzer (`ml/journal_analyzer.py`)**: Discovers meta-patterns from trade history and suppresses setups with win rates below 40% in specific regimes.
- **Historical Replay Engine (`ml/replay_engine.py`)**: High-speed bar-by-bar simulator with order execution at next bar's open and STT/slippage friction (0.05%).

### 4.5 Momentum Masters Swing Toolkit (`setups/swing_toolkit/`)
Dedicated positional swing toolkit for Indian equities:
- **Universe (`universe.py`)**: 50+ highly liquid NSE tickers categorized into sectors.
- **Scanners (`scanners.py`)**:
  1. *Momentum Scanner*: Relative volume surge ($\ge 1.5\times$), 20-day breakout or tight consolidation.
  2. *DWIB Scanner*: Daily/Weekly Inside Bar range contraction.
  3. *ATH Contraction Scanner*: Tickers within 15% of 52-week highs contracting along 10/20 EMAs.
- **Checklist (`checklist.py`)**: 8-factor score (Stage 2 trend, RS vs Nifty, volume dry-up, sector momentum, risk-reward). Threshold $\ge 70\%$ for actionable candidate status.
- **ORB Engine (`orb_entry.py`)**: 15-minute Opening Range Breakout with early 5m/15m volume validation gates.

---

## 5. API Structure & Route Inventory

All endpoints reside under the `/api/v1` namespace:

| Router | Prefix | Endpoint | Method | Description |
|---|---|---|---|---|
| **Data & Watchlist** | `/api/v1` | `/search` | GET | Symbol search with fuzzy scoring |
| | | `/symbols` | GET | List all active watchlist symbols |
| | | `/symbols` | POST | Add new symbol to database |
| | | `/init` | POST | Initialize schema & seed watchlist |
| | | `/sync` | POST | Trigger historical OHLCV/news sync |
| | | `/candles/{ticker}` | GET | Historical OHLCV bars |
| | | `/news/{ticker}` | GET | Financial news headlines |
| | | `/setups/{ticker}` | GET | Evaluate 5 core setups + regime |
| | | `/indicators/{ticker}`| GET | Pre-computed indicators for charts |
| **Market Feeds** | `/api/v1/market` | `/status` | GET | Exchange session & holiday status |
| | | `/quote/{ticker}` | GET | Real-time quote with caching |
| | | `/candles/{ticker}` | GET | Live streaming candle bars |
| | | `/ta/{ticker}` | GET | TradingView technical indicator summary |
| | | `/watchlist` | GET | Quotes for all watchlist symbols |
| | | `/option-chart` | GET | Synthetic option contract historical bars |
| | | `/live-tick/{ticker}` | GET | High-frequency quote tick |
| | | `/option-tick` | GET | Option contract live quote tick |
| **Dashboard** | `/api/v1/dashboard`| `/metrics` | GET | Real-time P&L, win-rate, capital |
| | | `/portfolio` | GET | Active positions & account balance |
| | | `/analytics` | GET | Comprehensive performance statistics |
| | | `/trades` | GET | Trade history & audit records |
| | | `/config` | GET/POST| Read/write runtime trading config |
| | | `/ai-journal` | GET | AI journal events & RL setup weights |
| **Swing Toolkit** | `/api/v1/swing` | `/universe` | GET | Curated liquid Indian swing universe |
| | | `/scanners/run` | GET | Execute 3 scanners & 8-factor checklist |
| | | `/watchlist` | GET/POST| View or add candidates to swing list |
| | | `/watchlist/{ticker}`| DELETE| Remove candidate from swing list |
| | | `/orb-check/{ticker}`| GET | Evaluate 15m ORB trigger & volume gates|
| **Backtest** | `/api/v1/backtest` | `/run` | GET | Run walk-forward backtest simulation |
| **Training** | `/api/v1/training` | `/start` | POST | Start continuous online training thread |
| | | `/stop` | POST | Stop continuous training thread |
| | | `/status` | GET | Real-time training telemetry & logs |
| | | `/live-portfolio` | GET | Training virtual wallet balance |
| **Strategies** | `/api/v1/strategy` | `/list` | GET | List custom user-defined strategies |
| | | `/create` | POST | Save new strategy definition |
| | | `/{name}` | DELETE | Delete saved strategy |

---

## 6. Authentication & Security Architecture

1. **Environment Configuration**:
   - `ENVIRONMENT` defaults to `production`.
   - In production or non-loopback bindings, `API_KEY` must be configured. Keyless access is restricted strictly to `ENVIRONMENT=development` on loopback hosts (`127.0.0.1`, `localhost`, `::1`).
2. **Credential Verification**:
   - Header transport via `X-API-Key` or `Authorization: Bearer <key>`.
   - Timing-safe comparison using `secrets.compare_digest`.
   - URL query parameter authentication is prohibited.
3. **Rate Limiting**:
   - In-memory sliding window using `cachetools.TTLCache(maxsize=100000, ttl=60)`.
   - Quota namespaced per `(client_ip, endpoint_path, quota)`.
   - Reverse-proxy header (`X-Forwarded-For`) is trusted only when the immediate connection originates from loopback or RFC1918 private subnets.
4. **Transport Security**:
   - Production responses include HSTS headers (`max-age=31536000; includeSubDomains; preload`).
   - Content Security Policy (CSP), `X-Content-Type-Options: nosniff`, and `X-Frame-Options: DENY`.

---

## 7. Build, Run & Process Orchestration

### Prerequisites
- Python 3.13 inside a virtual environment (`venv`).
- Node.js & npm for frontend.
- Docker Desktop running for TimescaleDB.

### Startup Workflow (`start.py`)
Running `python start.py` initiates three parallel processes:
1. **FastAPI Backend**: `venv\Scripts\python -m uvicorn api.main:app --reload --port 8000`
2. **AI Background Trader**: `venv\Scripts\python paper_trader.py`
3. **React Frontend**: `npm.cmd run dev` inside `frontend/` (accessible at `http://localhost:5173/app/`)

### Docker Database Service
```powershell
docker compose up -d
```
Starts container `trading_timescaledb` on `127.0.0.1:5432` with volume `pgdata`.

---

## 8. Current Feature Status Matrix

| Component / Subsystem | Implementation State | Verification Status | Operational Notes |
|---|---|---|---|
| **TimescaleDB Storage** | Production-ready | Verified | Stores bars and news; requires Docker container online. |
| **Dual Persistence** | Production-ready | Verified | Automatically falls back to JSON files if DB is offline. |
| **Core Setup Engine** | Production-ready | Verified | 5 deterministic setups + ADX regime detection. |
| **Swing Toolkit** | Production-ready | Verified | 3 scanners, 8-factor checklist, 15m ORB volume gate. |
| **Real-Time Data Feeds**| Production-ready | Verified | TradingView-ta with bounded TTL caching & yfinance fallback. |
| **Paper Trading Daemon**| Production-ready | Verified | Autonomous 1-hour scan loop, Kelly sizing, MTM drawdown lock. |
| **Risk Engine** | Production-ready | Verified | 2% risk cap, 1.5:1 min R:R, ATR stops, ruin probability. |
| **Options Engine** | Feature-complete | Verified | Black-Scholes Greeks, long CE/PE only; live execution blocked. |
| **RL Contextual Bandit**| Feature-complete | Verified | Thompson Sampling updates setup weights on trade outcomes. |
| **Replay Engine** | Feature-complete | Verified | Next-bar open execution, STT friction, isolated weights. |
| **Continuous Trainer** | Feature-complete | Verified | SGDClassifier online partial_fit; artifacts not unified with batch. |
| **Walk-Forward Backtest**| Feature-complete | Verified | Real-world friction (0.1%), label-safe test window isolation. |
| **API Authentication** | Production-ready | Verified | Fail-closed production default, timing-safe key comparison. |
| **Active Frontend SPA** | Production-ready | Verified | 8 functional pages, TypeScript clean, Vite builds in ~6s. |
| **Live Broker Execution**| Scaffolding only | Intentionally Blocked | SEBI compliance checks in place; order placement fails closed. |
