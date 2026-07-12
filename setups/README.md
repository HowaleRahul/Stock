# Trading Setups Module (`/setups`)

## Responsibilities
- **Modular Setups:** Each setup is an independent class implementing a common `BaseSetup` interface (`evaluate(data) -> SetupSignal`).
- **Standardized Output:** All setups must emit a normalized confidence score bounded between `-1.0` (Strong Short / Bearish) and `+1.0` (Strong Long / Bullish), along with a dictionary of `reasons` for explainability.
- **Initial Setups (Phase 2 Roadmap):**
  1. `TrendPullbackSetup`: EMA/VWAP pullback identification in strong directional trends.
  2. `BreakoutSetup`: Volume-confirmed resistance/support breakouts (`Donchian` / `Bollinger`).
  3. `MeanReversionSetup`: RSI/Z-score extreme deviations with mean reversion triggers.
  4. `OptionsFlowSetup`: Open Interest (OI) buildup, Max Pain shifts, and PCR divergences for F&O indices.

## Roadmap Status
- **Phase 0:** Directory initialized, base interfaces to be built in Phase 2.
