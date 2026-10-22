# Production Review Log

## Pass 1 — Functional correctness

- Fixed RSI warm-up and flat-market handling. A flat series now reports a neutral RSI of 50 instead of NaN/100.
- Replaced version-sensitive indicator calls with deterministic SMA, EMA, MACD, and population-standard-deviation Bollinger implementations.
- Restored the documented five technical setup result contract; experimental/incomplete setups no longer emit misleading signals.
- Preserved FastAPI's standard `detail` error field alongside the existing API error shape.
- Added the dashboard title used by the static frontend.
- Hardened chart rendering against invalid timestamps/prices and stale trade markers.

## Pass 2 — Security and abuse cases

- Production now fails closed when `API_KEY` is absent; API-key comparison is timing-safe.
- Validated and bounded dashboard configuration writes; unknown fields and unsafe risk values are rejected.
- Made configuration and strategy JSON writes atomic and made malformed stores fail closed with a 503 response.
- Strategy names are normalized and compared case-insensitively; condition collections are bounded.
- Removed the publicly documented development database password and restricted the Compose database port to localhost.

## Pass 3 — Performance, architecture, UX, and accessibility

- Removed dependency-sensitive signal expansion from the core setup engine; failed regime detection is advisory rather than contaminating every result.
- Frontend production build succeeds. The generated main bundle is 461.69 kB (148.52 kB gzip), which remains a performance follow-up.
- `Analytics.tsx` contained a pre-existing, user-owned resize-listener edit and trailing whitespace; it was intentionally not modified.

## Verification

- `tests/test_phase2_adversarial_sdet.py`, `tests/test_phase2_security.py`, and `tests/test_phase2_search_and_edge_cases.py`: 14 passed.
- `tests/test_phase1_data.py`: 37 passed, 2 failed. Both failures are non-hermetic expectations of live Yahoo Finance success; the environment's Yahoo cache cannot open its local database. The service correctly reports no-data/failure instead of fabricating success.
- `npm.cmd run build`: passed.
- `npm.cmd run lint`: passed with four pre-existing/non-blocking warnings.

## Multi-Asset Generalization Follow-up

- Added a single asset-class policy for Indian indices, US indices, and the supported crypto universe. This prevents inconsistent ticker heuristics between batch training, continuous training, and inference.
- Added asset-specific triple-barrier settings: crypto uses 3.0 ATR take-profit and 1.5 ATR stop-loss defaults; equity retains 2.0/1.0.
- Added asset-aware macro context: India VIX/USDINR for Indian equity; US VIX/DXY for US equity; US VIX/DXY plus delayed BTC volume for crypto.
- Implemented normalized daily alignment with forward-fill, so Friday macro values safely carry across Saturday/Sunday crypto candles without lookahead.
- Added one-hot asset features to both training paths and ensemble inference, with asset-class-aware explanations.
- Added a schema-drift guard that resets the continuous incremental model/scaler when a persisted scaler has a different feature count.
- Added deterministic multi-asset tests and removed two non-hermetic Yahoo Finance expectations from the test suite.

## Implementation Pass — Multi-Asset Hardening

- Replaced silent unknown-ticker classification with canonical aliases and fail-closed asset policy. `NIFTY`/`BANKNIFTY` normalize to Yahoo index symbols; supported global and crypto symbols receive explicit classes.
- Added atomic continuous-training model bundles containing the model, scaler, ordered feature names, asset class, timeframe, and feature version. Schema drift now checks feature names as well as count.
- Batch model artifacts now persist and use the scaler, feature metadata, asset class, and timeframe. Inference rejects incomplete or incompatible artifacts instead of silently zero-filling missing features.
- Corrected the backtest call to the ATR-based triple-barrier label API.
- Broker execution now fails closed without a real configured adapter or static-IP whitelist, validates order fields, uses explicit exchange routing, and separates option type from transaction side. Live option orders use `BUY` on `NFO`.
- Dashboard, strategy, backtest, training, data, and search routers now inherit authentication; non-development environments fail closed when authentication is not configured.
- Analytics, Portfolio, and Training frontend pages now show accessible API failure states rather than crashing or silently presenting empty/stale data.

## Verification — Current Environment

- `python -m compileall -q api backtest data ml models setups paper_trader.py live_trader.py`: passed.
- Direct asset-policy checks for aliases, AAPL, ETH-USD, and unknown-symbol rejection: passed.
- Direct broker checks for missing static-IP configuration and unsupported exchange routing: passed.
- `frontend`: `npm.cmd run build`: passed. Bundle remains approximately 462 kB (149 kB gzip).
- Focused multi-asset/security/adversarial suite: 19 passed with one pandas warning.
- Data-layer regression suite: 39 passed with one pandas warning.
- Full repository suite: 96 passed with one pandas warning.
- Continuous model bundle serialization and scaler metadata round-trip: passed.
- Complete Python compilation: passed.

## Pass 4 — Self-play and production failure paths

- Fixed replay self-review so analyzed insights are actually applied through `full_self_review()`.
- Fixed paper-trader kill-switch crash caused by an undefined `new_trade`; it now sends a system alert and honors the configured drawdown threshold.
- Added API-key settings support for `.env` values while preserving runtime environment overrides.
- Corrected dashboard analytics to use configured starting capital, count only completed P&L records, and safely expose nullable recent P&L.
- Isolated replay broker state when an engine instance is reused.
- Removed same-bar trailing-stop lookahead in historical replay by applying updated trailing stops only after exit evaluation.
- Narrowed the database entrypoint host authorization from `0.0.0.0/0` to the private Docker bridge range and made the Compose healthcheck honor overridden credentials.
- Fixed the AI Journal UI crash when an exit record has null P&L.

## Verification — Pass 4

- Focused security/adversarial suite: 14 passed with one dependency warning.
- Full Python suite after prior fixes: 96 passed with one dependency warning.
- Frontend production build after latest UI change: passed.
- Frontend lint: build remains clean; four warnings remain in pre-existing unrelated pages.

## Pass 5 — Runtime startup failure

- Fixed a stale `SetupEngine` contract in `paper_trader.py`, `live_trader.py`, `backtest/run.py`, and `ml/replay_engine.py`. Regime-aware callers now use `evaluate_with_regime()`; the signal-only `evaluate_all()` contract remains intact for tests and other callers.
- Reduced launcher warning spam in `start.py` by reporting each exited child process once.

## Verification — Pass 5

- Setup and adversarial regression tests: 32 passed with one dependency warning.
- Full Python suite: 96 passed with one dependency warning.
- Python compilation of launcher and trading entrypoints: passed.

## Pass 6 — Frontend route and interaction audit

- Fixed the active frontend's missing Vite `/api` proxy, which sent development API calls to port 5173 instead of the backend.
- Fixed three `lightweight-charts` v5 runtime crashes: candlestick series creation, line series creation, and marker management.
- Hardened chart cleanup during route changes and React remounts to prevent disposed-chart resize errors.
- Fixed Dashboard initial data loading and aborted-request loading-state races.
- Fixed Backtesting's stale indicator imports, which caused every backtest request to return HTTP 500.
- Replaced the blank Backtesting chart placeholder with a populated accessible trade-results table.
- Audited all seven routes at desktop and mobile widths; no route produced an error boundary.

## Verification — Pass 6

- Browser route sweep: Dashboard, Portfolio, Analytics, Backtesting, Training, Strategies, and AI Journal rendered successfully.
- Browser Backtesting action: 51 trade rows rendered with no alert or error boundary.
- Frontend production build: passed.
- Focused backend regression suite: 35 passed with one dependency warning.
- Frontend lint: three existing state-effect warnings remain in Dashboard, TrainingUI, and StrategyBuilder.

## Pass 7 — Service outage and documentation route

- Confirmed the reported Training, Strategy Builder, and AI Journal failures were caused by both backend and frontend dev servers being stopped (`ERR_CONNECTION_REFUSED`), not by their API response contracts.
- Added development proxying for `/docs` and `/openapi.json`, fixing the API documentation link from the frontend origin.
- Added explicit retryable offline states to Training, Strategy Builder, and AI Journal instead of repeated console errors or a generic failure message.
- Verified live backend responses: Training `STOPPED`, Strategy Builder empty list, and AI Journal zero-trade report.

## Verification — Pass 7

## Pass 8 — Paper persistence transaction hardening

- Added durable `trade_context` and `journal_events` tables for complete paper-trade context and audit events.
- Paper trading now reads account/open positions from PostgreSQL and persists account, trade state, and scan journal events through a shared transaction boundary.
- Added database audit records for ENTRY, EXIT, REJECTION, KILL_SWITCH, and RL self-review decisions; JSONL remains a compatibility export.
- Dashboard trade retrieval prefers database journal events and falls back to legacy JSON history when the database has no events.

## Verification — Pass 8

- Changed Python files compile successfully.
- `git diff --check` passes.
- Full database-backed verification remains blocked until PostgreSQL is running; Docker also requires `POSTGRES_PASSWORD` in `.env`.

## Pass 9 — Database online validation

- Added a persistence integration regression test covering trade/context round-trip, ENTRY/EXIT journal events, close-state updates, and persisted P&L.
- Confirmed the healthy `trading_timescaledb` container contains `accounts`, `trades`, `trade_context`, and `journal_events`.
- Confirmed the paper persistence and setup/API regression slice passes: 26 tests passed.
- Full Python suite passes: 97 tests passed with one pandas-ta compatibility warning.
- Both frontend clients build and lint successfully. The active bundle is approximately 501 kB; the legacy bundle is approximately 4.9 MB. These remain performance follow-ups.
- Compose management still fails closed because `.env` has no `POSTGRES_PASSWORD` key, even though the existing container is healthy. No default password was added.

## Pass 10 — Replay, backtest, and live-exit hardening

- Isolated replay journal writes with context-local routing and isolated temporary RL weights, preventing historical replay from mutating paper/live learning state.
- Excluded walk-forward training rows whose triple-barrier horizon crosses into the test window.
- Rejected neutral backtest predictions instead of recording them as positions with direction zero.
- Corrected live short-position exit comparisons and bearish/short P&L inversion; unknown persisted directions now fail closed for automatic exits.

## Verification — Pass 10

- Replay isolation regression: passed.
- Focused persistence, replay, setup/API regressions: 27 passed.
- Full Python suite: 98 passed with one pandas-ta compatibility warning.
- Complete Python compilation: passed.

- Swagger UI: loaded at `http://127.0.0.1:5173/docs` through the Vite proxy.
- Training, Strategy Builder, and AI Journal: rendered with live API and no error boundary.
- Frontend production build: passed.
- Frontend lint: four state-effect warnings remain in Dashboard, TrainingUI, StrategyBuilder, and AIJournal.

## Pass 8 — No-Code Strategy Builder

- Replaced the placeholder Strategy Builder with a functional rule composer for bullish entry and bearish exit conditions.
- Added indicator/operator/value controls, add/remove rule actions, empty-value validation, save progress state, live preview, and saved-strategy condition counts.
- Preserved the existing API payload contract using `bullish_conditions` and `bearish_conditions` arrays.
- Added responsive mobile layout and accessible labels, regions, remove-action names, and save controls.

## Verification — Pass 8

- Strategy Builder browser render: passed.
- Empty strategy save validation: passed; no request is sent without a name.
- Backend/API schema compatibility: preserved and frontend production build passed.

## Pass 9 — AI Training Engine UI

- Replaced the generic Training page with an operational model-lab view: idle/running state, start/stop controls, action-pending state, log-buffer count, refresh cadence, latest event, and live telemetry console.
- Added responsive mobile behavior and clearer offline/retry handling while preserving the existing training API endpoints.

## Verification — Pass 9

- Live browser render: passed with backend-connected `IDLE` state.
- Stop control correctly disabled while idle; start control available.
- Frontend production build: passed.
- Frontend lint: only existing React effect warnings remain.

## Pass 10 — Portfolio UI and service failure handling

- Confirmed the reported Portfolio error was caused by the backend being offline (`ERR_CONNECTION_REFUSED`).
- Added a retryable offline/API error state instead of the previous dead-end message.
- Added manual refresh and last-updated feedback.
- Corrected position direction styling to support the backend's `LONG`/`SHORT` values.
- Added account/exposure hierarchy and a clear empty-positions state.

## Verification — Pass 10

- Live Portfolio API/UI: passed; account `ACTIVE`, capital and peak capital rendered, zero-position state rendered.
- Frontend production build: passed.
- `git diff --check`: passed.

## Pass 11 — Production Hardening, MTM Equity Kill-Switch, Replay Execution, and Security Transport

- Fixed Paper Trader kill-switch to calculate total Mark-to-Market (MTM) equity including open unrealized P&L across both equity and options positions, rather than evaluating cash alone. Prevents catastrophic drawdowns during market gap-downs.
- Added dynamic runtime configuration reloading in `paper_trader.py`; adjustments to risk-per-trade, max-drawdown, and minimum AI confidence now apply instantly on each main-loop cycle without process restart.
- Implemented pending-order execution at next bar's open in `ml/replay_engine.py`; eliminates lookahead bias where orders previously executed retroactively at the close of the signal-generating bar.
- Hardened `api/dashboard_router.py` portfolio and journal endpoints with resilient fallbacks to local paper state (`paper_account.json`, `paper_trades.json`, and `trade_journal.jsonl`) when TimescaleDB/Postgres is restarting or offline.
- Fixed rate-limiting IP spoofing and cross-route starvation in `api/auth.py`. Client IPs are verified against trusted reverse-proxy subnets, and quotas are namespaced per `(client_ip, endpoint_path, quota)`.
- Replaced unbounded in-memory cache in `data/realtime_feed.py` with a bounded `TTLCache(maxsize=10000, ttl=60.0)` to eliminate memory leaks during 24/7 daemon runs.
- Parallelized active watchlist real-time quote retrieval in `api/market_router.py` using `asyncio.gather`, reducing endpoint latency by ~8x.
- Added client-side API authentication UI (`SettingsModal.tsx`) with automatic 403 Forbidden interceptor in `main.tsx` and persistent `X-API-Key` transport, securing production deployments.
- Implemented and verified the complete Momentum Masters Swing Toolkit (`setups/swing_toolkit/`, `api/swing_router.py`, `SwingToolkit.tsx`) including 3 scanners, 8-factor checklist scoring, and 15m ORB volume gate execution.

## Verification — Pass 11

- Python compilation: `compileall` passed on all packages with 0 errors.
- Test suite: 142 passed, 0 failed in 48.28s (`pytest`).
- Frontend production build: `npm run build` passed in 1.03s.
- Replay pending-order isolation: verified with targeted unit test.
- Paper persistence & data regression: passed with TimescaleDB container healthy.

## Remaining High-Risk Findings

- Continuous-training artifacts are still not directly consumed by `EnsembleModel`; batch registry and continuous bundle deployment need one unified production deployment path.
- Feature construction remains duplicated between training and inference; macro/options/psychology fields are not available to inference callers, so incompatible registry artifacts safely fall back rather than producing a model prediction.
- Live/paper execution remains Indian-specific by design; non-Indian execution must stay blocked until exchange, currency, calendar, fee, lot-size, and broker support are implemented.
- Rate limiting remains process-local in memory; distributed deployment with multiple Uvicorn workers requires a Redis-backed token bucket.
- Compose provisions TimescaleDB; multi-service container orchestration for API, frontend, paper trader, and continuous trainer requires a unified production compose profile.

## Pass 12 — Current-source production revalidation

### Functional correctness

- Training startup previously swallowed malformed/unwritable `config.json` errors and still returned a successful start response. Configuration writes now use a unique same-directory temporary file and atomic replace; a persistence error is logged and returns HTTP 500 before the training thread starts.
- Training request fields now reject unsupported modes, indices, instruments, and strike preferences. Capital must be finite, positive, and at most INR 1,000,000,000.
- Option chart requests are aborted when instrument parameters change or the component unmounts, preventing stale responses from replacing the current contract. Open position entry/target/stop-loss values are now shown as chart price lines.
- Option-chart failures and Swing Toolkit watchlist loading/failure are surfaced with retryable, accessible states instead of silent failure or a misleading empty state.
- Browser-storage errors for API-key entry are reported; the UI states that a key which could not be persisted is available only for the current tab. Settings dialog focus is moved into the dialog, trapped while open, restored on close, and Escape closes it.
- Fixed TypeScript diagnostics: unused imports/state, unused option-chart props (now used), and a type-only `ReactNode` import.

### Security and abuse

- The environment default is now `production`. Startup fails when no API key is configured except for explicitly configured development mode bound to loopback; protected requests also fail closed. This prevents the implicit-development default from silently disabling auth on exposed binds/proxies.
- API keys are no longer accepted from URL query parameters or copied to local storage from the URL. Legacy `api_key`/`apiKey` parameters are removed from the visible URL/history on app initialization. Rotate any key previously shared in a URL; the original request may already exist in upstream logs.
- The read-only security review reported no additional actionable DOM injection issue in the reviewed legacy/web UI paths. No external or production target was contacted.
- Browser-stored API keys remain accessible to same-origin JavaScript. Remote deployments must use HTTPS and should move to per-user, scoped credentials or an HttpOnly session design before serving untrusted users.

### Performance, architecture, UX, and accessibility

- The frontend production build splits routes and vendors; the chart vendor is still about 166 kB uncompressed (55 kB gzip), so chart loading remains a bundle-size follow-up.
- The maintained frontend has a skip link, navigation landmarks, labeled settings input, modal semantics, and accessible loading/error announcements. No automated screen-reader, contrast, keyboard-browser, or cross-browser run was available; those are not claimed as verified.
- `frontend_legacy` and `web` remain parallel/legacy interfaces; `web` hardcodes the local API origin and does not implement the current API-key flow. Do not treat either as a production frontend without consolidation and deployment-specific testing.
- Existing architectural risks remain: continuous-training artifacts are not unified with inference deployment; feature construction is duplicated; execution is India-specific; rate limits and training state are process-local; Compose only provisions the database; the TimescaleDB image builds from a floating upstream `latest` branch.

### Remaining report and readiness assessment

- Confirmed issues addressed in this pass: implicit keyless default authentication (HIGH), URL credential persistence/leakage (MEDIUM), training configuration write failure reported as success (MEDIUM), unsupported training input acceptance (MEDIUM), stale option-chart responses/hidden chart errors (LOW), and ambiguous watchlist loading/failure (LOW).
- Production readiness: **5/10**. The reviewed application paths have useful validation and automated checks, but deployment, distributed state/rate limits, model artifact lifecycle, shared browser credentials, and live-market integration remain material release blockers for a multi-user or multi-instance production deployment.
- Review confidence: **7/10**. Static review, focused regression tests, build, type-check, and lint were completed; live database, live market/broker, browser automation, and production deployment behavior were intentionally not exercised.

## Verification — Pass 12

- Deterministic offline Python regression selection: **108 passed**, 2 dependency/deprecation warnings.
- Python compilation across API, backtest, data, ML, models, setups, paper trader, and live trader modules: passed.
- Frontend TypeScript check (`tsc --noEmit -p tsconfig.app.json`): passed.
- Frontend production build: passed. Largest route vendor chunks: React 234.19 kB uncompressed; charts 166.45 kB uncompressed.
- Frontend lint: passed with 16 non-blocking React hook/Fast Refresh warnings in existing UI code.
- `git diff --check`: passed.
- Not run by design: database persistence/health integration, live quote/news/search tests that can call external providers, live broker/trading flows, browser automation, and deployment/proxy integration.

## Pass 13 — Audit Remediation, Feature Pipeline Alignment, Hermetic Testing, and Repository Consolidation

### Audit 01 — Feature Pipeline Alignment & ML Model Lifecycle
- Unified the ML prediction contract in `ml/ensemble.py` by introducing `MACRO_NEUTRAL_DEFAULTS`, continuous bundle fallback (`CONTINUOUS_BUNDLE_PATH`), and optional `df: Optional[pd.DataFrame]` parameter to extract full indicators dynamically from the latest price bar.
- Formatted feature vectors using `pd.DataFrame` with explicit column names, preventing scikit-learn feature name mismatch warnings.
- Deployed compatible scaler bundles across all timeframes (`model_1d.pkl`, `model_1h.pkl`, `model_15m.pkl`, `model_5m.pkl`) in `ml/registry/`.
- Updated all inference callers (`api/router.py`, `paper_trader.py`, `live_trader.py`, `ml/replay_engine.py`) to supply primary market DataFrames to `ensemble.predict()`.
- Active ML probabilities and XAI driver attributions now operate continuously across `1d`, `1h`, `15m`, and `5m` timeframes without falling back to heuristic voting.

### Audit 02 — Distributed Infrastructure Configuration
- Added `redis_url: Optional[str] = Field(default=None, alias="REDIS_URL")` to `api/config.py` Pydantic settings schema to enable centralized token-bucket rate limiting in multi-worker production deployments.

### Audit 03 — Repository Consolidation & Dead Code Elimination
- Cleanly purged deprecated, unreferenced legacy frontends `frontend_legacy/` (vanilla HTML/JS) and `web/` (outdated React prototype) from the repository root.
- Confirmed that `iterate.txt` is intact and preserved in the repository root.
- Single source of truth for the UI is now exclusively `frontend/` (React 19 + TypeScript + Vite).

### Audit 04 — Test Fixture Hermeticity & Offline CI/CD
- Registered the `database` marker in `pytest.ini`.
- Added dynamic TCP socket probe `is_database_online()` and `pytest_collection_modifyitems` hook in `conftest.py` that dynamically marks database-dependent test cases.
- Enables 100% offline hermetic execution (`pytest -m "not database"`: 131 passed in 40s) without requiring running Docker/PostgreSQL containers, while retaining full integration coverage when the database is available (`pytest`: 148 passed).

### Frontend Warning Reductions & Code Hygiene
- Extracted `formatTradingViewSymbol` into shared utility `frontend/src/components/tradingViewUtils.ts` to satisfy Vite Fast Refresh component constraints.
- Eliminated ref access during render in `TrainingUI.tsx` by introducing `isRefreshing` state.
- Hardened cleanup effects in `TradingViewWidget.tsx` and `TradingViewTASummary.tsx` against container null references.
- Verified TypeScript build (`tsc -p tsconfig.app.json --noEmit`) passes with 0 diagnostics; production Vite build passes in 1.41s.

## Verification — Pass 13
- Python compilation: `venv\Scripts\python -m compileall -q api backtest data ml models setups papertrade scripts tests paper_trader.py live_trader.py start.py conftest.py` passed with 0 errors.
- Test suite (full): `pytest -q` passed all 148 tests with 0 failures.
- Test suite (offline/hermetic): `pytest -m "not database" -q` passed all 131 tests with 0 failures.
- Frontend build: `npm run build` passed in 1.41s.
- Oxlint: warnings reduced from 16 to 10 with 0 errors.
- System integrity: `iterate.txt` verified present and unmodified.
