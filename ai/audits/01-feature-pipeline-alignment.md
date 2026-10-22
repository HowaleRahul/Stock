# Audit 01: Feature Pipeline Alignment & ML Model Lifecycle

**Audit Date**: October 2026  
**Auditor**: Principal ML Systems Architect & Senior SDET  
**Status**: Critical Flaw Identified & Complete Remediation Specified  
**Affected Modules**: `ml/ensemble.py`, `ml/train.py`, `ml/continuous_trainer.py`, `ml/features.py`, `ml/registry/`

---

## 1. Executive Summary & Empirical Verification

During adversarial execution and code tracing of the machine learning inference path, we discovered that **100% of live and paper trading inferences currently fail to utilize the trained machine learning models**, silently degrading to unweighted heuristic voting across all timeframes.

### 1.1 Empirical Verification via Direct Execution
Executing `EnsembleModel.predict` against the current model registry produces the following outcomes:

1. **Daily Timeframe (`1d`)**:
   ```
   Command: python -c "from ml.ensemble import EnsembleModel; ...; EnsembleModel('1d').predict(...)"
   Output:
   Model feature contract is incomplete: ['macro_spx_ret', 'macro_usdinr_ret', 'macro_vix', 'macro_btc_volume_ret', 'opt_delta', 'opt_gamma']
   pred: {'signal': 'neutral', 'probability': 0.0, 'drivers': [], 'alternative_scenario': 'Awaiting market momentum to build.', 'model_version': 'fallback_heuristic'}
   ```
   *Result*: The model in `ml/registry/model_1d.pkl` expects 21 features, but `EnsembleModel.predict` only constructs 15 features. The 6 missing macro features cause an immediate fail-closed fallback to `fallback_heuristic`.

2. **Intraday Timeframes (`15m`, `1h`, `5m`)**:
   ```
   Command: python -c "from ml.ensemble import EnsembleModel; ...; EnsembleModel('1h').predict(...)"
   Output:
   Ignoring registry model without compatible scaler metadata.
   pred: {'signal': 'neutral', 'probability': 0.0, 'drivers': [], 'alternative_scenario': 'Awaiting market momentum to build.', 'model_version': 'fallback_heuristic'}
   ```
   *Result*: `model_15m.pkl`, `model_1h.pkl`, and `model_5m.pkl` were serialized in early development phases without a `StandardScaler` object and without `asset_class` metadata. In `ml/ensemble.py` lines 89–92, `self.scaler is None` triggers an immediate fallback to `fallback_heuristic`.

3. **Continuous Online Brain (`continuous_brain_bundle.pkl`)**:
   `ml/continuous_trainer.py` continuously updates `ml/models/continuous_brain_bundle.pkl` with a 27-feature SGD model. However, **no module in the entire repository ever loads or reads this bundle for live or paper trading**. `EnsembleModel` exclusively attempts to load static files from `ml/registry/`.

---

## 2. In-Depth Root Cause Analysis

### 2.1 The Three Incompatible Feature Universes
The codebase contains three distinct, mutually incompatible feature schemas:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        FEATURE SCHEMA DRIFT                            │
├────────────────────────────────┬───────────────────┬───────────────────┤
│ Universe A: Legacy Registry   │ Universe B: Batch │ Universe C: Online│
│ (model_15m, 1h, 5m)            │ Training (1d)     │ Continuous Brain  │
├────────────────────────────────┼───────────────────┼───────────────────┤
│ 28 Features:                   │ 21 Features:      │ 27 Features:      │
│ • regime_val, regime_adx       │ • regime_val, adx │ • regime_val, adx │
│ • 14 Setup Signals & Confs:    │ • 6 Macro/Greeks  │ • 5 Setup Signals │
│   - MA Crossover               │ • 3 Asset Flags   │ • 6 Macro/Greeks  │
│   - RSI                        │ • 5 Core Setups   │ • 5 Psych Features│
│   - MACD                       │                   │ • atr             │
│   - Bollinger Bands            │                   │ • tf_hint         │
│   - S/R Breakout               │                   │ • 3 Asset Flags   │
│   - Candlestick Patterns       │                   │                   │
│   - VWAP & Volume              │                   │                   │
│   - Fibonacci Retracement      │                   │                   │
│   - Ichimoku Cloud             │                   │                   │
│   - Chart Patterns             │                   │                   │
│   - News Sentiment (NLP)       │                   │                   │
│   - Fundamentals Valuation     │                   │                   │
│   - Options PCR                │                   │                   │
├────────────────────────────────┼───────────────────┼───────────────────┤
│ Scaler: None                   │ Scaler: Present   │ Scaler: Present   │
│ Asset: None                    │ Asset: IN_EQUITY  │ Asset: IN_EQUITY  │
└────────────────────────────────┴───────────────────┴───────────────────┘
```

### 2.2 Feature Construction Asymmetry in `EnsembleModel.predict`
In `ml/ensemble.py` (lines 67–87), `EnsembleModel.predict` only constructs:
1. `regime_val` (integer -1, 0, 1)
2. `regime_adx` (float)
3. Asset flags (`feat_is_in_equity`, `feat_is_us_equity`, `feat_is_crypto`)
4. Core setup signals and confidences for whatever setups are passed in.

It **never** extracts macro features (`macro_vix`, `macro_spx_ret`, `macro_usdinr_ret`, `macro_btc_volume_ret`) or synthetic option Greeks (`opt_delta`, `opt_gamma`), because `predict()` is passed only `(regime_data, setups, setup_weights, asset_class)`. It does not receive the raw candlestick DataFrame (`df`), making it impossible to look up or calculate macro indicators or Greeks during inference.

---

## 3. Architectural Solution: Unified Feature Pipeline

To eliminate feature drift and ensure that inference models receive 100% of their required features, we specify a unified **`FeatureExtractor`** architecture.

### 3.1 Design Specification

```
                         ┌───────────────────────┐
                         │   Historical / Live   │
                         │    OHLCV DataFrame    │
                         └──────────┬────────────┘
                                    │
                                    ▼
                         ┌───────────────────────┐
                         │   FeatureExtractor    │
                         │  (Single Source of    │
                         │        Truth)         │
                         └──────────┬────────────┘
                                    │
      ┌─────────────────────────────┼─────────────────────────────┐
      │                             │                             │
      ▼                             ▼                             ▼
┌──────────────┐              ┌──────────────┐              ┌──────────────┐
│ Batch Train  │              │  Continuous  │              │  Production  │
│ (train.py)   │              │  (trainer)   │              │ (ensemble.py)│
└──────────────┘              └──────────────┘              └──────────────┘
```

1. **Centralized Feature Definition**:
   Define `CORE_FEATURE_NAMES` as the immutable feature contract:
   - `regime_val`, `regime_adx` (2)
   - Asset flags: `feat_is_in_equity`, `feat_is_us_equity`, `feat_is_crypto` (3)
   - 5 Core setup signals & confidences (10):
     - `MA Crossover_sig`, `MA Crossover_conf`
     - `RSI_sig`, `RSI_conf`
     - `MACD_sig`, `MACD_conf`
     - `Bollinger Bands_sig`, `Bollinger Bands_conf`
     - `S/R Breakout_sig`, `S/R Breakout_conf`
   - Total Core Signal Features = 15.

2. **Two-Tier Inference Compatibility**:
   - **Tier 1 (Core Signals Only - 15 features)**: For ultra-fast real-time tick evaluation where live macro data feeds are unavailable or delayed.
   - **Tier 2 (Full Macro & Greeks - 21 features)**: For 1h and 1d swing trade evaluation where the full historical OHLCV DataFrame and macro context are provided.

3. **Continuous Brain Promotion Pipeline**:
   Add an automated promotion hook in `ml/continuous_trainer.py`:
   - When continuous training reaches $N$ validation steps with positive out-of-sample accuracy ($> 55\%$) and ROC-AUC ($> 0.55$), the model artifact is saved directly to `ml/registry/model_{timeframe}.pkl`.
   - `EnsembleModel` watches the modification timestamp of its registry file and hot-reloads the weights without requiring a process restart.

---

## 4. Remediation Implementation Plan

### Step 1: Update `EnsembleModel.predict` to Support Optional DataFrame Input
Modify `ml/ensemble.py`:
```python
def predict(
    self,
    regime_data: Dict[str, Any],
    setups: List[Any],
    setup_weights: Dict[str, float] = None,
    asset_class: str = "IN_EQUITY",
    df: Optional[pd.DataFrame] = None, # Allow passing historical/macro df
) -> Dict[str, Any]:
```
If `df` is provided and the model expects macro/Greeks features, extract the latest bar's macro fields directly from `df`. If `df` is not provided, populate safe neutral defaults (e.g., `vix = 15.0`, `opt_delta = 0.5`, `ret = 0.0`) so the model contract is satisfied rather than dropping to heuristic fallback.

### Step 2: Retrain Registry Models with Verified Scaler Metadata
Re-run `ml/train.py` across all four timeframes (`1d`, `1h`, `15m`, `5m`) with:
1. Exact 5-setup contract.
2. Standardized `StandardScaler`.
3. Explicit `asset_class: IN_EQUITY`.
4. Consistent feature list.

### Step 3: Wire Continuous Brain into `EnsembleModel` Fallback
If no model exists in `ml/registry/model_{timeframe}.pkl`, `EnsembleModel` should check `ml/models/continuous_brain_bundle.pkl` before falling back to heuristic voting.
