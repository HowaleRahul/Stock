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

## Remaining High-Risk Findings

- Continuous-training artifacts are still not consumed by `EnsembleModel`; batch registry and continuous bundle deployment need one deliberate production path.
- Feature construction remains duplicated between training and inference; macro/options/psychology fields are not available to inference callers, so incompatible registry artifacts safely fall back rather than producing a model prediction.
- Live/paper execution remains Indian-specific by design; non-Indian execution must stay blocked until exchange, currency, calendar, fee, lot-size, and broker support are implemented.
- Rate limiting remains process-local and is not suitable for multi-worker production deployment.
- Compose still provisions only the database, and clean-volume role/database initialization requires deployment validation.
- Frontend browser-level race, accessibility, mobile viewport, and large-dataset checks remain unexecuted.
