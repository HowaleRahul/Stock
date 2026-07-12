# Event-Driven Backtester (`/backtest`)

## Responsibilities
- **Event-Driven Simulation:** Processes historical bars (`OHLCV`) and ticks sequentially to avoid lookahead bias.
- **Realistic Execution Friction:** Simulates exact brokerage charges (STT, GST, Stamp Duty, Brokerage fees for NSE Equity & F&O), bid-ask spread slippage, and latency delays.
- **Portfolio & Risk Management:** Tracks cash balance, margin requirements (`SPAN + Exposure` simulation for F&O), position sizing, and maximum drawdown limits.
- **Performance Analytics:** Emits detailed performance summaries including Sharpe Ratio, Sortino Ratio, Maximum Drawdown, Win/Loss Ratio, Profit Factor, and trade-by-trade logs.

## Roadmap Status
- **Phase 0:** Directory initialized, engine to be built in Phase 4.
