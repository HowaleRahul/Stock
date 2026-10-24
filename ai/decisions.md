# Architectural & Technical Decisions Log

This document records the major architectural, structural, and design decisions made throughout the lifecycle of the **Personal AI-Assisted Trading System (Signal Desk)**. Each entry documents the rationale, current implementation, trade-offs, and verification status based directly on codebase evidence.

---

### Decision 1: TimescaleDB Hypertables with Composite Primary Keys
- **Date**: Phase 0 & 1 (July 2026; commit `fdd1d2c`)
- **Decision**: Partition high-volume time-series data (`ohlcv_bars`, `news_headlines`) as TimescaleDB hypertables partitioned along the `time` dimension, enforcing composite primary keys `(time, symbol_id, timeframe)` and `(time, url)`.
- **Why it appears to have been made**: In high-frequency and multi-asset algorithmic systems, standard PostgreSQL relational tables suffer query latency degradation and indexing bloat as data volumes scale. TimescaleDB chunks time-series intervals automatically, optimizing time-range queries.
- **Current implementation**: Defined in `models/models.py` (`OHLCVBar`, `NewsHeadline`) and configured in `models/init_db.py` via `SELECT create_hypertable('ohlcv_bars', 'time', if_not_exists => TRUE);`.
- **Files/components affected**: `models/models.py`, `models/init_db.py`, `data/service.py`, `Dockerfile.postgres-local`, `Dockerfile.timescaledb`.
- **Known trade-offs**: TimescaleDB requires the partition column (`time`) to be part of any unique or primary key constraint, preventing simple auto-increment integer primary keys and necessitating composite keys.
- **Evidence/source in the project**: `models/models.py` lines 30–84; `models/init_db.py` lines 42–63.
- **Reason status**: **Verified** (documented in comments and model definitions).

---

### Decision 2: Asynchronous Database Access with Connection Pool Disposal
- **Date**: Phase 0 (July 2026; commit `3028e51`)
- **Decision**: Use SQLAlchemy 2.0 async engine (`postgresql+asyncpg://`) with explicit connection pool cleanup on shutdown and between tests.
- **Why it appears to have been made**: FastAPI is natively asynchronous. Blocking database calls under synchronous drivers (like `psycopg2`) stall the uvicorn event loop during concurrent requests.
- **Current implementation**: `create_async_engine` initialized in `api/db.py` with `pool_size=20`, `max_overflow=20`, `pool_pre_ping=True`. Test teardown hook in `conftest.py` disposes the engine between tests to avoid asyncpg socket leaks across Windows `ProactorEventLoop` boundaries.
- **Files/components affected**: `api/db.py`, `api/main.py`, `conftest.py`, `data/service.py`.
- **Known trade-offs**: Async SQLAlchemy requires `greenlet` support, async context managers (`async with`), and cannot execute lazy relation loading synchronously.
- **Evidence/source in the project**: `api/db.py` lines 16–31; `conftest.py` lines 6–15.
- **Reason status**: **Verified** (explicitly explained in `conftest.py` docstrings).

---

### Decision 3: Input Sanitization and Path Parameter Normalization
- **Date**: Phase 1 Hardening (July 2026; commits `0934957` through `7701cd3`)
- **Decision**: Sanitize all incoming tickers, timeframes, and text inputs against NUL bytes (`\x00`), character lengths, and invalid formats before database queries or external API calls.
- **Why it appears to have been made**: Security and adversarial SDET testing revealed risks of NUL byte injection in PostgreSQL C-based drivers, as well as unhandled crashes when users passed lowercase or malformed ticker symbols.
- **Current implementation**: `DataCleaner.sanitize_text` in `data/cleaner.py`, `_clean_ticker_param` in `api/router.py`, and Pydantic field validators in `api/schemas.py`.
- **Files/components affected**: `data/cleaner.py`, `api/router.py`, `api/schemas.py`.
- **Known trade-offs**: Adds minor CPU validation overhead on every request.
- **Evidence/source in the project**: Commits `3575c96`, `d4616c3`; `api/router.py` lines 73–84.
- **Reason status**: **Verified** (commit history and unit tests in `tests/test_phase1_data.py`).

---

### Decision 4: Contract Standardization to Five Core Setups in `SetupEngine`
- **Date**: Production Review Pass 1 (July 2026; commit `4640f28`, `REVIEW_LOG.md` Pass 1)
- **Decision**: Lock the default `SetupEngine` evaluation contract to five deterministic technical setups (`MACrossover`, `RSI`, `MACD`, `BollingerBands`, `Breakout`), separating experimental setups and regime detection.
- **Why it appears to have been made**: Experimental setups were returning unstable signals or crashing on missing optional libraries (e.g. sentiment, options, fundamentals without network access). Locking the core engine ensured deterministic behavior across all callers.
- **Current implementation**: `SetupEngine.__init__` instantiates the five core setups. It provides two methods: `evaluate_all(df)` returning `List[SetupSignal]`, and `evaluate_with_regime(df)` returning `tuple[dict, List[SetupSignal]]`.
- **Files/components affected**: `setups/engine.py`, `setups/base.py`, `api/router.py`, `paper_trader.py`, `live_trader.py`, `backtest/run.py`.
- **Known trade-offs**: Additional setups (`OptionsSetup`, `SentimentSetup`, `MomentumMastersSetup`) must be invoked independently or via specialized routers rather than automatically bundled in `SetupEngine`.
- **Evidence/source in the project**: `REVIEW_LOG.md` lines 5–10; `setups/engine.py` lines 26–36, 94–102.
- **Reason status**: **Verified** (documented in `REVIEW_LOG.md`).

---

### Decision 5: Canonical Multi-Asset Policy with Fail-Closed Classification
- **Date**: Multi-Asset Hardening (August 2026; commits `1f1bd4b`, `f8dcf94`)
- **Decision**: Unify asset-class determination in `ml/assets.py` across `IN_EQUITY`, `US_EQUITY`, and `CRYPTO`. Forbid loose heuristics (like substring checking) and fail closed on unrecognized tickers.
- **Why it appears to have been made**: Different components previously used conflicting heuristics to determine asset class, causing inconsistent feature generation, macro data lookups, and triple-barrier label horizons.
- **Current implementation**: `classify_ticker` and `normalize_ticker` in `ml/assets.py`. `TARGETS` and `US_EQUITY_SYMBOLS` explicitly define supported symbols. Tickers with unknown patterns raise `ValueError`.
- **Files/components affected**: `ml/assets.py`, `ml/features.py`, `ml/ensemble.py`, `ml/continuous_trainer.py`, `tests/test_multi_asset.py`.
- **Known trade-offs**: New symbols cannot be added dynamically without updating `ml/assets.py`.
- **Evidence/source in the project**: `ml/assets.py` lines 1–60; `REVIEW_LOG.md` lines 33–53.
- **Reason status**: **Verified** (explicitly stated in `ml/assets.py` header).

---

### Decision 6: Fail-Closed Broker Scaffolding with SEBI Algo-ID Tagging
- **Date**: Phase 9 Scaffolding (August 2026; commit `f8dcf94`)
- **Decision**: Create a rigid `BrokerAPI` interface that checks static public IP against `WHITELISTED_IP`, validates orders, mandates `EXCHANGE_ALGO_ID` tagging per SEBI 2026 retail regulations, and fails closed (`RuntimeError`) if real broker execution is attempted.
- **Why it appears to have been made**: To ensure real funds can never be traded accidentally from a development or staging environment without formal compliance, exchange-approved algo IDs, and verified static IP binding.
- **Current implementation**: `api/broker.py`. `place_order` verifies order parameters, validates `NSE`/`NFO` routing, and raises `RuntimeError("Live order submission is unavailable until a real broker adapter is configured")`.
- **Files/components affected**: `api/broker.py`, `live_trader.py`.
- **Known trade-offs**: Real live trading cannot proceed until an external broker SDK (e.g., Kite Connect, Upstox API) is fully integrated and approved.
- **Evidence/source in the project**: `api/broker.py` lines 1–131; `REVIEW_LOG.md` lines 49–52.
- **Reason status**: **Verified** (documented in `api/broker.py`).

---

### Decision 7: Two-Tier Paper Trading Persistence (Database First + Local JSON Fallback)
- **Date**: Phase 8 & 11 Hardening (August – October 2026; commits `c78a60b`, `702e041`)
- **Decision**: Persist paper trading accounts, open trades, and audit events to PostgreSQL (`accounts`, `trades`, `trade_context`, `journal_events`), but retain bidirectional fallbacks to local files (`paper_account.json`, `paper_trades.json`, `logs/trade_journal.jsonl`).
- **Why it appears to have been made**: Enables the system to operate autonomously in offline development or edge environments where the Docker container is stopped or restarting, while ensuring durable ACID transactions when the database is online.
- **Current implementation**: `papertrade/persistence.py` handles atomic DB writes; `api/dashboard_router.py` queries database tables first and falls back to JSON files if the database connection fails.
- **Files/components affected**: `papertrade/persistence.py`, `api/dashboard_router.py`, `paper_trader.py`, `scripts/migrate_json_to_db.py`.
- **Known trade-offs**: Dual persistence logic introduces potential state divergence if files and database are updated out of sync.
- **Evidence/source in the project**: `REVIEW_LOG.md` lines 122–128, 206–207; `api/dashboard_router.py` lines 61–125.
- **Reason status**: **Verified** (explicitly described in `REVIEW_LOG.md`).

---

### Decision 8: Execution at Next Bar's Open in Replay Engine
- **Date**: Pass 11 Hardening (October 2026; commit `9c52f40`, `REVIEW_LOG.md` Pass 11)
- **Decision**: During historical RL self-play replay, execute orders at the `open` price of the bar *following* the signal bar, rather than at the `close` of the signal bar.
- **Why it appears to have been made**: Executing at the close of the signal-generating bar creates lookahead bias and unrealistic fills, as in real market conditions a strategy cannot evaluate bar close and fill simultaneously on the same tick.
- **Current implementation**: `ml/replay_engine.py` caches pending orders and fills them upon receiving the next bar's open price.
- **Files/components affected**: `ml/replay_engine.py`, `tests/test_replay_isolation.py`.
- **Known trade-offs**: Slightly complicates the simulation state machine by requiring pending order queues.
- **Evidence/source in the project**: `REVIEW_LOG.md` lines 205, 218; `ml/replay_engine.py`.
- **Reason status**: **Verified** (documented in `REVIEW_LOG.md` and test suite).

---

### Decision 9: Contextual Bandit with Thompson Sampling for Online Reweighting
- **Date**: Phase 7 / RL Self-Play (August 2026; commit `f020a55`, `9c52f40`)
- **Decision**: Implement setup confidence adaptation using a Contextual Bandit (`Beta` prior with Thompson Sampling) rather than full deep reinforcement learning.
- **Why it appears to have been made**: Individual trade decisions are episodic rather than continuous state-action trajectories. Thompson Sampling naturally balances exploration of under-tested setups with exploitation of proven setups, without requiring large neural network training pipelines.
- **Current implementation**: `ml/reinforcement_learner.py` maintains alpha/beta parameters per `(setup, regime)` pair, persisted in `ml/models/setup_weights.json`.
- **Files/components affected**: `ml/reinforcement_learner.py`, `ml/journal_analyzer.py`, `paper_trader.py`, `ml/replay_engine.py`.
- **Known trade-offs**: Assumes setups are independent; does not model complex combinatorial interactions between simultaneous setups.
- **Evidence/source in the project**: `ml/reinforcement_learner.py` lines 1–15; `iterate.txt` lines 182–200.
- **Reason status**: **Verified** (documented in module docstring).

---

### Decision 10: Migration from Vanilla JS to React 19 + TypeScript SPA
- **Date**: August 2026 (commits `720fed4`, `3c22c28`)
- **Decision**: Transition the frontend from static HTML/JS (`frontend_legacy/`) and a prototype React app (`web/`) to a modern React 19 + TypeScript + Vite SPA (`frontend/`).
- **Why it appears to have been made**: As dashboard requirements expanded to include interactive charts, real-time analytics, backtest visualizers, and strategy builders, vanilla JS became difficult to maintain and lacked compile-time type safety.
- **Current implementation**: Full SPA in `frontend/src/` with 8 distinct pages, dynamic route splitting (`lazy`), and shared layout shell (`App.tsx`).
- **Files/components affected**: `frontend/`, `frontend_legacy/`, `web/`, `api/main.py`.
- **Known trade-offs**: Increased build complexity, higher bundle sizes (React vendor ~234 kB, charts ~166 kB). (Legacy directories were subsequently removed in Decision 13).
- **Evidence/source in the project**: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/src/App.tsx`.
- **Reason status**: **Inferred** based on git commit history and initial presence of `frontend_legacy` and `web`.

---

### Decision 13: Repository Consolidation and Removal of Legacy Frontends
- **Date**: Audit Remediation (October 2026; commit `31382e0`, `REVIEW_LOG.md` Pass 13)
- **Decision**: Completely delete deprecated, unreferenced legacy frontends `frontend_legacy/` (vanilla HTML/JS) and `web/` (outdated React prototype), leaving `frontend/` as the sole UI surface, while strictly preserving `iterate.txt`.
- **Why it appears to have been made**: Having three frontends caused developer ambiguity, search noise, and review overhead. Only `frontend/` is mounted by FastAPI in `api/main.py` and built by `start.py`.
- **Current implementation**: Only `frontend/` remains in the root.
- **Files/components affected**: `frontend_legacy/`, `web/`, `REVIEW_LOG.md`, `ai/`.
- **Known trade-offs**: None; legacy frontends were non-functional and unreferenced.
- **Evidence/source in the project**: Commit `31382e0`; `REVIEW_LOG.md` Pass 13; `ai/audits/03-repository-consolidation.md`.
- **Reason status**: **Verified** (documented in audit and commit log).

---

### Decision 14: Dynamic Socket-Based Test Fixture Hermeticity
- **Date**: Audit Remediation (October 2026; commit `31382e0`, `REVIEW_LOG.md` Pass 13)
- **Decision**: Register `@pytest.mark.database` in `pytest.ini` and implement a dynamic TCP socket probe `is_database_online()` in `conftest.py` with an automated `pytest_collection_modifyitems` hook to segregate database integration tests.
- **Why it appears to have been made**: 17 database integration tests previously failed with connection errors when running in offline development or containerless CI/CD environments.
- **Current implementation**: `conftest.py` checks TCP connectivity to `127.0.0.1:5432` on collection. Running `pytest -m "not database"` executes 131 tests with 100% pass rate in complete offline isolation. When the database is available, all 148 tests execute automatically.
- **Files/components affected**: `conftest.py`, `pytest.ini`, `tests/`, `ai/audits/04-test-fixture-hermeticity.md`.
- **Known trade-offs**: None; provides full flexibility between fast offline CI runs and complete end-to-end integration verification.
- **Evidence/source in the project**: Commit `31382e0`; `conftest.py` lines 14–46; `pytest.ini`.
- **Reason status**: **Verified** (documented in `conftest.py`).

---

### Decision 15: Unified ML Inference with Dynamic Indicator Extraction and Continuous Fallback
- **Date**: Audit Remediation (October 2026; commit `31382e0`, `REVIEW_LOG.md` Pass 13)
- **Decision**: Upgrade `EnsembleModel.predict()` to accept an optional `df: Optional[pd.DataFrame]` parameter, extract ATR/RSI/MACD indicators dynamically, provide `MACRO_NEUTRAL_DEFAULTS`, deploy fitted `StandardScaler` artifacts across all timeframes in `ml/registry/`, and automatically fall back to `ml/models/continuous_brain_bundle.pkl`.
- **Why it appears to have been made**: Previously, models trained on rich features fell back to simple unweighted heuristic voting during inference due to missing macro/options/volatility fields, disabling trained ML predictions in live/paper trading.
- **Current implementation**: `ml/ensemble.py` lines 86–168 extracts features dynamically, matches feature schemas with `StandardScaler`, and outputs active model probabilities and XAI driver attributions across `1d`, `1h`, `15m`, and `5m` timeframes.
- **Files/components affected**: `ml/ensemble.py`, `ml/registry/`, `api/router.py`, `paper_trader.py`, `live_trader.py`, `ml/replay_engine.py`.
- **Known trade-offs**: Requires callers to pass the active OHLCV DataFrame into `ensemble.predict()`.
- **Evidence/source in the project**: Commit `31382e0`; `ml/ensemble.py` lines 86–175; `REVIEW_LOG.md` Pass 13.
- **Reason status**: **Verified** (verified by unit tests and live prediction endpoints).

---

### Decision 11: Production-First Default Authentication and Header-Based API Key
- **Date**: Pass 12 Hardening (October 2026; commit `702e041`)
- **Decision**: Default `ENVIRONMENT` to `"production"` across configuration; require `X-API-Key` or `Authorization: Bearer` for all API requests; prohibit query-parameter API keys; permit keyless access only if explicitly set to `development` on a loopback host.
- **Why it appears to have been made**: Prevents deployments exposed to the internet or LAN from inadvertently running without authentication due to implicit development defaults. URL query parameters were removed to prevent credential leakage in proxy/browser logs.
- **Current implementation**: `api/config.py` sets `environment: str = Field(default="production")`; `api/auth.py` validates `_configured_api_key()` and `_allows_keyless_development()`; `frontend/src/main.tsx` strips legacy query parameters on boot.
- **Files/components affected**: `api/config.py`, `api/auth.py`, `api/main.py`, `frontend/src/main.tsx`, `frontend/src/components/SettingsModal.tsx`.
- **Known trade-offs**: Developers running outside Docker or non-loopback IPs must generate and configure an `API_KEY`.
- **Evidence/source in the project**: `REVIEW_LOG.md` lines 240–246; `api/auth.py` lines 48–110.
- **Reason status**: **Verified** (documented in `REVIEW_LOG.md` Pass 12).

---

### Decision 12: Addition of Momentum Masters Swing Toolkit
- **Date**: October 2026 (commit `56a5733`)
- **Decision**: Implement a specialized Indian equities swing trading toolkit inspired by Mark Minervini / Momentum Masters methodology, including 3 scanners (Momentum, DWIB, ATH Contraction), an 8-factor checklist scoring engine, and a 15-minute Opening Range Breakout (ORB) engine.
- **Why it appears to have been made**: To expand trading coverage beyond index intraday derivatives (`NIFTY`/`BANKNIFTY`) into multiday positional swing setups in high-momentum liquid Indian stocks.
- **Current implementation**: `setups/swing_toolkit/` directory with `universe.py`, `scanners.py`, `checklist.py`, `orb_entry.py`, and `toolkit.py`. Exposed via `api/swing_router.py` and UI page `frontend/src/pages/SwingToolkit.tsx`.
- **Files/components affected**: `setups/swing_toolkit/`, `setups/swing_toolkit_setup.py`, `api/swing_router.py`, `frontend/src/pages/SwingToolkit.tsx`, `paper_trader.py`.
- **Known trade-offs**: Introduces additional external Yahoo Finance requests when scanning the swing universe (50+ tickers).
- **Evidence/source in the project**: Commit `56a5733`; `setups/swing_toolkit/` source code.
- **Reason status**: **Verified** (documented in commit `56a5733` and docstrings).

---

### Decision 16: Complete Specialization in Indian Stock Market Futures & Options (F&O) and SENSEX Index Support
- **Date**: October 2026 (Pass 14 F&O Transformation)
- **Decision**: Transform the entire trading system to specialize strictly in Futures & Options (F&O) on the Indian Stock Market. Eliminate all cash/equity execution paths, foreign markets, and crypto. Add native BSE SENSEX (`^BSESN`) index alongside NIFTY, BANKNIFTY, FINNIFTY, and MIDCPNIFTY. Configure dual scalp (`5m`, `15m`) and swing (`1h`, `1d`) timeframes. Reroute all paper trading through `DerivativeEngine` with option Greeks (Delta, Theta, Gamma, IV) and exact exchange lot sizes. Reset database tables and local paper trading state from scratch. Retrain all ML stacking classifiers from scratch on historical F&O index data. Update all frontend pages (`Dashboard`, `TrainingUI`, `Portfolio`, `BacktestUI`, `OptionChartViewer`) to feature BSE SENSEX, F&O lot sizing, dynamic futures margin calculation, and contract indicators.
- **Why it appears to have been made**: As requested by user, the workstation is dedicated solely to Indian stock market F&O trading (scalping and swinging), leveraging derivatives with leverage and risk management rather than equity delivery.
- **Current implementation**:
  - `ml/assets.py`: Restricted `ASSET_CLASSES` to `("IN_INDEX_FO",)`. Defined `FO_UNDERLYINGS`, `LOT_SIZES` (NIFTY 25, BANKNIFTY 15, SENSEX 10, FINNIFTY 25, MIDCPNIFTY 50), `STRIKE_INTERVALS` (SENSEX/BANKNIFTY 100, NIFTY/FINNIFTY 50, MIDCPNIFTY 25), `FUTURES_MARGIN_RATES`, `EXPIRY_DAYS` (SENSEX Friday day 4).
  - `paper_trader.py` & `live_trader.py`: Direct execution through `DerivativeEngine.generate_derivative_plan()`. Option buying (CE/PE) for micro/small budgets and linear Index Futures for growth tiers.
  - `setups/engine.py`: Re-calibrated regime modulation for F&O leverage, gating long calls in crash regimes and prioritizing mean reversion in choppy regimes.
  - `models/init_db.py`: Seeded 11 F&O symbols (`NIFTY`, `BANKNIFTY`, `SENSEX`, `FINNIFTY`, `MIDCPNIFTY`, `^NSEI`, `^NSEBANK`, `^BSESN`).
  - `scripts/reset_fo_database.py`: Clean recreation of schemas, TimescaleDB hypertables, fresh paper account with ₹1,00,000, and reset of local trade logs.
  - `scripts/train_fo_models.py`: Fresh ML training across scalp (`5m`, `15m`) and swing (`1h`, `1d`) timeframes for all F&O indices.
  - Frontend: `Dashboard.tsx`, `BacktestUI.tsx`, `Portfolio.tsx`, `OptionChartViewer.tsx`, `TrainingUI.tsx`, and `tradingViewUtils.ts` updated with BSE SENSEX support, exchange indicators (`BSE F&O` / `NSE F&O`), F&O contract labels, and margin advisories.
- **Files/components affected**: `ml/assets.py`, `ml/options_engine.py`, `ml/continuous_trainer.py`, `paper_trader.py`, `live_trader.py`, `config.json`, `.env.example`, `models/init_db.py`, `api/catalog.py`, `api/market_router.py`, `api/training_router.py`, `api/dashboard_router.py`, `api/backtest_router.py`, `frontend/src/pages/Dashboard.tsx`, `frontend/src/pages/TrainingUI.tsx`, `frontend/src/pages/Portfolio.tsx`, `frontend/src/pages/BacktestUI.tsx`, `frontend/src/components/OptionChartViewer.tsx`, `frontend/src/components/tradingViewUtils.ts`.
- **Known trade-offs**: Cash equities and foreign markets are disallowed; attempts to trade non-F&O assets fail closed.
- **Evidence/source in the project**: User prompt requirement; `ml/assets.py`, `config.json`, `REVIEW_LOG.md` Pass 14.
- **Reason status**: **Verified**.

---

### Decision 17: Public APIs Integration — Frankfurter Currency API, Indian Market RSS News Sentiment, and Angel One SmartAPI Broker

- **What was decided**: Integrate high-value, production-grade public APIs identified from the public-apis repository that specifically empower Indian F&O trading:
  1. **Frankfurter Currency API (`https://api.frankfurter.app/`)**: High-speed, keyless, zero-rate-limit ECB reference rate API for live and historical USD/INR exchange rates, serving as an instant fallback when Yahoo Finance `INR=X` is delayed or blocked.
  2. **Indian Market Financial News & Sentiment Feed**: Open RSS ingestion from Indian financial press (Google News IN / Moneycontrol / NDTV Profit / Economic Times) combined with domain-tuned VADER financial sentiment scoring to classify index sentiment (BULLISH / BEARISH / NEUTRAL) and aggregate bull/bear headline ratios.
  3. **Angel One SmartAPI Broker (`smartapi.angelbroking.com`)**: Implementation of `SmartAPIBroker` supporting RFC 6238 automated TOTP 2FA, NFO & BFO (NSE & BSE SENSEX) segment execution, static IP verification, and SEBI Algo-ID order tagging (`tag=self.algo_id`).
- **Why it appears to have been made**: As requested by user to leverage relevant APIs from the official `public-apis` directory for the Indian F&O workstation. Yahoo Finance fails to deliver news for Indian indices (`^NSEI`, `^BSESN`), making the Indian financial RSS feed essential. Live USD/INR is a critical macro feature in `ml/features.py`, and SmartAPI is the premier Indian broker API listed in `public-apis` supporting F&O derivatives.
- **Current implementation**:
  - `data/fx_fetcher.py`: `FrankfurterFXFetcher` supporting `get_latest_usdinr_sync()` and `get_historical_usdinr_series_sync(days=...)`.
  - `ml/features.py`: Integrated `FrankfurterFXFetcher` as an automatic keyless fallback in `enrich_with_macro_and_options()`.
  - `data/news_fetcher.py`: Added `calculate_sentiment()`, `_fetch_indian_rss_news_sync()`, and `get_sentiment_summary()` with financial market VADER weights (`crash: -3.5`, `surge: +2.5`, `rally: +2.5`).
  - `api/market_router.py`: Exposed `GET /api/v1/market/news-sentiment/{ticker}`.
  - `api/broker.py`: Implemented `SmartAPIBroker` inheriting from `BrokerAPI` with standard library RFC 6238 TOTP computation and SEBI algo tagging.
  - `frontend/src/pages/Dashboard.tsx`: Integrated real-time "Market News Pulse & Sentiment Engine" card displaying overall bias, bull/bear count, and top headlines.
  - `tests/test_public_apis.py`: 8 comprehensive unit and integration tests.
- **Files/components affected**: `data/fx_fetcher.py`, `data/news_fetcher.py`, `ml/features.py`, `api/market_router.py`, `api/broker.py`, `frontend/src/pages/Dashboard.tsx`, `tests/test_public_apis.py`.
- **Known trade-offs**: Live broker execution still requires user credentials and static IP; fails closed in mock mode.
- **Evidence/source in the project**: User prompt (`public-apis`), `tests/test_public_apis.py`, `REVIEW_LOG.md` Pass 15.
- **Reason status**: **Verified**.

---

### Decision 18: Safe Pandas Index Schema Comparison in Continuous Trainer

- **What was decided**: Eliminate boolean truth-value evaluation on `pandas.Index` objects inside `_reset_if_feature_schema_changed()` in `ml/continuous_trainer.py`. Standardize feature name resolution using `current_names = list(feature_names) if feature_names is not None else list(X.columns)`.
- **Why it appears to have been made**: In Python, `feature_names or X.columns` evaluates `bool(feature_names)`. If `feature_names` is a `pd.Index` (e.g. `X.columns`), Pandas raises `ValueError: The truth value of a Index is ambiguous. Use a.empty, a.bool(), a.item(), a.any() or a.all()`. This caused historical training cycles to fail with a warning during offline replay and skip model checkpoints.
- **Current implementation**:
  - `ml/continuous_trainer.py`: Refactored `_reset_if_feature_schema_changed()` to check `if feature_names is not None` before converting to a list.
  - Aligned live training step to use `IN_INDEX_FO` asset class and resolve target index using `FO_UNDERLYINGS`.
  - `tests/test_multi_asset.py`: Added `test_continuous_trainer_schema_reset_pd_index_safety` testing identical schema, `feature_names=None`, and schema modifications without raising Index exceptions.
- **Files/components affected**: `ml/continuous_trainer.py`, `tests/test_multi_asset.py`.
- **Known trade-offs**: None.
- **Evidence/source in the project**: Live runtime warning logged during training loop; regression test in `tests/test_multi_asset.py`; `REVIEW_LOG.md` Pass 16.
- **Reason status**: **Verified**.

---

### Decision 19: Immediate / Zero-Latency Training Termination (<150ms)

- **What was decided**: Ensure that clicking "Stop Trading" halts continuous training immediately (<150ms) rather than waiting 15-45 seconds for long feature extraction loops and sleep cycles to finish.
- **Why it appears to have been made**: As reported by user: "STOP TRAINING SHOULD KILL THE TRAINING IMMEDIATELY WHY TAKING TAKE?". Previously:
  1. `generate_features_for_ticker()` sequentially iterated through up to 5,000 bars calculating 5 technical setups without checking `stop_event`, locking the thread in a CPU loop for 20-45s.
  2. Sleep loops polled `time.sleep(1)` in fixed 15s/30s ranges.
  3. `POST /api/v1/training/stop` set `stop_event` but left `is_training=True` until thread termination, causing immediate status polling from the UI to report `is_training: true` and keep the UI in running state.
- **Current implementation**:
  - `ml/continuous_trainer.py`:
    - Propagated `stop_event` into `generate_features_for_ticker()`; checks `stop_event.is_set()` before download, during feature calculation, and every iteration of the bar setup loop, aborting instantly.
    - Replaced busy-sleep polling with native `stop_event.wait(timeout=...)` which awakens in <1ms upon `stop_event.set()`.
  - `api/training_router.py`:
    - Updated `stop_training` to immediately set `is_training = False`, signal `stop_event`, and cooperatively join `training_thread` for up to 1.5s via `asyncio.to_thread`.
    - In `get_status()`, if `stop_event.is_set()`, returns `is_training: False` and `mode: "IDLE"`.
  - `frontend/src/pages/TrainingUI.tsx`:
    - Optimistically updates `isTraining = false` and `trainingMode = 'IDLE'` upon clicking Stop for instant visual UI feedback.
- **Files/components affected**: `ml/continuous_trainer.py`, `api/training_router.py`, `frontend/src/pages/TrainingUI.tsx`.
- **Known trade-offs**: In-flight feature batch for that cycle is discarded cleanly without corrupting model state.
- **Evidence/source in the project**: User prompt requirement; verified stop benchmark (thread terminated in 0.140s); `REVIEW_LOG.md` Pass 17.
- **Reason status**: **Verified**.

---

### Decision 20: Comprehensive Trade Specification Dossier, Closed Trades Serialization & 24/7 Replay Telemetry

- **What was decided**:
  1. **Complete Trade Specification Dossier (`TradeDossierModal`)**: Surface every single trade metric and specification in an interactive modal for both active positions and closed trades:
     - Contract identifier, Underlying index, Instrument type (Index Options CE/PE vs Index Futures), Moneyness (ATM/ITM/OTM), Strike price, and Expiry date.
     - Lots, Contract quantity, Entry price, Current/Exit price, Margin/Premium deployed, Net MTM / Realized PnL, Return %.
     - Full Risk Architecture: Hard Stop Loss, Take Profit, Trailing Stop Ratchet, Distance to SL, Distance to TP, Risk/Reward Ratio.
     - Option Greeks: Delta ($\Delta$), Gamma ($\Gamma$), Theta ($\Theta$ per day), Implied Volatility ($IV$ annualized).
     - Execution Context: Spot price at entry, Regime (TRENDING_BULL, TRENDING_BEAR, SIDEWAYS_CHOP), AI Ensemble Confidence %, and Fired Technical Setups list with interactive chart inspection triggers.
  2. **Closed Trades Serialization & History Table**:
     - Expose the last 50 closed derivative trades in `ml/live_market_learner.py:get_portfolio_state()` under `"closed_trades"`.
     - Render a dedicated Closed Trades & Reinforcement Learning table in `TrainingUI.tsx` displaying Entry/Exit timestamp, Exit Reason (e.g. TRAILING_STOP_HIT, TARGET_REACHED, ATR_STOP_HIT), Duration, and a one-click "Specs" button.
  3. **24/7 Offline Replay & Path-Dependent Telemetry**:
     - Surface simulation metrics (`_replay_telemetry` in `ml/continuous_trainer.py` and `TrainingStatus` schema in `api/training_router.py`) tracking target index, timeframe, total simulated trades, win count, loss count, timeout count, win rate %, and dynamic ATR stops.
     - Render an Offline Historical Replay card in the UI providing real-time feedback during closed market hours.
     - Wire `_live_learner.execute_live_cycle()` into the offline historical loop using recent bar data to maintain active virtual portfolio management around the clock.
- **Why it appears to have been made**: As requested by user: "EACH TRADE TAKING ITS SPECIFICATION, DETAILS EVERYTHING SHOULD BE SHOWN. UI ISSUES ALSO THERE FIX THEM". Previously closed trade records were retained in Python memory but excluded from API responses, leaving the Closed Trades count at 0 in the UI and obscuring the individual trade executions from offline replay simulations.
- **Files/components affected**: `ml/live_market_learner.py`, `ml/continuous_trainer.py`, `api/training_router.py`, `frontend/src/pages/TrainingUI.tsx`.
- **Known trade-offs**: Additional serialization payload for 50 closed trades is minimal (<25KB) and stays within 1-second UI polling intervals.
- **Evidence/source in the project**: User prompt requirement; frontend build verification; `REVIEW_LOG.md` Pass 18.
- **Reason status**: **Verified**.

---

### Decision 21: Full Process Isolation, Multi-Directory Auto-Reloading, and Bulletproof Schema Guard for Continuous Training

- **What was decided**:
  1. **Bulletproof Schema Comparison Guard (`_reset_if_feature_schema_changed`)**:
     - Wrapped the schema comparison in `ml/continuous_trainer.py` inside an exception-safe try/except block.
     - Normalized feature names via `[str(c) for c in list(feature_names)]` and `list(persisted_names) == current_names`.
     - In case of any schema evaluation irregularity, automatically and safely resets to a fresh `SGDClassifier` and `StandardScaler` without throwing unhandled exceptions to the replay loop.
  2. **Multi-Directory Reloader Configuration**:
     - Configured Uvicorn launch flags in `start.py` to watch all key application directories (`--reload-dir api --reload-dir ml --reload-dir data --reload-dir setups`).
     - Previously, Uvicorn watched only the default working directory root or `api/`, leaving long-running background threads in the worker process executing stale bytecode from prior imports.
  3. **Full Traceback Logging**:
     - Added `logger.error("Historical training error: %s", traceback.format_exc())` to `ml/continuous_trainer.py` for comprehensive visibility into any training runtime issues.
- **Why it appears to have been made**: As reported by user: `[WARNING] Historical training error: The truth value of a Index is ambiguous. Use a.empty, a.bool(), a.item(), a.any() or a.all(). STILL`. Investigation revealed a stale Uvicorn worker process (PID 14384) started at 00:29:50 was still executing an old in-memory thread that had loaded the unpatched `continuous_trainer.py`. Terminating the stale worker and running with multi-directory reloading completely eliminated the error.
- **Files/components affected**: `ml/continuous_trainer.py`, `start.py`.
- **Known trade-offs**: None.
- **Evidence/source in the project**: User prompt report; live execution verification showing Cycle 1 simulating 1,133 trades and transitioning to Cycle 2 with 0 errors; `REVIEW_LOG.md` Pass 19.
- **Reason status**: **Verified**.

---

### Decision 22: Algorithmic Repository Synthesis, Multi-Agent Consensus, Risk-Adjusted RL Reward Shaping, and Drawdown Circuit Breakers

- **What was decided**:
  1. **Algorithmic Trading Repository Synthesis**:
     - Audited and adapted concepts from 15 algorithmic trading repositories (`claude-trading-skills`, `TradingAgents`, `QuantDinger`, `jesse`, `fenix`, `uniBroker`, `nsepython`, `paper-trade-broker`, `Lean.Brokerages.Zerodha`, `StarApi-py`, `india-stocks-api`, `nse-api-package`, `Bharat-SM-Data`, `staskh/trading_skills`, `tick-stock-panel`).
  2. **Multi-Agent Consensus Architecture (`ml/multi_agent_consensus.py`)**:
     - Incorporated the multi-agent consensus workflow from `TauricResearch/TradingAgents`.
     - Synthesizes specialized insights from Technical, Derivatives, Fundamental, and Sentiment agents.
     - Adds adversarial Bull vs. Bear debate to remove confirmation bias, with mandatory Chief Risk Officer gating before trade execution.
  3. **Drawdown Circuit Breakers & Risk Gate (`ml/circuit_breaker.py`)**:
     - Incorporated strict capital preservation rules from `tradermonty/claude-trading-skills`.
     - Enforces a 2.0% daily realized loss ceiling and a mandatory 24-hour cooldown after 3 consecutive losses to halt revenge trading.
     - Integrated as a pre-scan gate in both `paper_trader.py` and `ml/live_market_learner.py`.
  4. **Post-Trade Reflection Memory (`ml/agent_reflection.py`)**:
     - Automatically generates structured institutional reflection lessons on completed trades across all exit reasons.
     - Persists lessons to `logs/agent_reflections.jsonl` for continuous AI journal analysis.
  5. **Risk-Adjusted Reward Shaping (R-multiples) & Prior Discounting (`ml/reinforcement_learner.py`)**:
     - Scaled Beta posterior step sizes by realized R-multiples ($R = |\text{pnl}| / \text{risk}$), clipping between 0.5 and 3.0.
     - Added `discount_priors()` to decay stale priors towards (1.0, 1.0) on regime shifts, re-enabling Thompson sampling exploration.
     - Added `ExecutionArmBandit` to adapt execution parameters (e.g. ATR trailing multipliers: 0.8x, 1.0x, 1.5x, 2.0x).
  6. **Live NSE Option Chain Scraper (`data/nse_feed.py`) & Dealer GEX (`ml/gex_engine.py`)**:
     - Integrated TLS fingerprint impersonation (`curl_cffi`) for resilient live option chain scraping.
     - Computes real-time Put-Call Ratio (PCR), Max-Pain strike, FII/DII institutional net flows, and dealer gamma flip levels.
- **Why it was made**: User requested a comprehensive upgrade of paper trading and reinforcement learning capabilities leveraging top trading repositories and institutional AI trading patterns.
- **Files/components affected**: `ml/circuit_breaker.py`, `ml/agent_reflection.py`, `ml/multi_agent_consensus.py`, `ml/reinforcement_learner.py`, `ml/gex_engine.py`, `data/nse_feed.py`, `api/broker_adapter.py`, `setups/vcp_setup.py`, `setups/piotroski_setup.py`, `paper_trader.py`, `ml/live_market_learner.py`, `tests/test_researched_modules.py`, `tests/test_rl_paper_enhancements.py`.
- **Known trade-offs**: None; all 176 existing and new unit/integration tests pass with 100% backward compatibility.
- **Evidence/source in the project**: Verified with 176 passing tests (`pytest -q`); `repository_evaluation_and_integration_report.md`.
- **Reason status**: **Verified**.

