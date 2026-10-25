# Known Issues, Risks & Technical Debt

This document catalogs all verified defects, technical debt, incomplete features, security risks, and architectural limitations discovered during comprehensive inspection of the **Personal AI-Assisted Trading System (Signal Desk)**.

> [!NOTE]
> Detailed deep-dive audits and remediation plans for the major architectural areas are available in the [`ai/audits/`](audits/README.md) suite:
> - [Audit 01: Feature Pipeline Alignment & ML Model Lifecycle](audits/01-feature-pipeline-alignment.md)
> - [Audit 02: Distributed Infrastructure & Multi-Worker Concurrency](audits/02-distributed-infrastructure.md)
> - [Audit 03: Repository Consolidation & Dead Code Elimination](audits/03-repository-consolidation.md)
> - [Audit 04: Test Fixture Hermeticity & Offline CI/CD Execution](audits/04-test-fixture-hermeticity.md)

---

### Issue 1: In-Memory Process-Local Rate Limiting (Single-Worker Limitation)
- **Severity**: Medium
- **Evidence**: `api/auth.py` lines 14–45:
  ```python
  _RATE_LOCK = threading.Lock()
  _RATE_LIMITS = TTLCache(maxsize=100000, ttl=60)
  ```
- **Affected Area**: `api/auth.py`
- **Current Behavior**: Rate limits are tracked inside the process memory of each individual Uvicorn worker process using a threading lock and `cachetools.TTLCache`.
- **Expected Behavior**: In a clustered or multi-worker production deployment (`uvicorn --workers N`), rate-limiting quotas should be centralized (e.g., via Redis) across all worker instances.
- **Possible Impact**: A client can bypass the 60 req/min quota by distributing requests across multiple workers. Additionally, worker process restarts immediately discard all accumulated rate limit counters.
- **Status**: Partially Addressed / In Progress (REDIS_URL configuration setting added to `api/config.py` in Pass 13)
- **Recommended Next Investigation/Fix**: Connect the Redis token-bucket adapter in `api/auth.py` when `REDIS_URL` is configured, falling back to local `TTLCache` in development.

---

### Issue 2: Feature Disconnect Between Batch Training and Ensemble Inference
- **Severity**: High
- **Evidence**: `ml/ensemble.py` lines 101–105 previously threw fallback voting when models trained with enriched indicators encountered missing features during inference.
- **Affected Area**: `ml/ensemble.py`, `ml/train.py`, `ml/features.py`, `api/router.py`, `paper_trader.py`, `live_trader.py`
- **Current Behavior**: `EnsembleModel.predict()` now accepts an optional `df: Optional[pd.DataFrame]` parameter, dynamically computing ATR, RSI, MACD, and volatility features from the last bar, provides `MACRO_NEUTRAL_DEFAULTS`, and evaluates inference with compatible scalers across all timeframes (`1d`, `1h`, `15m`, `5m`).
- **Expected Behavior**: A unified feature extraction module should be shared identically between batch training, continuous training, and live/paper inference.
- **Possible Impact**: None remaining — all timeframes now output active ML probabilities and XAI driver attributions without heuristic fallback.
- **Status**: Resolved / Verified (Pass 13)
- **Remediation**: Implemented in Pass 13 (`ml/ensemble.py`, `ml/registry/`).

---

### Issue 3: Continuous Training Model Bundle Disconnected from Live/Paper Inference
- **Severity**: High
- **Evidence**: `ml/continuous_trainer.py` produces `ml/models/continuous_brain_bundle.pkl`.
- **Affected Area**: `ml/continuous_trainer.py`, `ml/ensemble.py`, `api/training_router.py`
- **Current Behavior**: `EnsembleModel` in `ml/ensemble.py` now supports automatic fallback/promotion to `ml/models/continuous_brain_bundle.pkl` if a registry artifact is missing or incomplete.
- **Expected Behavior**: Continuous training artifacts should promote directly into `ml/registry/` or be dynamically hot-reloaded by `EnsembleModel`.
- **Possible Impact**: Continually trained models are seamlessly loaded into active inference.
- **Status**: Resolved / Verified (Pass 13)
- **Remediation**: Implemented in Pass 13 (`ml/ensemble.py`).

---

### Issue 4: Live Broker Order Submission Fails Closed Without Live Flag (Angel One SmartAPI Integrated)
- **Severity**: Low
- **Evidence**: `api/broker.py`:
  ```python
  if self.broker_mode != "live":
      logger.error("BROKER_MODE is not set to 'live'; refusing real SmartAPI connection.")
      return False
  ```
- **Affected Area**: `api/broker.py`, `live_trader.py`
- **Current Behavior**: `SmartAPIBroker` (Angel One SmartAPI) is implemented with automated RFC 6238 TOTP 2FA, NFO & BFO segment routing, and SEBI Algo-ID order tagging. By design, it enforces fail-closed execution unless `BROKER_MODE=live`, `WHITELISTED_IP`, and valid credentials are provided.
- **Expected Behavior**: Live execution should only execute when real credentials and regulatory compliance (static IP + Algo ID) are verified by the user.
- **Possible Impact**: Protects users from accidental order routing in development while providing production-ready integration.
- **Status**: Operational / Verified by Test (Pass 15)
- **Remediation**: Implemented `SmartAPIBroker` in `api/broker.py` with 100% test coverage in `tests/test_public_apis.py`.
- **Current Behavior**: Attempting to place an order via `BrokerAPI.place_order` raises a `RuntimeError`.
- **Expected Behavior**: For live deployment, integration with an official exchange broker SDK (e.g. Zerodha Kite Connect, AngelOne SmartAPI, Upstox API) with automated order placement, fill reconciliation, and status polling.
- **Possible Impact**: Live capital execution is completely blocked. (This is intentional scaffolding for safety, but represents incomplete live capability).
- **Status**: Incomplete Feature / Scaffolding
- **Recommended Next Investigation/Fix**: Implement a production broker adapter (e.g. `KiteBrokerAdapter`) behind the `BrokerAPI` interface with thorough integration tests and sandbox order execution.

---

### Issue 5: Docker Compose Lacks Multi-Service Production Profile
- **Severity**: Medium
- **Evidence**: `docker-compose.yml` only defines the `timescaledb` database container. It requires `POSTGRES_PASSWORD` in `.env` and does not define services for `api`, `frontend`, or `paper_trader`.
- **Affected Area**: `docker-compose.yml`, `start.py`, deployment
- **Current Behavior**: The user must run Docker for the database, and then manually run `python start.py` on the host OS to spawn Uvicorn, the paper trader daemon, and Vite via `npm.cmd`.
- **Expected Behavior**: A production Docker Compose file (`docker-compose.prod.yml`) that provisions the database, FastAPI backend, paper trader daemon, and an Nginx container serving the built frontend SPA on a unified internal network.
- **Possible Impact**: Complex manual deployment; process management on servers is fragile without systemd or container supervision.
- **Status**: Active / Technical Debt
- **Recommended Next Investigation/Fix**: Author a comprehensive `docker-compose.prod.yml` and containerize the FastAPI backend and Nginx reverse proxy.

---

### Issue 6: Redundant Legacy Frontend Repositories (`frontend_legacy` and `web`)
- **Severity**: Low
- **Evidence**: Previously the project root contained three distinct frontend codebases (`frontend_legacy/`, `web/`, and `frontend/`).
- **Affected Area**: Workspace root
- **Current Behavior**: `frontend_legacy/` and `web/` have been removed cleanly. Only the active, maintained React 19 + TypeScript SPA (`frontend/`) remains. `iterate.txt` was preserved intact.
- **Expected Behavior**: Only one active, maintained frontend codebase should exist in the repository.
- **Possible Impact**: None remaining — repository is consolidated, eliminating developer confusion.
- **Status**: Resolved / Cleaned (Pass 13)
- **Remediation**: Purged legacy directories in Pass 13.

---

### Issue 7: Test Suite Contains Database-Dependent Tests That Fail When Docker Is Offline
- **Severity**: Low
- **Evidence**: Running full `pytest` while Docker / TimescaleDB was stopped previously resulted in 17 failures out of 148 tests due to `ConnectionRefusedError`.
- **Affected Area**: `tests/`, `conftest.py`, `pytest.ini`
- **Current Behavior**: Registered custom `@pytest.mark.database` in `pytest.ini`, created a TCP socket check `is_database_online()` in `conftest.py`, and mapped the 17 integration tests via `pytest_collection_modifyitems`. Running `pytest -m "not database"` executes 131 tests with 100% pass rate in complete offline isolation. When the database is online, all 148 tests run and pass cleanly.
- **Expected Behavior**: Tests requiring database connectivity should be marked and segregated so unit regression suites pass 100% offline.
- **Possible Impact**: None remaining — offline hermetic testing and online integration testing are both verified.
- **Status**: Resolved / Verified (Pass 13)
- **Remediation**: Implemented in Pass 13 (`pytest.ini`, `conftest.py`).

---

### Issue 8: Browser Storage of API Key in `localStorage`
- **Severity**: Medium
- **Evidence**: `frontend/src/main.tsx` lines 20–28:
  ```typescript
  const token = localStorage.getItem('signal_desk_api_key');
  if (token && !config.headers['X-API-Key']) {
    config.headers['X-API-Key'] = token;
  }
  ```
- **Affected Area**: `frontend/src/main.tsx`, `frontend/src/components/SettingsModal.tsx`
- **Current Behavior**: The user's API authentication key is persisted in plain text in browser `localStorage`.
- **Expected Behavior**: For single-user local setups, `localStorage` is convenient. However, in multi-user remote deployments, credentials should use `HttpOnly`, `Secure`, `SameSite=Strict` session cookies to protect against Cross-Site Scripting (XSS) credential theft.
- **Possible Impact**: Any XSS vulnerability or malicious third-party script can read the API key and gain full API access.
- **Status**: Known Security Trade-Off (documented in `REVIEW_LOG.md` Pass 12)
- **Recommended Next Investigation/Fix**: Implement cookie-based session management for hosted production instances.

---

### Issue 9: React Compiler Warnings (Synchronous `setState` in `useEffect`)
- **Severity**: Low
- **Evidence**: Running `npm run lint` (`oxlint`) reports warnings across UI components.
- **Affected Area**: `frontend/src/pages/`, `frontend/src/components/`
- **Current Behavior**: Extracted `formatTradingViewSymbol` into shared utility `tradingViewUtils.ts` and eliminated ref access during render in `TrainingUI.tsx` (`isFetchingRef.current` replaced by `isRefreshing` state). Total oxlint warnings reduced from 16 to 10 with 0 errors.
- **Expected Behavior**: Clean linting with 0 compiler warnings.
- **Possible Impact**: Minor rendering overhead during component mount.
- **Status**: Partially Resolved / In Progress (Pass 13)
- **Recommended Next Investigation/Fix**: Refactor remaining synchronous `setState` inside mount effects across `Analytics.tsx`, `StrategyBuilder.tsx`, `AIJournal.tsx`, `Dashboard.tsx`, and `OptionChartViewer.tsx`.

---

### Issue 10: In-Memory TTL Cache for Real-Time Feeds Not Shared Across Instances
- **Severity**: Low
- **Evidence**: `data/realtime_feed.py` line 38 uses `TTLCache(maxsize=10000, ttl=60.0)`.
- **Affected Area**: `data/realtime_feed.py`
- **Current Behavior**: Quotes and TradingView indicators are cached in process memory with TTLs between 3 and 15 seconds.
- **Expected Behavior**: In horizontally scaled deployments, cache should be shared across instances.
- **Possible Impact**: Redundant upstream calls to Yahoo Finance and TradingView from multiple backend nodes, increasing risk of third-party IP rate limiting.
- **Status**: Active / Technical Debt
- **Recommended Next Investigation/Fix**: Implement an optional distributed Redis caching layer for `RealTimeDataFeed`.

---

### Issue 11: Ambiguous Truth Value on Pandas Index in Continuous Trainer Schema Check
- **Severity**: Medium
- **Evidence**: `ml/continuous_trainer.py`:
  ```python
  names_match = persisted_names is None or list(persisted_names) == list(feature_names or X.columns)
  ```
  Threw `ValueError: The truth value of a Index is ambiguous. Use a.empty, a.bool(), a.item(), a.any() or a.all().` when `feature_names` is a `pd.Index` (e.g. `X.columns`), aborting offline replay cycles.
- **Affected Area**: `ml/continuous_trainer.py`
- **Current Behavior**: `current_names = [str(c) for c in list(feature_names)] if feature_names is not None else [str(c) for c in list(X.columns)]` safely extracts column strings without evaluating boolean truth value of pandas Index. Furthermore, the entire schema comparison is wrapped in an exception-safe block, and Uvicorn watches `--reload-dir api --reload-dir ml --reload-dir data --reload-dir setups` to prevent stale background threads from running across edits.
- **Expected Behavior**: Continuous training loop runs offline historical replay and live training without exceptions.
- **Possible Impact**: Replay training cycles were aborted with warning, skipping model checkpoints.
- **Status**: Resolved / Verified in Live Replay Engine (Pass 19)
- **Remediation**: Corrected `_reset_if_feature_schema_changed()` with bulletproof exception handling, configured multi-directory reloader in `start.py`, verified with regression tests in `tests/test_multi_asset.py`, and confirmed via live execution of offline cycles with 1,133 simulated trades and zero errors.

---

### Issue 12: High Latency When Stopping Continuous Training Loop
- **Severity**: Medium
- **Evidence**: `ml/continuous_trainer.py` and `api/training_router.py`:
  - `generate_features_for_ticker` lacked `stop_event` checks across 5,000-bar setup loops.
  - Busy sleep polling delayed thread response by up to 30 seconds.
  - UI status endpoint returned `is_training: true` while thread finished long computation.
- **Affected Area**: `ml/continuous_trainer.py`, `api/training_router.py`, `frontend/src/pages/TrainingUI.tsx`
- **Current Behavior**: `stop_event` is checked per bar in feature extraction; sleep intervals awaken instantly via `stop_event.wait()`; `is_training` is immediately set to `False`; stop time reduced to <150ms.
- **Expected Behavior**: Instant shutdown upon clicking Stop Trading.
- **Possible Impact**: User had to wait up to 45 seconds for loop termination.
- **Status**: Resolved / Verified by Benchmark (Pass 17)
- **Remediation**: Thread terminates in 0.140s in verified benchmark.

---

### Issue 13: Omission of Closed Trades & Trade Specifications in Training UI
- **Severity**: Medium
- **Evidence**: `ml/live_market_learner.py` stored `self.closed_trades` in memory but omitted them from `get_portfolio_state()` return dictionary, resulting in `0 Closed Trades` shown in `TrainingUI.tsx` despite hundreds/thousands of simulations occurring. Furthermore, active positions displayed only basic contract labels without detailed option Greeks, SL/TP levels, trailing ratchet distance, or setup confluence signals.
- **Affected Area**: `ml/live_market_learner.py`, `ml/continuous_trainer.py`, `api/training_router.py`, `frontend/src/pages/TrainingUI.tsx`
- **Current Behavior**:
  1. `get_portfolio_state()` now serializes `"closed_trades": list(self.closed_trades)[-50:]`.
  2. `_replay_telemetry` tracks simulated trades, win/loss/timeout counts, win rate, and ATR targets during offline historical cycles and exposes them via `api/training_router.py`.
  3. `TrainingUI.tsx` renders a dedicated Closed Trades & Reinforcement Learning table, an Offline Replay telemetry card, and an interactive 360° Trade Specification Dossier Modal (`TradeDossierModal`) for any active or closed trade.
- **Expected Behavior**: Users must be able to inspect every trade parameter (instrument, strike, Greeks, lots, qty, margins, SL, TP, trailing stop, AI confidence, and fired setups).
- **Possible Impact**: Users had zero visibility into trade execution reasoning or historical closed trade performance.
- **Status**: Resolved / Verified (Pass 18)
- **Remediation**: Comprehensive Trade Dossier Modal and telemetry pipeline implemented and verified with clean Vite build and full test suite pass.

---

### Issue 14: Capital Accounting Deficit & Futures PnL Understatement
- **Severity**: Critical (Quant Math)
- **Evidence**: `paper_trader.py` and `ml/live_market_learner.py` failed to deduct required margin/premium from free portfolio capital on order entry, allowing concurrent double-spending and infinite leverage. Furthermore, Futures PnL was calculated as spot percentage change times margin rather than notional points difference times contract quantity, understating risk by ~6.67x.
- **Affected Area**: `paper_trader.py`, `ml/live_market_learner.py`, `api/broker_adapter.py`
- **Current Behavior**: Margin/premium is immediately deducted from free portfolio capital on order creation (`invested_deducted = True`). Upon trade exit, initial margin plus net cash PnL is credited back. Futures PnL is calculated exactly as $\Delta\text{Points} \times \text{Quantity} - \text{Friction}$. Gap slippage on stop-loss is liquidated at `bar_open` when gaps occur.
- **Status**: Resolved / Verified (Pass 21)

---

### Issue 15: React 19 Cascading Renders & Canvas Thrashing (10 Oxlint Violations)
- **Severity**: High (Frontend Performance & UX)
- **Evidence**: 10 `react(set-state-in-effect)` violations across 7 files (`OptionChartViewer.tsx`, `Dashboard.tsx`, `Portfolio.tsx`, `TrainingUI.tsx`, `Analytics.tsx`, `StrategyBuilder.tsx`, `SwingToolkit.tsx`, `AIJournal.tsx`). 2-second polling tick in `OptionChartViewer.tsx` triggered continuous lightweight-charts canvas destruction and redraws every 2 seconds.
- **Affected Area**: `frontend/src/`
- **Current Behavior**: All synchronous state mutations inside `useEffect` bodies were removed or decoupled into promise resolutions. Live tick state was separated from historical candles, eliminating the 2s canvas thrashing. Chart instances are synchronized on container resize.
- **Status**: Resolved / Verified (Pass 21; `oxlint` returns 0 warnings and 0 errors).

---

### Issue 16: Authentication Dev Mode Bypass & Missing `math` Import
- **Severity**: High (Security & Reliability)
- **Evidence**: `_allows_keyless_development()` in `api/auth.py` checked server bind host (`settings.api_host`) instead of request client host (`request.client.host`), allowing remote access when port-forwarded. `api/backtest_router.py` called `math.isfinite()` without importing `math`, causing 100% 500 error crashes on backtests.
- **Affected Area**: `api/auth.py`, `api/backtest_router.py`
- **Current Behavior**: `api/auth.py` strictly validates `request.client.host` (loopback / testclient only). `import math` added to `api/backtest_router.py`.
- **Status**: Resolved / Verified (Pass 21).

---

### Issue 17: Database Pollution via Unverified GET Queries
- **Severity**: High (Database Integrity & Resource Exhaustion)
- **Evidence**: `sync_symbol_ohlcv` and `sync_symbol_news` in `data/service.py` inserted `Symbol` rows before verifying if the ticker existed in external financial data.
- **Affected Area**: `data/service.py`, `data/fetcher.py`
- **Current Behavior**: External data is verified first via `YFinanceFetcher.verify_symbol_exists(ticker)` or non-empty fetched bars before inserting into the database. Tickers without external data return `status: "no_data"` without writing anything to PostgreSQL.
- **Status**: Resolved / Verified (Pass 22).

---

### Issue 18: SSRF, Parameter Injection & XML Entity Expansion in News Ingestion
- **Severity**: Critical (AppSec & DoS)
- **Evidence**: Un-encoded search queries in `data/news_fetcher.py`, unvalidated HTTP redirects, and raw `xml.etree.ElementTree` parsing without entity defense.
- **Affected Area**: `data/news_fetcher.py`
- **Current Behavior**: Queries are quoted with `urllib.parse.quote_plus`; `_is_safe_redirect` resolves destination IPs to reject loopback, RFC 1918 private subnets, and cloud metadata (`169.254.169.254`); `_safe_parse_xml` rejects XML declaring `<!DOCTYPE` or `<!ENTITY` (Billion Laughs defense).
- **Status**: Resolved / Verified (Pass 22).

---

### Issue 19: Doji Candle Feature Singularity & Quant Gradient Explosions
- **Severity**: Critical (Quant ML Math)
- **Evidence**: In `ml/features.py`, normalizing lower wicks by `candle_body + 1e-5` on Doji candles produced panic index values exceeding $5 \times 10^6$, blowing up `StandardScaler` variance and causing `SGDClassifier` weights to explode.
- **Affected Area**: `ml/features.py`
- **Current Behavior**: Denominator is clamped to $\max(\text{candle\_body}, \text{candle\_range} \times 0.1)$, and `psych_panic_index` is strictly clamped to $[0.0, 50.0]$.
- **Status**: Resolved / Verified (Pass 22).

---

### Issue 20: Starlette Validation Exception 500 Crash on Custom Validators
- **Severity**: High (API Stability)
- **Evidence**: Pydantic v2 `RequestValidationError` contains raw `ValueError` objects in `ctx['error']`. Calling `JSONResponse` directly threw `TypeError: Object of type ValueError is not JSON serializable`, converting 422 errors into 500 crashes.
- **Affected Area**: `api/main.py`
- **Current Behavior**: `validation_exception_handler` wraps errors with `jsonable_encoder` after stringifying all `ctx` dictionary entries, returning proper 422 JSON bodies.
- **Status**: Resolved / Verified (Pass 22).

---

### Issue 21: Virtual Broker Bankruptcy Circuit Breaker Bypass
- **Severity**: Critical (Financial Risk)
- **Evidence**: In `ml/replay_engine.py`, when `peak_capital <= 0` (blown account), `drawdown_pct` returned `0.0`, allowing bankrupt accounts to bypass the 10% drawdown kill-switch and continue trading.
- **Affected Area**: `ml/replay_engine.py`, `backtest/engine.py`
- **Current Behavior**: When `capital <= 0` or `peak_capital <= 0`, `drawdown_pct` immediately returns `1.0` (100% drawdown) and locks trading activity.
- **Status**: Resolved / Verified (Pass 22).

---

### Issue 22: Monolithic Error Boundaries & Streaming Log UI Freezes
- **Severity**: Medium-High (Frontend Resilience & UX)
- **Evidence**: Full-page error boundary caused entire UI crashes when a single chart or panel failed. Slicing was missing for 1,000+ training log streams, freezing browser threads.
- **Affected Area**: `frontend/src/components/ErrorBoundary.tsx`, `frontend/src/pages/Dashboard.tsx`, `frontend/src/pages/TrainingUI.tsx`
- **Current Behavior**: `ErrorBoundary` supports `compact` mode with localized "Reload Widget" buttons; `TrainingUI` slices logs to 300 lines with real-time text filtering; `TradeDossierModal` enforces WCAG AA focus trapping.
- **Status**: Resolved / Verified (Pass 22).

---

### Issue 23: Live Trader Safeguard Disconnect (Circuit Breaker & Consensus Bypassed)
- **Severity**: Critical (Financial Risk)
- **Evidence**: `live_trader.py` lacked `DrawdownCircuitBreaker` gating, `MultiAgentConsensusEngine` rulings, feature enrichment, and dynamic India VIX IV.
- **Affected Area**: `live_trader.py`
- **Current Behavior**: Integrated circuit breaker pre-scan gate, multi-agent consensus gate, feature enrichment, dynamic India VIX, and disk state persistence (`live_trades.json`).
- **Status**: Resolved / Verified (Pass 23).

---

### Issue 24: Static 7-Day DTE Assumption Distortion on 0-DTE Expiries
- **Severity**: High (Options Pricing & Greeks)
- **Evidence**: `ml/options_engine.py` hardcoded `DAYS_TO_EXPIRY = 7.0`, causing distorted Delta, Theta, and Gamma on non-7DTE trading days.
- **Affected Area**: `ml/options_engine.py`
- **Current Behavior**: Implemented dynamic DTE per index (`MIDCPNIFTY` Mon, `FINNIFTY` Tue, `BANKNIFTY` Wed, `NIFTY` Thu, `SENSEX` Fri) calculating fractional trading days to 15:30 IST close with automatic weekly rollover.
- **Status**: Resolved / Verified (Pass 23).

---

### Issue 25: Dashboard Analytics Indentation Bug Returning None
- **Severity**: High (API Stability & UX)
- **Evidence**: In `api/dashboard_router.py`, `/analytics` logic was indented inside the database exception block, returning `None` when database queries succeeded.
- **Affected Area**: `api/dashboard_router.py`
- **Current Behavior**: Indentation corrected so metrics, equity curve, and Gambler's Ruin probability of ruin are computed and returned consistently.
- **Status**: Resolved / Verified (Pass 23).

---

### Issue 26: Unrealistic F&O Slippage Assumption vs Statutory SEBI Costs
- **Severity**: High (Financial Modeling)
- **Evidence**: Previous flat 0.05% slippage failed to account for flat ₹20 buy/sell brokerage, SEBI STT (0.1% on options sell), NSE txn charges, GST 18%, and Stamp Duty.
- **Affected Area**: `ml/risk_engine.py`, `paper_trader.py`
- **Current Behavior**: Implemented `IndianFOFrictionModel` with exact analytical breakeven calculation and risk gating against high-friction setups.
- **Status**: Resolved / Verified (Pass 23).

---

### Issue 27: Missing Intraday MIS Square-Off Cutoff at 15:15 IST
- **Severity**: Medium-High (Operational Risk)
- **Evidence**: Intraday positions held past 15:15 IST risked broker RMS auto-square-off penalties.
- **Affected Area**: `paper_trader.py`, `ml/live_market_learner.py`
- **Current Behavior**: Enforced automatic exit at 15:15 IST with `exit_reason = "INTRADAY_SQUARE_OFF"`.
- **Status**: Resolved / Verified (Pass 23).

---

### Issue 28: React 19 State Closure Race Condition in Setup Selector
- **Severity**: Medium (Frontend Functional Integrity)
- **Evidence**: In `BacktestUI.tsx`, strategy presets called `setSetup()` followed by `setTimeout(runBacktest)`, which read stale closed-over state.
- **Affected Area**: `frontend/src/pages/BacktestUI.tsx`
- **Current Behavior**: `runBacktest` accepts an explicit override parameter, eliminating closure delay.
- **Status**: Resolved / Verified (Pass 23).

---

### Issue 29: Path Parameter Rate Limit Permutation Bypass
- **Severity**: High (Security & Abuse)
- **Evidence**: `api/auth.py` previously keyed rate limit buckets by concrete request path (`request.scope.get('path')`), allowing clients to bypass the 60 req/min limit by cycling through ticker symbols (e.g. `/quote/TCS`, `/quote/INFY`).
- **Affected Area**: `api/auth.py`
- **Current Behavior**: Keying is now bound to the endpoint route template (`route.path`), sharing the quota bucket across all parameter variants. In addition, client IPs extracted from `X-Forwarded-For` are verified with `ipaddress.ip_address()`, and IPv4-mapped IPv6 loopbacks (`::ffff:127.0.0.1`) are normalized.
- **Status**: Resolved / Verified (Pass 24).

---

### Issue 30: Windows File Lock Race Condition & 503 Crashes in Strategy Store
- **Severity**: Medium-High (Concurrency & Reliability)
- **Evidence**: In `api/strategy_router.py`, `setups/swing_toolkit/toolkit.py`, and `ml/trade_logger.py`, concurrent asynchronous requests caused Windows file-lock contention and `json.JSONDecodeError` when reading during an atomic file replace (`os.replace`), yielding HTTP 503 errors.
- **Affected Area**: `api/strategy_router.py`, `setups/swing_toolkit/toolkit.py`, `ml/trade_logger.py`
- **Current Behavior**: Synchronized all read and atomic write operations with `threading.RLock()`, and safely defaulted empty uninitialized strategy files to an empty array `[]`.
- **Status**: Resolved / Verified (Pass 24).

---

### Issue 31: SSRF Port Probing & 0.0.0.0 IP Bypass in News Fetcher
- **Severity**: High (Security)
- **Evidence**: In `data/news_fetcher.py`, the redirect validator allowed non-standard ports (8443, 8000) and `0.0.0.0` (which connects to localhost on Windows and Linux), and XML payloads were parsed without length caps when `defusedxml` was installed.
- **Affected Area**: `data/news_fetcher.py`
- **Current Behavior**: Strictly restricted redirects to HTTPS port 443, blocked `ip.is_unspecified` (`0.0.0.0` and `::`), and enforced a 5MB payload limit prior to XML parsing.
- **Status**: Resolved / Verified (Pass 24).

---

### Issue 32: Silent Null-Byte Stripping & Path Traversal in Data Ingestion
- **Severity**: Medium-High (Security & Data Integrity)
- **Evidence**: `data/service.py` silently replaced null bytes with `""` instead of raising validation errors, and ticker parameters permitted directory traversal sequences (`..`).
- **Affected Area**: `data/service.py`, `api/router.py`, `api/schemas.py`, `api/backtest_router.py`
- **Current Behavior**: Standardized centralized `_validate_service_ticker()` across all ingestion and API entrypoints, strictly rejecting null bytes, path traversal sequences (`..`, `/`, `\`), and URI fragments (`#`).
- **Status**: Resolved / Verified (Pass 24).

---

### Issue 33: Multi-threaded ContextVar Isolation Failure in TradeLogger
- **Severity**: Medium (Concurrency & Audit Logging)
- **Evidence**: In `ml/trade_logger.py`, Python `ContextVar` values set in a parent thread did not propagate into child worker threads, causing background worker events to fail to write to custom log files.
- **Affected Area**: `ml/trade_logger.py`
- **Current Behavior**: Implemented a synchronized `_global_log_file` fallback so spawned threads inherit the active test or worker log file.
- **Status**: Resolved / Verified (Pass 24).

---

### Issue 34: Option Selling Exit Direction Inversion in Broker Executors
- **Severity**: Critical (Trading Execution)
- **Evidence**: In `paper_trader.py` and `live_trader.py`, position close logic defaulted to placing `SELL` orders, which incorrectly attempted to sell more contracts when exiting a short option position.
- **Affected Area**: `paper_trader.py`, `live_trader.py`
- **Current Behavior**: Corrected exit logic to submit a `BUY` order at current ask price when exiting a position with `side == "SELL"`.
- **Status**: Resolved / Verified (Pass 24).



