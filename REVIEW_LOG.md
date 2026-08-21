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
