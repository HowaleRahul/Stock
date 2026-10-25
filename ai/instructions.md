# AI Instructions & Developer Guardrails

This document establishes operational directives, architectural constraints, and coding conventions that all future AI agents and human contributors must follow when working on the **Personal AI-Assisted Trading System (Signal Desk)**.

---

## 1. Project-Specific Rules

### 1.0 Compulsory Project Brain Synchronization (Strictly Enforced Across All Sessions)
* **Always Update the Brain Without Fail**: In ANY and ALL chats or sessions on this project, whenever ANY change, bug fix, feature addition, refactoring, dependency update, file removal, or architectural adjustment is made to this codebase, the project brain files in `ai/` (`current-state.md`, `decisions.md`, `known-issues.md`, `instructions.md`) and `REVIEW_LOG.md` **MUST** be updated immediately and thoroughly without fail.
* **Non-Negotiable Pre-Condition**: No update, goal, prompt, or task is considered complete until all affected components, architectural decisions, and verification steps are accurately reflected in the brain documentation.
* **Definition of Done**: No coding task, audit, or refactoring is finished until the brain documentation has been verified and updated to mirror the exact current reality of the codebase.

### 1.1 Non-Negotiable Operational Safety
* **Fail-Closed Financial Execution**: Never allow automated orders or broker connections without an explicit `ENVIRONMENT=LIVE` setting, valid authenticated broker adapters, and static IP whitelisting. By default, live order injection throws a `RuntimeError` (verified in `api/broker.py` line 131).
* **Derivatives Execution Modes**: The derivatives engine supports long options (`BUY_OPTIONS`), directional option writing (`SELL_OPTIONS`), defined-risk credit spreads (`CREDIT_SPREAD`), and index futures (`FUTURES`). Naked unhedged options selling without exchange SPAN + Exposure margin allocation is prohibited. Retail accounts utilize defined-risk credit spreads (Bull Put / Bear Call) where maximum loss is strictly capped by the wing width.
* **Positive Theta Notation**: Option selling and credit spreads harvest positive theta decay ($+\Theta > 0$ or $+₹\text{Theta/day}$), representing an income stream rather than a holding friction.
* **Risk Envelope Enforcement**: The risk engine strictly enforces maximum risk per trade ($\le 2\%$, configurable up to $5\%$ ceiling) and minimum Risk-to-Reward ratio ($\ge 1.5:1$). Trades violating these constraints must be rejected and logged to the journal with explicit rejection reasons (verified in `ml/risk_engine.py`).
* **Kill-Switch Thresholds**: If total Mark-to-Market (MTM) drawdown reaches or exceeds `max_portfolio_drawdown_pct` (default 10%), all trading activity is locked, a critical alert is dispatched via `api/notifier.py`, and the status transitions to `HALTED_DRAWDOWN` (verified in `paper_trader.py`).

### 1.2 Sole Specialization in Indian Stock Market Futures & Options (F&O)
* **Exclusive F&O Asset Class**: The system is specialized WHOLE AND SOLE in Indian Stock Market Futures & Options (`IN_INDEX_FO`). Cash equities, foreign equities, and crypto have been permanently removed. Any attempt to classify or trade an unsupported asset class must fail closed with a `ValueError` (verified in `ml/assets.py`).
* **Supported Underlyings & Lot Sizes**:
  - `NIFTY 50` (`^NSEI`): Lot size 25, strike interval 50, expiry Thursday.
  - `BANK NIFTY` (`^NSEBANK`): Lot size 15, strike interval 100, expiry Wednesday.
  - `BSE SENSEX` (`^BSESN`): Lot size 10, strike interval 100, expiry Friday.
  - `FIN NIFTY` (`FINNIFTY`): Lot size 25, strike interval 50, expiry Tuesday.
  - `MIDCAP NIFTY` (`MIDCPNIFTY`): Lot size 50, strike interval 25, expiry Monday.
* **Dual Scalp & Swing Framework**:
  - Scalp trading operates on `5m` (hold $\le 15$ bars) and `15m` (hold $\le 25$ bars) with rapid momentum targets.
  - Swing trading operates on `1h` (hold $\le 40$ bars) and `1d` (hold $\le 20$ bars) with wide trailing stops.
* **F&O Execution Isolation**: All trade orders must pass through `DerivativeEngine.generate_derivative_plan()`. Under micro/small capital ($\le ₹1,00,000$), it buys Call/Put options (`CE`/`PE`) or utilizes defined-risk Credit Spreads; under institutional capital ($\ge ₹5,00,000$) with SPAN margin clearance, it can write options or allocate linear Index Futures.
* **SEBI Compliance**: Naked unhedged options selling without full SPAN margin coverage is strictly prohibited. Intraday MIS trades must auto-square-off at 15:15 IST.

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
* **Legacy Subsystems**: `frontend_legacy/` (Vanilla JS) and `web/` (React JS prototype) were purged during repository consolidation (Pass 13). Only `frontend/` is maintained.
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
| `api/broker.py` | Contains live order execution adapters (`BrokerAPI`, `SmartAPIBroker`). Must remain locked in fail-closed mode unless `BROKER_MODE=live`, `WHITELISTED_IP`, and official exchange algo ID are verified. |
| `data/fx_fetcher.py` & `data/news_fetcher.py` | Governs external public API integrations (ECB Frankfurter FX & Indian financial press RSS feed). Must always maintain graceful fallback paths without blocking the event loop. |
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
   # Run all 235 offline unit tests hermetically without requiring Docker/PostgreSQL:
   venv\Scripts\pytest -m "not database" -q

   # Run full 254 unit and database integration tests when Docker is online:
   venv\Scripts\pytest -q
   ```
   All hermetic unit tests must pass 100% offline. Full integration tests run automatically when `trading_timescaledb` is healthy.

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
5. Removing or renaming active trading setups, risk caps, or database tables.

---

## 10. Summary Distinction: Existing Conventions vs. Recommended Rules

| Convention / Rule | Classification | Source / Verification |
|---|---|---|
| Defaulting `ENVIRONMENT` to `production` | **Existing Convention** | `api/config.py` line 12 |
| `API_KEY` timing-safe comparison | **Existing Convention** | `api/auth.py` line 105 |
| Five core setups contract in `SetupEngine` | **Existing Convention** | `setups/engine.py` line 30 |
| Kelly sizing capped at 2% risk | **Existing Convention** | `ml/risk_engine.py` line 5 |
| Options buying only (no naked selling) | **Existing Convention** | `ml/options_engine.py` line 11 |
| Unification of batch model and continuous ML bundle deployment | **Existing Convention** | `ml/ensemble.py` Pass 13 |
| Hermetic test suite execution via `@pytest.mark.database` | **Existing Convention** | `conftest.py` & `pytest.ini` Pass 13 |
| Consolidated single React 19 SPA | **Existing Convention** | `frontend/` (legacy frontends deleted) |
| Redis-backed rate limiting for multi-worker Uvicorn deployment | **Recommended Rule** | `REDIS_URL` setting added; Redis adapter next |
