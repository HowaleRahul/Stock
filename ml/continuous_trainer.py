import time
import random
import logging
import os
import joblib
import pandas as pd
import numpy as np
import yfinance as yf
from sklearn.linear_model import SGDClassifier
from sklearn.preprocessing import StandardScaler
from ml.features import enrich_with_macro_and_options, enrich_with_psychology_features, generate_triple_barrier_labels
from ml.assets import TARGETS, asset_flags, barrier_config
from setups.engine import SetupEngine

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ContinuousBrain")

MODEL_PATH = "ml/models/continuous_brain.pkl"
SCALER_PATH = "ml/models/scaler.pkl"
BUNDLE_PATH = "ml/models/continuous_brain_bundle.pkl"

TARGET_CLASSES = TARGETS

# Configuration for multi-timeframe swing trading
# We remove 5m and 15m as transaction friction (STT, slippage) kills scalping alpha in India.
# We focus purely on Swing Trading (1h, 1d) with ATR-scaled targets.
TIMEFRAME_CONFIGS = [
    {"tf": "1h", "period": "730d", "tp_atr": 2.0, "sl_atr": 1.0, "max_hold": 40},
    {"tf": "1d", "period": "5y", "tp_atr": 2.0, "sl_atr": 1.0, "max_hold": 20}
]

def load_or_create_model():
    os.makedirs("ml/models", exist_ok=True)
    if os.path.exists(BUNDLE_PATH):
        bundle = joblib.load(BUNDLE_PATH)
        model = bundle["model"]
        scaler = bundle["scaler"]
        logger.info("Loaded existing AI Brain from disk.")
    else:
        model = SGDClassifier(loss='log_loss')
        scaler = StandardScaler()
        logger.info("Created NEW AI Brain.")
    return model, scaler

def save_model(model, scaler, feature_names, asset_class, timeframe):
    tmp_bundle_path = BUNDLE_PATH + ".tmp"
    joblib.dump({
        "model": model,
        "scaler": scaler,
        "features": list(feature_names),
        "feature_version": "v2",
        "asset_class": asset_class,
        "timeframe": timeframe,
    }, tmp_bundle_path)
    os.replace(tmp_bundle_path, BUNDLE_PATH)
    logger.info("Saved upgraded AI Brain to disk.")

def _reset_if_feature_schema_changed(model, scaler, X, feature_names=None):
    """Avoid silently applying a persisted model to a different feature set."""
    expected_count = getattr(scaler, "n_features_in_", None)
    persisted_names = getattr(scaler, "feature_names_in_", None)
    names_match = persisted_names is None or list(persisted_names) == list(feature_names or X.columns)
    if expected_count is None or (expected_count == X.shape[1] and names_match):
        return model, scaler
    logger.warning(
        "Feature schema changed from %s to %s columns; resetting the incremental model.",
        expected_count, X.shape[1],
    )
    return SGDClassifier(loss="log_loss"), StandardScaler()

def generate_features_for_ticker(ticker, tf_config, asset_class="IN_EQUITY"):
    logger.info(f"Downloading {ticker} history ({tf_config['period']} at {tf_config['tf']})...")
    df = yf.download(ticker, period=tf_config["period"], interval=tf_config["tf"], progress=False)
    if df.empty or len(df) < 100:
        return None, None
    
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
        
    df.columns = [c.lower() for c in df.columns]
    
    try:
        df = enrich_with_macro_and_options(df, ticker, asset_class=asset_class)
        df = enrich_with_psychology_features(df)
    except Exception as e:
        logger.error(f"Macro fetch failed: {e}")
        return None, None
        
    labels = generate_triple_barrier_labels(
        df, 
        tp_atr_mult=tf_config["tp_atr"], 
        sl_atr_mult=tf_config["sl_atr"], 
        max_hold_bars=tf_config["max_hold"]
    )
    
    engine = SetupEngine()
    
    X_rows = []
    y_labels = []
    
    def _signal_to_num(signal: str) -> int:
        if signal.lower() == "bullish": return 1
        if signal.lower() == "bearish": return -1
        return 0
        
    def _regime_to_num(regime: str) -> int:
        r = regime.lower()
        if r == "trending-bullish": return 1
        if r == "trending-bearish": return -1
        if r == "trending": return 1
        if r == "crash": return -1
        return 0
    
    min_periods = 100
    for i in range(min_periods, len(df)):
        window_df = df.iloc[max(0, i - 300):i+1]
        label = labels[i]
        
        regime_data, setups = engine.evaluate_with_regime(window_df)
        
        feats = {}
        feats["regime_val"] = _regime_to_num(regime_data.get("regime", "neutral"))
        feats["regime_adx"] = float(regime_data.get("adx", 0.0))
        
        for s in setups:
            feats[f"{s.name}_sig"] = _signal_to_num(s.signal)
            feats[f"{s.name}_conf"] = float(s.confidence)
        
        feats['macro_vix'] = df['macro_vix'].iloc[i]
        feats['macro_spx_ret'] = df['macro_spx_ret'].iloc[i]
        feats['macro_usdinr_ret'] = df['macro_usdinr_ret'].iloc[i]
        feats['macro_btc_volume_ret'] = df['macro_btc_volume_ret'].iloc[i]
        feats['opt_delta'] = df['opt_delta'].iloc[i]
        feats['opt_gamma'] = df['opt_gamma'].iloc[i]
        
        feats['psych_fomo_streak'] = df['psych_fomo_streak'].iloc[i]
        feats['psych_panic_index'] = df['psych_panic_index'].iloc[i]
        feats['psych_dist_to_round'] = df['psych_dist_to_round'].iloc[i]
        feats['psych_session_phase'] = df['psych_session_phase'].iloc[i]
        feats['atr'] = df['atr'].iloc[i]
        
        tf_mapping = {"1h": 0.5, "1d": 1.0}
        feats['tf_hint'] = tf_mapping.get(tf_config["tf"], 1.0)
        
        feats.update(asset_flags(asset_class))

        X_rows.append(feats)
        y_labels.append(label)
        
    X = pd.DataFrame(X_rows)
    # Drop rows with NaN values to prevent SGDClassifier crash
    valid_mask = ~X.isna().any(axis=1)
    X = X[valid_mask]
    y_labels = [y for i, y in enumerate(y_labels) if valid_mask.iloc[i]]
    
    return X, y_labels

def run_training_loop(stop_event=None, log_callback=None):
    def log(msg):
        logger.info(msg)
        if log_callback:
            log_callback(msg)

    log("==================================================")
    log("STARTING CONTINUOUS TRAINING ENGINE (ALPHAZERO MODE)")
    log("==================================================")
    
    model, scaler = load_or_create_model()
    classes = np.array([-1, 0, 1])
    cycles = 0
    while True:
        if stop_event and stop_event.is_set():
            log("🛑 STOP SIGNAL RECEIVED. Halting Training Engine.")
            break
            
        cycles += 1
        asset_class = random.choice(list(TARGET_CLASSES.keys()))
        ticker = random.choice(TARGET_CLASSES[asset_class])

        base_config = random.choice(TIMEFRAME_CONFIGS)
        # Crypto may use the same timeframes, but its barriers account for
        # the materially higher volatility.
        tf_config = {**base_config, **barrier_config(asset_class, base_config["tf"])}
        
        log(f"[CYCLE {cycles}] Target: {ticker} ({asset_class}) | Timeframe: {tf_config['tf']}")
        
        X, y = generate_features_for_ticker(ticker, tf_config, asset_class)
        
        if X is None or len(X) == 0:
            log(f"Not enough data for {ticker}. Skipping...")
            continue
            
        log(f"Simulated {len(X)} trades. Win: {y.count(1)}, Loss: {y.count(-1)}, Timeout: {y.count(0)}")
        
        model, scaler = _reset_if_feature_schema_changed(model, scaler, X, X.columns)
        # 1. Incrementally update the Scaler with the new data distribution
        scaler.partial_fit(X)
        
        # 2. Transform the data
        X_scaled = scaler.transform(X)
        
        # 3. Incrementally teach the ML Model
        log("Injecting simulated outcomes into AI Brain (partial_fit)...")
        model.partial_fit(X_scaled, y, classes=classes)
        
        # Save every 3 cycles
        if cycles % 3 == 0:
            save_model(model, scaler, X.columns, asset_class, tf_config["tf"])
            log("💾 Model Checkpoint Saved.")
            
        # Brief pause to avoid destroying APIs
        time.sleep(60)

def main():
    run_training_loop()

if __name__ == "__main__":
    main()
