# Current Implementation State

This document provides a comprehensive, factual snapshot of the architecture, components, workflows, and operational state of the **Personal AI-Assisted Trading System (Signal Desk)** as it exists in the codebase today.

---

## 1. Project Purpose

The **Personal AI-Assisted Trading System (Signal Desk)** is an end-to-end algorithmic trading and decision-support workstation. It combines classical technical analysis setups, machine learning meta-models, reinforcement learning setup reweighting, real-time market data streaming, and risk management. 

Primary focus:
1. **Indian Stock Market F&O Specialization**: The system specializes WHOLE AND SOLE in Futures & Options (F&O) trading on the Indian stock market (NSE & BSE). Cash equity delivery, US markets, and cryptocurrencies have been completely removed.
2. **Supported Underlyings**: NIFTY 50 (`^NSEI`), BANK NIFTY (`^NSEBANK`), BSE SENSEX (`^BSESN`), FINNIFTY, and MIDCPNIFTY with exact exchange lot sizes, strike intervals, and weekly expiry schedules.
3. **Dual Scalp & Swing Framework**: Fast intraday scalp trading (`5m`, `15m`) with tight ATR barriers, and multiday positional swing trading (`1h`, `1d`) with wide trailing stops.
4. **Derivatives Execution Engine**: All trade allocations execute strictly as Index Options (CE/PE calls & puts with Black-Scholes Delta, Theta, Gamma, Vega, IV), directional option selling, defined-risk credit spreads (Bull Put & Bear Call spreads), non-directional Iron Condors (rangebound sideways regimes), or linear Index Futures depending on user capital tier, volatility regime, and SPAN margin availability. Naked unlimited-risk option selling without margin gating is prohibited; retail accounts deploy defined-risk credit spreads and Iron Condors, while institutional allocations harvest dual positive theta decay ($+\Theta > 0$) with exchange SPAN + exposure margins.
5. **Interactive Option Payoff Visualization**: Real-time continuous SVG multi-leg option payoff diagrams in the frontend with green profit and red loss clipped gradients, breakeven markers, live spot tracking, and friction breakeven modeling.
6. **Continuous AI Retraining**: Fresh stacking classifiers trained from scratch on historical Indian index data, coupled with contextual bandit strike selection and TimescaleDB hypertable persistence.

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
│   ├── broker_adapter.py     # Universal multi-broker client & high-fidelity matching engine
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
│   ├── fx_fetcher.py         # Frankfurter ECB Currency API (zero-auth USD/INR live & historical FX)
│   ├── nse_feed.py           # Live NSE India option chain scraper (curl_cffi TLS, PCR, Max Pain, FII/DII)
│   ├── market_hours.py       # IST market session management & holiday schedules
│   ├── news_fetcher.py       # Real-time Indian Market RSS Feed & VADER financial sentiment engine
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
│   ├── engine.py             # SetupEngine orchestrator (6 core setups + optional advanced)
│   ├── indicators.py         # Pure mathematical indicators (SMA, EMA, RSI, MACD, BB)
│   ├── regime.py             # ADX-based Market Regime detector
│   ├── ma_crossover.py       # Moving average crossover setup
│   ├── rsi_setup.py          # RSI overbought/oversold & divergence setup
│   ├── macd_setup.py         # MACD signal line crossover setup
│   ├── bollinger_setup.py    # Bollinger Band squeeze & breakout setup
│   ├── breakout_setup.py     # Donchian channel support/resistance breakout
│   ├── vcp_setup.py          # Mark Minervini Volatility Contraction Pattern setup
│   ├── piotroski_setup.py    # Piotroski F-Score fundamental accounting quality setup
│   ├── options_setup.py      # Real-time Put-Call Ratio & strike Max-Pain setup
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
│   ├── circuit_breaker.py    # Account-level Drawdown Circuit Breaker & streak cooldown gate
│   ├── agent_reflection.py   # Post-trade reflection memory engine & JSONL logger
│   ├── multi_agent_consensus.py # Multi-Agent decision consensus (Tech, Deriv, Fund, Sent, Risk)
│   ├── gex_engine.py         # Institutional Dealer Gamma Exposure (GEX) engine
│   ├── options_engine.py     # Long options contract selection & Greek math
│   ├── trade_logger.py       # Structured trade event logger
│   ├── reinforcement_learner.py # Contextual Bandit (Beta prior, R-multiples, arm bandits)
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
└── tests/                    # 17 test suites covering 307 test cases (288 passed, 19 skipped, 0 failed)
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
- **Drawdown Circuit Breakers (`ml/circuit_breaker.py`)**: Account-level risk gate enforcing daily loss ceiling (2.0%), consecutive loss streak gate (3 losses triggers a 24-hour mandatory cooldown), and weekly (5%) / monthly (8%) drawdown hard ceilings.
- **Post-Trade Reflection Memory (`ml/agent_reflection.py`)**: Automatically analyzes settled paper and live trades upon exit across all exit modes, extracting structured rules and persisting lessons to `logs/agent_reflections.jsonl`.
- **Multi-Agent Consensus Engine (`ml/multi_agent_consensus.py`)**: Collaborative financial consensus engine featuring Technical, Derivatives, Fundamental, and Sentiment analyst agents, adversarial Bull vs. Bear debate, and Chief Risk Officer gating.
- **Dealer Gamma Exposure Engine (`ml/gex_engine.py`)**: Computes Call/Put walls, Gamma Flip strike, and volatility pinning vs. acceleration regimes.
- **Options Engine (`ml/options_engine.py`)**: Maps directional index signals to near-the-money long calls or puts (`CE`/`PE`), calculates Black-Scholes Greeks (delta, gamma, theta), sizes contracts to round lot sizes, and continuously trains the `FOLearner` strike contextual bandit.
- **RL Contextual Bandit (`ml/reinforcement_learner.py`)**: Uses Thompson Sampling over Beta posteriors with Risk-Adjusted Reward Shaping (R-multiples), Adaptive Prior Discounting (`discount_priors`) for regime shifts, and `ExecutionArmBandit` hyperparameter adaptation.
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
| | | `/option-strategy-payoff` | GET | Multi-leg option payoff analysis & breakeven calculation |
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

### Startup Workflow (`start.py`, `start.bat`, `start.ps1`)
Running `python start.py`, `.\start.bat`, or `.\start.ps1` automatically detects the local virtual environment (`.\venv\Scripts\python.exe`), configures environment PATH and VIRTUAL_ENV, and initiates three supervised processes:
1. **FastAPI Backend**: `venv\Scripts\python -m uvicorn api.main:app --reload --port 8000`
2. **AI Background Trader**: `venv\Scripts\python paper_trader.py`
3. **React Frontend**: `npm.cmd run dev` inside `frontend/` (accessible at `http://localhost:5173/app/`)
*Note*: `start.py` includes automatic virtualenv self-healing: if executed with the system Python interpreter, it automatically relaunches itself using the project's `venv` Python, preventing `ModuleNotFoundError` crashes in Uvicorn reloader subprocesses or background workers.

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
| **Swing Toolkit** | Production-ready | Verified | 3 institutional scanners, 8-factor checklist, 15m ORB volume gate, candidate filtering toolbar, async `YFinanceFetcher.fetch_history` with direct v8 chart fallback and 5-min TTL cache, live session volume normalization, and 45s cancellation. |
| **Real-Time Data Feeds**| Production-ready | Verified | TradingView-ta with bounded TTL caching & yfinance fallback. Defensive Title/lowercase casing. |
| **Paper Trading Daemon**| Production-ready | Verified | Autonomous 1-hour scan loop, Kelly sizing, MTM drawdown lock, 4-leg condor exit pricing, and process-safe tempfile writes. |
| **Unified Paper Matching Engine**| Production-ready | Verified | High-fidelity simulated matching engine (`api/broker_adapter.py`) with multi-tick Stop-Loss Limit continuation, complete order history audit logging, order cancellation, and strict input validation. |
| **Risk Engine** | Production-ready | Verified | 2% risk cap, 1.5:1 min R:R, ATR stops, Greek delta trailing stop ratchets, ruin probability. |
| **Options Engine** | Production-ready | Verified | Black-Scholes Greeks (Delta, Gamma, Theta, Vega, Rho across all tick/chart endpoints), dynamic DTE per index, dynamic India VIX IV, Newton-Raphson + Brent numerical IV solver, intrinsic value expiry settlement, long CE/PE, directional short CE/PE, Bull Put / Bear Call credit spreads, 4-leg defined-risk Iron Condors, SPAN margin gating, and positive theta decay notation. |
| **Option Selling & Spreads** | Production-ready | Verified | Automated directional short option selection, credit spreads, 4-leg Iron Condors, SPAN/exposure margin checks, analytical breakeven exit pricing, and interactive payoff curve generation via `/option-strategy-payoff`. |
| **Drawdown Circuit Breakers** | Production-ready | Verified | Normalized 2% daily capital loss gate, 24h cooldown after 3 losses, disk-persisted state, 100% drawdown bankrupt halt. |
| **Multi-Agent Consensus** | Production-ready | Verified | Synthesizes Tech, Deriv, Fund, Sent agents with live PCR/Max Pain/GEX context, Bull vs Bear debate, tie-breakers, and CRO gating. |
| **RL Contextual Bandit**| Production-ready | Verified | Thompson Sampling with R-multiple reward scaling, prior discounting & MAB execution tuning. |
| **Replay Engine** | Feature-complete | Verified | Next-bar open execution, STT friction, isolated weights, flat Sharpe denominator guard. |
| **Continuous Trainer** | Production-ready | Verified | SGDClassifier online partial_fit, 24/7 offline historical replay telemetry, heap-capped closed trades, and clean shutdown. |
| **Walk-Forward Backtest**| Production-ready | Verified | Real-world friction (0.1%), label-safe test window isolation, math finite bounds, zero return variance guard. |
| **F&O Friction Model** | Production-ready | Verified | Statutory SEBI STT (0.1% opt sell, 0.02% fut sell), ₹20 brokerage, GST 18%, Stamp Duty, 4-leg spread friction, 8-order Iron Condor friction, and analytical breakeven gating. |
| **Intraday MIS Square-Off** | Production-ready | Verified | Enforced 15:15 IST automated square-off on open intraday trades in both paper and live trading loops, eliminating RMS broker penalty fees. |
| **API Authentication & Rate Limiting** | Production-ready | Verified | Fail-closed production default, route-template grouped rate limits preventing path parameter bypasses, validated XFF client IPs pinned to loopback/configured proxies, and timing-safe key comparison. |
| **Public APIs (Frankfurter & RSS)** | Production-ready | Verified | Keyless ECB USD/INR rates + Indian Market RSS financial sentiment feed with strict port-443 SSRF defense, allowed redirect host enforcement (`api.frankfurter.app`, `api.frankfurter.dev`), 0.0.0.0 rejection, 5MB pre-parse XML caps, and XML entity defenses. |
| **Unified Config & File Concurrency** | Production-ready | Verified | Re-entrant RLock with retry-safe atomic replacement across training, dashboard, strategy store, and swing watchlist to prevent Windows file-lock contention. |
| **SmartAPI Broker** | Feature-complete | Verified | Angel One SmartAPI RFC 6238 TOTP auth + SEBI Algo-ID tagged execution with fail-closed `broker_mode == 'live'` assertion and input sanitization. |
| **Trade Dossier & History** | Production-ready | Verified | Full 360° trade specs modal (6 Greeks with Delta, Theta, Gamma, Vega, Rho, IV and positive Theta, SL/TP, trailing ratchet, range breakevens, 4-leg condor wing ribbon, AI conf, setups) + closed trade history table with ARIA dialog & focus trap. |
| **Active Frontend SPA** | Production-ready | Verified | 8 functional pages, 0 Oxlint warnings, 0 TypeScript errors, Vite production build in 2.75s, 6 Greeks, interactive 4-leg condor wing ribbon, range breakevens, credit spread builder, positive theta badges, localized `<ErrorBoundary compact>` wrappers, and mobile-responsive tables. |
| **Live Broker Execution**| Feature-complete | Fails Closed | Live execution engine with FO ticker matching, position deduplication, BFO/NFO routing, Drawdown Circuit Breaker, reversed broker exit orders (`BUY` to cover shorts), TradeContext DB persistence, 15:15 IST MIS square-off, and consensus gating; fails closed in dev mode. |
