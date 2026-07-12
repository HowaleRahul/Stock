# Live Paper-Trading & Adaptive Loop (`/papertrade`)

## Responsibilities
- **Live Paper Execution:** Connects to real-time websocket tick/bar feeds and executes virtual orders with realistic order fills and slippage.
- **Order State Machine:** Tracks virtual orders through valid lifecycles (`PENDING`, `SUBMITTED`, `FILLED`, `CANCELLED`, `REJECTED`, `CLOSED`).
- **Adaptive Reweighting Loop:** Continually monitors setup performance in live paper-trading. Setups producing false signals in current market regimes have their ensemble weights dynamically lowered; winning setups are reweighted upward.
- **Persistence & Audit:** Saves all virtual trade executions, fill timestamps, P&L, and ensemble confidence explainability logs into TimescaleDB.

## Roadmap Status
- **Phase 0:** Directory initialized, execution loop to be built in Phase 5.
