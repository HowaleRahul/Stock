# Personal AI-Assisted Trading System

An ML-driven decision-support system for equity, intraday, and F&O trading. This system **does not** attempt to predict markets with 100% certainty or act as a black box. Instead, it runs multiple independent technical, fundamental, and sentiment **setups**, combines their outputs via a trainable ensemble into a confidence-scored signal `[-1.0 to +1.0]`, and continuously adapts by paper-trading its own signals and reweighting itself based on real-world performance. Every recommendation is fully **explainable**.

---

## 🏗️ Phase-Wise Architecture & Roadmap

This project is built phase-by-phase. Each phase produces a concrete, working deliverable before moving to the next.

| Phase | Title | Deliverable & Status |
| :--- | :--- | :--- |
| **Phase 0** | **Foundations & Project Setup** | ✅ **Active** — Empty-but-running FastAPI backend, TimescaleDB/Postgres connection layer, secrets handling, target symbols, and repo skeleton. |
| **Phase 1** | **Data Pipeline & Storage** | ⏳ *Planned* — Multi-timeframe historical bar ingestion (1m, 5m, 15m, 1d), websocket ticker ingestion, TimescaleDB schema, automated cleaning. |
| **Phase 2** | **Feature Engineering & Setups** | ⏳ *Planned* — Independent setups emitting `-1.0 to +1.0` confidence signals (Trend Pullback, Breakout, Mean Reversion, Options Flow/OI). |
| **Phase 3** | **Ensemble & Explainability Engine** | ⏳ *Planned* — Trainable meta-model combining setup signals into unified trade scores with SHAP/feature contribution explanations. |
| **Phase 4** | **Event-Driven Backtest Engine** | ⏳ *Planned* — Realistic backtester accounting for slippage, brokerage, margin checks, and detailed risk metrics (Sharpe, Max Drawdown). |
| **Phase 5** | **Live Paper-Trading & Adaptive Loop** | ⏳ *Planned* — Execution loop against live feeds, virtual portfolio tracking, state machine, and continuous ensemble reweighting. |
| **Phase 6** | **Dashboard & UI** | ⏳ *Planned* — Web interface for real-time monitoring of confidences, setups, active paper trades, and equity curves. |

---

## 🗂️ Repository Directory Structure

```text
Stock/
├── api/             # FastAPI backend server, database connections, and REST endpoints
├── backtest/        # Event-driven historical backtester with realistic friction & metrics
├── data/            # Data ingestion pipelines, TimescaleDB models, and raw/processed storage
├── frontend/        # Web UI dashboard (Phase 6)
├── models/          # Trainable meta-ensemble models combining setup signals
├── papertrade/      # Live paper-trading execution engine & adaptive performance tracking
├── setups/          # Independent technical, fundamental, and sentiment trading setups
├── .env             # Local environment secrets & configuration (ignored by Git)
├── .env.example     # Template for environment configuration
├── docker-compose.yml # PostgreSQL + TimescaleDB containerized service
└── requirements.txt # Python package dependencies
```

---

## ⚙️ Quick Start & Setup (Phase 0)

### 1. Environment & Dependencies
Create and activate a Python virtual environment, then install dependencies:
```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Database Setup (PostgreSQL + TimescaleDB)
If Docker Desktop is running, start the TimescaleDB container:
```powershell
docker-compose up -d
```
*(Note: The application also supports an optional fallback/cloud Postgres instance configured via `.env`.)*

### 3. Run FastAPI Backend
Start the backend server using `uvicorn`:
```powershell
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
```

### 4. Verify System Status & DB Connection
- **API Health & Target Symbols:** Visit `http://127.0.0.1:8000/health`
- **Database Connection Check:** Visit `http://127.0.0.1:8000/db-check`

---

## 🔐 Secrets & Configuration Management

All sensitive credentials (API keys, database URLs, broker tokens) are managed strictly via environment variables (`.env` file using `pydantic-settings`). **Never hardcode API keys or credentials in source code.** See `.env.example` for the required configuration variables.
