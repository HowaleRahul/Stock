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
