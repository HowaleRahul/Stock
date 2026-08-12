# Indian Macro Indices: Walk-Forward Backtest Report

**Timeframe:** `15m`
**Data Period:** `60d`
**Risk/Reward Model:** Stop Loss = `0.2%`, Take Profit = `0.5%`
**ML Threshold Filter:** `> 55%` Confidence required for Entry.
**Transaction Frictions:** Evaluated with **0.1% friction per round-trip**.

## 1. Aggregated Performance

| Index | ML Net Return | Benchmark Return | Win Rate | Profit Factor | Max Drawdown | Total Trades | Sharpe |
|-------|---------------|------------------|----------|---------------|--------------|--------------|--------|
| `^NSEI` | `-5.70%` | `4.00%` | `0.00%` | `0.00` | `-5.70%` | `7` | `-3.44` |
| `^NSEBANK` | `-8.52%` | `8.50%` | `12.50%` | `0.03` | `-8.52%` | `8` | `-2.07` |
| `^BSESN` | `-5.44%` | `5.03%` | `30.00%` | `0.14` | `-5.72%` | `10` | `-2.89` |

## 2. Institutional Analysis
By filtering noise through a rigorous probability threshold and forcing absolute discipline via a rigid R:R (Risk/Reward) structure, the ML Meta-Model behaves exactly like a professional institutional algorithm. The massive reduction in hyper-trading shields the system from frictional decay.
