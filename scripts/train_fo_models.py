"""
Train fresh Machine Learning models from scratch for Indian F&O Trading.
Covers Scalp (5m, 15m) and Swing (1h, 1d) on NIFTY, BANKNIFTY, and SENSEX.
Outputs trained bundles to ml/registry/ and ml/models/.
"""
import os
import sys
from pathlib import Path
from typing import Tuple, Dict, Any, List

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import logging
import joblib
import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score

from setups.engine import SetupEngine
from ml.assets import asset_flags, barrier_config, classify_ticker
from ml.features import enrich_with_macro_and_options, enrich_with_psychology_features, generate_triple_barrier_labels

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("train_fo_models")

TARGET_TICKERS = ["^NSEI", "^NSEBANK", "^BSESN"]
TIMEFRAMES = [
    {"tf": "5m", "period": "60d", "tp_atr": 1.5, "sl_atr": 0.8, "max_hold": 15},
    {"tf": "15m", "period": "60d", "tp_atr": 1.8, "sl_atr": 0.9, "max_hold": 25},
    {"tf": "1h", "period": "730d", "tp_atr": 2.0, "sl_atr": 1.0, "max_hold": 40},
    {"tf": "1d", "period": "5y", "tp_atr": 2.0, "sl_atr": 1.0, "max_hold": 20},
]

REGISTRY_DIR = BASE_DIR / "ml" / "registry"
MODELS_DIR = BASE_DIR / "ml" / "models"
REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
MODELS_DIR.mkdir(parents=True, exist_ok=True)


def extract_features_and_labels(ticker: str, tf_cfg: dict) -> Tuple[pd.DataFrame, pd.Series]:
    tf = tf_cfg["tf"]
    period = tf_cfg["period"]
    logger.info(f"Downloading historical data for {ticker} ({period} at {tf})...")
    df = yf.download(ticker, period=period, interval=tf, progress=False)
    if df.empty or len(df) < 60:
        logger.warning(f"Insufficient data for {ticker} at {tf} (got {len(df)} rows)")
        return pd.DataFrame(), pd.Series(dtype=int)

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    df = df.dropna(subset=["close", "high", "low", "open"])

    asset_class = "IN_INDEX_FO"
    try:
        df = enrich_with_macro_and_options(df, ticker, asset_class=asset_class)
        df = enrich_with_psychology_features(df)
    except Exception as e:
        logger.warning(f"Macro/Psychology enrichment error for {ticker}: {e}")

    # Compute ATR
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    df['atr'] = true_range.rolling(14, min_periods=1).mean()

    # Generate triple barrier labels
    labels = generate_triple_barrier_labels(
        df,
        tp_atr_mult=tf_cfg["tp_atr"],
        sl_atr_mult=tf_cfg["sl_atr"],
        max_hold_bars=tf_cfg["max_hold"],
    )

    engine = SetupEngine()
    features = []
    clean_labels = []

    def _sig_to_num(sig: str) -> int:
        s = sig.lower()
        return 1 if s == "bullish" else (-1 if s == "bearish" else 0)

    min_warmup = min(60, len(df) // 3)
    step = 1 if len(df) <= 1500 else max(1, len(df) // 1000)

    for i in range(min_warmup, len(df), step):
        window_df = df.iloc[max(0, i - 200):i + 1]
        label = labels[i]

        regime_data, setups = engine.evaluate_with_regime(window_df, ticker=ticker)

        r_val = 0
        r_str = str(regime_data.get("regime", "")).lower()
        if "bull" in r_str:
            r_val = 1
        elif "bear" in r_str or "crash" in r_str:
            r_val = -1

        f = {
            "regime_val": r_val,
            "regime_adx": float(regime_data.get("adx", 0.0)),
            "macro_spx_ret": float(df['macro_spx_ret'].iloc[i]) if 'macro_spx_ret' in df.columns else 0.0,
            "macro_usdinr_ret": float(df['macro_usdinr_ret'].iloc[i]) if 'macro_usdinr_ret' in df.columns else 0.0,
            "macro_vix": float(df['macro_vix'].iloc[i]) if 'macro_vix' in df.columns else 15.0,
            "macro_btc_volume_ret": float(df['macro_btc_volume_ret'].iloc[i]) if 'macro_btc_volume_ret' in df.columns else 0.0,
            "opt_delta": float(df['opt_delta'].iloc[i]) if 'opt_delta' in df.columns else 0.5,
            "opt_gamma": float(df['opt_gamma'].iloc[i]) if 'opt_gamma' in df.columns else 0.0,
            "psych_fomo_streak": float(df['psych_fomo_streak'].iloc[i]) if 'psych_fomo_streak' in df.columns else 0.0,
            "psych_panic_index": float(df['psych_panic_index'].iloc[i]) if 'psych_panic_index' in df.columns else 0.0,
            "psych_dist_to_round": float(df['psych_dist_to_round'].iloc[i]) if 'psych_dist_to_round' in df.columns else 0.0,
            "psych_session_phase": float(df['psych_session_phase'].iloc[i]) if 'psych_session_phase' in df.columns else 0.0,
            "atr": float(df['atr'].iloc[i]) if 'atr' in df.columns else 1.0,
        }

        # Include F&O asset flags
        f.update(asset_flags(asset_class))

        for s in setups:
            f[f"{s.name}_sig"] = _sig_to_num(s.signal)
            f[f"{s.name}_conf"] = float(s.confidence)

        features.append(f)
        clean_labels.append(label)

    feat_df = pd.DataFrame(features)
    # Fill any remaining NaNs
    feat_df = feat_df.fillna(0.0)
    label_ser = pd.Series(clean_labels)
    return feat_df, label_ser


def train_all_timeframes():
    logger.info("Starting fresh F&O Model Training from scratch across all timeframes...")

    all_timeframe_datasets = {}

    for tf_cfg in TIMEFRAMES:
        tf = tf_cfg["tf"]
        logger.info(f"\n--- Collecting F&O Training Data for Timeframe: {tf} ---")
        combined_X = []
        combined_y = []

        for ticker in TARGET_TICKERS:
            X, y = extract_features_and_labels(ticker, tf_cfg)
            if not X.empty and len(y) > 0:
                combined_X.append(X)
                combined_y.append(y)

        if combined_X:
            full_X = pd.concat(combined_X, ignore_index=True)
            full_y = pd.concat(combined_y, ignore_index=True)
            all_timeframe_datasets[tf] = (full_X, full_y)
            logger.info(f"Dataset for {tf}: {len(full_X)} samples across {full_X.shape[1]} features.")
        else:
            logger.warning(f"No samples collected for {tf}")

    # Train and save registry models for each timeframe
    for tf, (X, y) in all_timeframe_datasets.items():
        logger.info(f"\nTraining Classifier for {tf} ({len(X)} rows)...")

        # Split train/test
        split_idx = int(len(X) * 0.8)
        X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
        y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)

        clf = LogisticRegression(class_weight="balanced", max_iter=2000, solver="lbfgs")
        clf.fit(X_train_scaled, y_train)

        train_acc = accuracy_score(y_train, clf.predict(X_train_scaled))
        test_acc = accuracy_score(y_test, clf.predict(X_test_scaled)) if len(y_test) > 0 else train_acc
        logger.info(f"Model {tf} -> Train Acc: {train_acc:.3f}, Test Acc: {test_acc:.3f}")

        # Save to registry
        model_path = REGISTRY_DIR / f"model_{tf}.pkl"
        payload = {
            "model": clf,
            "scaler": scaler,
            "features": list(X.columns),
            "feature_version": "v2",
            "asset_class": "IN_INDEX_FO",
            "timeframe": tf,
            "accuracy": float(test_acc),
        }
        joblib.dump(payload, model_path)
        logger.info(f"Saved: {model_path}")

    # Also train the master continuous brain bundle on 1h/1d combined data
    logger.info("\n--- Training Master Continuous Brain Bundle ---")
    if "1h" in all_timeframe_datasets:
        master_X, master_y = all_timeframe_datasets["1h"]
    elif "1d" in all_timeframe_datasets:
        master_X, master_y = all_timeframe_datasets["1d"]
    else:
        master_X, master_y = list(all_timeframe_datasets.values())[0]

    master_scaler = StandardScaler()
    master_X_scaled = master_scaler.fit_transform(master_X)

    master_sgd = SGDClassifier(loss="log_loss", max_iter=2000, random_state=42)
    master_sgd.fit(master_X_scaled, master_y)

    master_bundle = {
        "model": master_sgd,
        "scaler": master_scaler,
        "features": list(master_X.columns),
        "feature_version": "v2",
        "asset_class": "IN_INDEX_FO",
        "timeframe": "1h",
    }
    master_bundle_path = MODELS_DIR / "continuous_brain_bundle.pkl"
    joblib.dump(master_bundle, master_bundle_path)
    logger.info(f"Saved Master Continuous Brain Bundle: {master_bundle_path}")

    joblib.dump(master_sgd, MODELS_DIR / "continuous_brain.pkl")
    joblib.dump(master_scaler, MODELS_DIR / "scaler.pkl")
    logger.info("Saved continuous_brain.pkl and scaler.pkl.")

    logger.info("\nALL F&O MODELS TRAINED AND SAVED SUCCESSFULLY FROM SCRATCH!")


if __name__ == "__main__":
    train_all_timeframes()
