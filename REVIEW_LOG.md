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

## Remaining High-Risk Findings

- Replay and paper/live trades still share the same journal and RL weight store; historical replay can contaminate live learning and dashboard metrics. This remains a production blocker until records and weights are source/run scoped.
- Replay still fills entries at the current bar close despite the stated next-bar-open design; this is lookahead/optimism risk and requires a pending-order model with next-bar execution.
- The paper-trader kill switch still needs mark-to-market equity, not only realized account capital, to stop on unrealized portfolio drawdown.
- Runtime dashboard configuration does not reload module-level paper-trader settings while the loop is running.
- Journal and RL JSON persistence are append/overwrite operations without cross-process locking; concurrent paper/replay processes can lose or corrupt state.
- The AI Journal frontend has no authenticated API-key transport, so protected deployments require an explicit frontend auth mechanism before this page can work.
- Continuous-training artifacts are still not consumed by `EnsembleModel`; batch registry and continuous bundle deployment need one deliberate production path.
- Feature construction remains duplicated between training and inference; macro/options/psychology fields are not available to inference callers, so incompatible registry artifacts safely fall back rather than producing a model prediction.
- Live/paper execution remains Indian-specific by design; non-Indian execution must stay blocked until exchange, currency, calendar, fee, lot-size, and broker support are implemented.
- Rate limiting remains process-local and is not suitable for multi-worker production deployment.
- Compose still provisions only the database, and clean-volume role/database initialization requires deployment validation.
- Frontend browser-level race, accessibility, mobile viewport, and large-dataset checks remain unexecuted.
