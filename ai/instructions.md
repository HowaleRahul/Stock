# AI Instructions & Developer Guardrails

This document establishes operational directives, architectural constraints, and coding conventions that all future AI agents and human contributors must follow when working on the **Personal AI-Assisted Trading System (Signal Desk)**.

---

## 1. Project-Specific Rules

### 1.1 Non-Negotiable Operational Safety
* **Fail-Closed Financial Execution**: Never allow automated orders or broker connections without an explicit `ENVIRONMENT=LIVE` setting, valid authenticated broker adapters, and static IP whitelisting. By default, live order injection throws a `RuntimeError` (verified in `api/broker.py` line 131).
* **Option Buying Only**: Under SEBI retail algo regulations and system policy, derivative strategies are restricted to long options (`CE` or `PE` buying). Naked option writing (short calls/puts) is prohibited to prevent unlimited tail risk (verified in `ml/options_engine.py` line 11).
* **Risk Envelope Enforcement**: The risk engine strictly enforces maximum risk per trade ($\le 2\%$, configurable up to $5\%$ ceiling) and minimum Risk-to-Reward ratio ($\ge 1.5:1$). Trades violating these constraints must be rejected and logged to the journal with explicit rejection reasons (verified in `ml/risk_engine.py`).
* **Kill-Switch Thresholds**: If total Mark-to-Market (MTM) drawdown reaches or exceeds `max_portfolio_drawdown_pct` (default 10%), all trading activity is locked, a critical alert is dispatched via `api/notifier.py`, and the status transitions to `HALTED_DRAWDOWN` (verified in `paper_trader.py`).

### 1.2 Multi-Asset Policy Separation
* **Explicit Asset Classification**: The system supports `IN_EQUITY`, `US_EQUITY`, and `CRYPTO`. Ticker classification is centralized in `ml/assets.py`. Do not introduce ad-hoc heuristics (e.g. searching for `"USD"` in ticker strings); unknown symbols must fail closed with a `ValueError`.
* **Asset-Specific Barriers & Macro**: 
  - Indian equities (`IN_EQUITY`): Macro context uses India VIX and USD/INR (`INR=X`). Barriers: 2.0 ATR target, 1.0 ATR stop.
  - US equities (`US_EQUITY`): Macro context uses US VIX (`^VIX`) and Dollar Index (`DX-Y.NYB`). Barriers: 2.0 ATR target, 1.0 ATR stop.
  - Crypto (`CRYPTO`): Macro context uses US VIX, DXY, and 24h volume. Barriers: 3.0 ATR target, 1.5 ATR stop. Crypto trades 24/7; macro series must be forward-filled from Friday closes without lookahead (verified in `ml/features.py`).

---

## 2. Architecture Constraints

### 2.1 Backend Architecture
* **Framework**: FastAPI with asynchronous route handlers and Pydantic v2 validation.
* **Database Access**: SQLAlchemy 2.0 async engine (`postgresql+asyncpg://`) with connection pooling (`pool_size=20`, `max_overflow=20`, `pool_pre_ping=True`).
* **Clean Fallbacks**: When TimescaleDB is unreachable, the API routers (`api/dashboard_router.py`) and background worker (`paper_trader.py`) must gracefully fall back to local disk state (`paper_account.json`, `paper_trades.json`, `logs/trade_journal.jsonl`) rather than crashing.
* **Synchronous Work Offloading**: Blocking CPU computations (e.g., pandas calculations, scikit-learn training, yfinance synchronous fetches) must be run via `run_in_threadpool` or `asyncio.to_thread` to prevent blocking the async event loop.
* **Atomic State Persistence**: Mutating file operations (`config.json`, strategies JSON, model registry `.pkl` files) must use same-directory temporary files (`tempfile.mkstemp`) followed by atomic filesystem replacement (`os.replace`) to prevent state corruption during power or process interruption.

### 2.2 Frontend Architecture
* **Active Surface**: The active frontend is in `frontend/` (React 19 + TypeScript + Vite + Tailwind CSS 4 + React Router 7).
* **Vite Proxy & Base Path**: The SPA is hosted under `/app/` (`base: "/app/"` in `frontend/vite.config.ts`). In development, Vite proxies `/api`, `/docs`, and `/openapi.json` to the backend on `http://127.0.0.1:8000`.
* **Legacy Subsystems**: `frontend_legacy/` (Vanilla JS) and `web/` (React JS prototype) are deprecated. Do not add new features to `frontend_legacy` or `web`.
* **Chart Rendering**: Charting uses TradingView Lightweight Charts v5. Charts must be properly removed via `chart.remove()` on React unmounts to prevent detached DOM memory leaks and resize observer exceptions (verified in `frontend/src/components/ChartWidget.tsx`).

---

## 3. Coding Conventions Discovered From the Project

### 3.1 Python Backend Conventions
* **Type Annotations**: Use Python 3.10+ typing (`tuple[dict, List[SetupSignal]]`, `Optional[T]`, `| None`).
* **Input Sanitization**: All incoming tickers must be sanitized using `DataCleaner.sanitize_text()` or `_clean_ticker_param()`: uppercase, strip whitespace, strip NUL bytes (`\x00`), and enforce length constraints ($\le 64$ characters).
* **Setup Engine Contract**:
  - Every technical setup must inherit from `setups.base.BaseSetup` and implement `evaluate(df: pd.DataFrame, ticker: str = "") -> SetupSignal`.
  - Confidence must be bounded between `0.0` and `1.0`.
  - Signal must be normalized to `"bullish"`, `"bearish"`, or `"neutral"`.
  - The public `SetupEngine.evaluate_all()` contract returns `List[SetupSignal]`. To obtain regime data alongside setup signals, callers must invoke `SetupEngine.evaluate_with_regime()` (verified in `setups/engine.py`).
* **Exception Logging**: Use Python's standard `logging` with structured logger names (`trading.api`, `trading.db`, `trading.ml`, etc.). Do not print raw error traces to stdout in production routes; catch exceptions and return standardized JSON error bodies:
  `{"error": True, "detail": message, "message": message, "status_code": code}`.

### 3.2 Frontend React & TypeScript Conventions
* **Client-Side Linting**: The codebase uses `oxlint`. Components must adhere to React Hook rules (avoid synchronous `setState` in `useEffect` when avoidable, avoid reading `.current` refs directly during rendering).
* **Strict Type Safety**: TypeScript must compile cleanly without errors using `npx tsc -p tsconfig.app.json --noEmit`.
* **API Authentication Interception**: All client-side HTTP calls use Axios. Axios interceptors automatically attach the `X-API-Key` header from `localStorage` (`signal_desk_api_key`) and listen for `403 Forbidden` responses to dispatch the `signal-desk-auth-required` event (verified in `frontend/src/main.tsx`).

---

## 4. Files & Modules Requiring Extra Caution

| File / Module | Reason for Caution |
|---|---|
| `api/auth.py` | Governs rate limiting, reverse-proxy header trust, and API key verification. Changes here can inadvertently expose the system to unauthorized access or lock out valid clients. |
| `api/broker.py` | Contains live order execution scaffolding. Must remain locked in fail-closed mode until official exchange approval and dedicated broker tests are implemented. |
| `ml/risk_engine.py` | Calculates Kelly fraction, stop-loss, take-profit, and probability of ruin. Logic alterations directly impact capital preservation and position sizing. |
| `paper_trader.py` | Main autonomous daemon managing real-time portfolio balance, trade entries, exits, and kill-switch execution. |
| `models/models.py` & `models/init_db.py` | Defines TimescaleDB hypertables and primary key composite constraints. Schema modifications require coordinated migration and TimescaleDB hypertable adjustments. |
| `ml/assets.py` | Determines macro context and label calculations. Erroneous changes can cause lookahead bias or data misalignment across crypto/equity domains. |
| `frontend/src/components/ChartWidget.tsx` | Manages TradingView Lightweight Charts canvas instances and DOM resizing observers; sensitive to double-initialization in React 19 `StrictMode`. |

---

## 5. Things That Must Not Be Changed Without Explicit Approval

1. **SEBI Compliance Constraints**: No naked short options, no removal of `EXCHANGE_ALGO_ID` tagging, and no bypassing of the `WHITELISTED_IP` check in `api/broker.py`.
2. **Setup Engine Contract**: Do not alter the return types of `SetupEngine.evaluate_all()` or `SetupEngine.evaluate_with_regime()`, as multiple tests, background workers, and API endpoints rely on this exact signature.
3. **Database Schema Partitioning**: The composite primary keys for `ohlcv_bars` (`time`, `symbol_id`, `timeframe`) and `news_headlines` (`time`, `url`) are mandated by TimescaleDB hypertable mechanics. Do not alter these primary keys.
4. **Capital Constraints in Config**: Do not increase default `risk_per_trade_pct` above 0.05 or disable `max_portfolio_drawdown_pct`.
5. **Base URL and Route Basenames**: Do not change the frontend `/app/` base route or the API `/api/v1` prefix without updating both FastAPI static mounts and Vite proxy configurations.

---

## 6. Testing & Validation Expectations

Before committing any modifications or creating PRs, agents must execute the following validation ladder:

1. **Python Compilation**:
   ```powershell
   venv\Scripts\python -m compileall -q api backtest data ml models setups papertrade scripts tests paper_trader.py live_trader.py start.py conftest.py
   ```
   Must complete with zero errors.

2. **Frontend Type Check**:
   ```powershell
   cd frontend
   npx tsc -p tsconfig.app.json --noEmit
   ```
   Must pass with zero type errors.

3. **Frontend Production Build**:
   ```powershell
   cd frontend
   npm run build
   ```
   Must build successfully into `frontend/dist`.

4. **Python Automated Test Suite**:
   ```powershell
   venv\Scripts\pytest -q tests/test_multi_asset.py tests/test_phase2_adversarial_sdet.py tests/test_phase2_security.py tests/test_replay_isolation.py tests/test_swing_toolkit.py
   ```
   All offline unit and regression test suites must pass. Note: Tests requiring live PostgreSQL connection will fail if Docker container `trading_timescaledb` is not running.

---

## 7. Deployment & Release Precautions

* **Default Production Security**: The configuration defaults `ENVIRONMENT=production`. In production, if `API_KEY` is not explicitly set, the server refuses to boot (`RuntimeError` in `validate_auth_configuration()`).
* **Docker Container Dependencies**: The TimescaleDB service (`docker-compose.yml`) strictly requires `POSTGRES_PASSWORD` in `.env`. Never run with empty or default database passwords.
* **Port Isolation**: Docker publishes PostgreSQL on `127.0.0.1:5432`, binding only to localhost. Do not expose this port to `0.0.0.0`.
* **Static Assets**: FastAPI serves the pre-compiled frontend from `frontend/dist` mounted at `/app`. Any frontend changes must be compiled via `npm run build` before being deployed to production environments.

---

## 8. Security-Sensitive Areas

1. **API Key Authentication**:
   - Compares secret values using `secrets.compare_digest` to prevent timing attacks.
   - Accepts authentication via `X-API-Key` or `Authorization: Bearer <key>`.
   - Never accept credentials via URL query parameters (legacy query parameters are stripped on frontend boot).
2. **Reverse Proxy Trust**:
   - Client IP extraction in `api/auth.py` only trusts `X-Forwarded-For` if the immediate client host is a verified loopback or private subnet (`10.x`, `172.x`, `192.168.x`).
3. **Rate Limiting**:
   - Namespaced per `(client_ip, path, quota)` with automatic eviction via `TTLCache(maxsize=100000, ttl=60)`.
4. **Input Boundary Sanitization**:
   - All symbol lookups, period parameters, and strategy condition counts are explicitly bounded (e.g., maximum 50 conditions per strategy).
5. **Credential Masking**:
   - Database connection strings are masked before being returned in `/db-check` or written to log files.
   - Telegram bot tokens in `api/notifier.py` are stripped from exception messages before logging.

---

## 9. User Approval Requirements

Future agents must pause and seek explicit USER approval before performing any of the following actions:
1. Connecting live broker credentials or changing `BROKER_MODE` to `live`.
2. Altering live trading capital allocations or risk parameters in `config.json`.
3. Executing database drop, truncate, or schema migration scripts on production databases.
4. Upgrading third-party dependencies with breaking changes (e.g., major version upgrades to pandas, SQLAlchemy, or React).
5. Removing deprecated modules (`frontend_legacy/` or `web/`).

---

## 10. Summary Distinction: Existing Conventions vs. Recommended Rules

| Convention / Rule | Classification | Source / Verification |
|---|---|---|
| Defaulting `ENVIRONMENT` to `production` | **Existing Convention** | `api/config.py` line 12 |
| `API_KEY` timing-safe comparison | **Existing Convention** | `api/auth.py` line 105 |
| Five core setups contract in `SetupEngine` | **Existing Convention** | `setups/engine.py` line 30 |
| Kelly sizing capped at 2% risk | **Existing Convention** | `ml/risk_engine.py` line 5 |
| Options buying only (no naked selling) | **Existing Convention** | `ml/options_engine.py` line 11 |
| Unification of batch model and continuous ML bundle deployment | **Recommended Rule** | Not yet implemented; documented in technical debt |
| Redis-backed rate limiting for multi-worker Uvicorn deployment | **Recommended Rule** | Currently in-memory `TTLCache`; needed if scaling workers |
| Consolidation of legacy frontend directories (`frontend_legacy`, `web`) | **Recommended Rule** | Deprecated directories remain in workspace |
