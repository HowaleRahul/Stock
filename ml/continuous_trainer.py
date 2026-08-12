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
from setups.engine import SetupEngine

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ContinuousBrain")

MODEL_PATH = "ml/models/continuous_brain.pkl"
SCALER_PATH = "ml/models/scaler.pkl"

TARGET_INDICES = [
    "^NSEI", "^NSEBANK"
]

# Configuration for multi-timeframe swing trading
# We remove 5m and 15m as transaction friction (STT, slippage) kills scalping alpha in India.
# We focus purely on Swing Trading (1h, 1d) with ATR-scaled targets.
TIMEFRAME_CONFIGS = [
    {"tf": "1h", "period": "730d", "tp_atr": 2.0, "sl_atr": 1.0, "max_hold": 40},
    {"tf": "1d", "period": "5y", "tp_atr": 2.0, "sl_atr": 1.0, "max_hold": 20}
]

def load_or_create_model():
    os.makedirs("ml/models", exist_ok=True)
    if os.path.exists(MODEL_PATH) and os.path.exists(SCALER_PATH):
        model = joblib.load(MODEL_PATH)
        scaler = joblib.load(SCALER_PATH)
        logger.info("Loaded existing AI Brain from disk.")
    else:
        model = SGDClassifier(loss='log_loss')
        scaler = StandardScaler()
        logger.info("Created NEW AI Brain.")
    return model, scaler

def save_model(model, scaler):
    joblib.dump(model, MODEL_PATH)
    joblib.dump(scaler, SCALER_PATH)
    logger.info("Saved upgraded AI Brain to disk.")

def generate_features_for_ticker(ticker, tf_config):
    logger.info(f"Downloading {ticker} history ({tf_config['period']} at {tf_config['tf']})...")
    df = yf.download(ticker, period=tf_config["period"], interval=tf_config["tf"], progress=False)
    if df.empty or len(df) < 100:
        return None, None
    
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
        
    df.columns = [c.lower() for c in df.columns]
    
    try:
        # This function fetches daily macro data and forward-fills it to align with intraday bars!
        df = enrich_with_macro_and_options(df, ticker)
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
        window_df = df.iloc[:i+1]
        label = labels[i]
        
        regime_data, setups = engine.evaluate_all(window_df)
        
        feats = {}
        feats["regime_val"] = _regime_to_num(regime_data.get("regime", "neutral"))
        feats["regime_adx"] = float(regime_data.get("adx", 0.0))
        
        for s in setups:
            feats[f"{s.name}_sig"] = _signal_to_num(s.signal)
            feats[f"{s.name}_conf"] = float(s.confidence)
        
        feats['macro_vix'] = df['macro_vix'].iloc[i]
        feats['macro_spx_ret'] = df['macro_spx_ret'].iloc[i]
        feats['macro_usdinr_ret'] = df['macro_usdinr_ret'].iloc[i]
        feats['opt_delta'] = df['opt_delta'].iloc[i]
        feats['opt_gamma'] = df['opt_gamma'].iloc[i]
        
        # Add Psychological Features
        feats['psych_fomo_streak'] = df['psych_fomo_streak'].iloc[i]
        feats['psych_panic_index'] = df['psych_panic_index'].iloc[i]
        feats['psych_dist_to_round'] = df['psych_dist_to_round'].iloc[i]
        feats['psych_session_phase'] = df['psych_session_phase'].iloc[i]
        feats['atr'] = df['atr'].iloc[i]
        
        # Frame hint so the model learns that a 1d setup is mathematically different from a 1h setup
        tf_mapping = {"1h": 0.5, "1d": 1.0}
        feats['tf_hint'] = tf_mapping.get(tf_config["tf"], 1.0)
        
        X_rows.append(feats)
        y_labels.append(label)
        
    X = pd.DataFrame(X_rows)
    return X, y_labels

def main():
    logger.info("==================================================")
    logger.info("STARTING CONTINUOUS TRAINING ENGINE (ALPHAZERO MODE)")
    logger.info("==================================================")
    
    model, scaler = load_or_create_model()
    classes = np.array([-1, 0, 1])
    is_fitted = hasattr(model, 'classes_')
    
    cycles = 0
    while True:
        cycles += 1
        ticker = random.choice(TARGET_INDICES)
        tf_config = random.choice(TIMEFRAME_CONFIGS)
        
        logger.info(f"[CYCLE {cycles}] Target: {ticker} | Timeframe: {tf_config['tf']}")
        
        X, y = generate_features_for_ticker(ticker, tf_config)
        
        if X is None or len(X) == 0:
            logger.warning(f"Not enough data for {ticker}. Skipping...")
            continue
            
        logger.info(f"Simulated {len(X)} trades. Win: {y.count(1)}, Loss: {y.count(-1)}, Timeout: {y.count(0)}")
        
        # 1. Incrementally update the Scaler with the new data distribution
        scaler.partial_fit(X)
        
        # 2. Transform the data
        X_scaled = scaler.transform(X)
        
        # 3. Incrementally teach the ML Model
        logger.info("Injecting simulated outcomes into AI Brain (partial_fit)...")
        model.partial_fit(X_scaled, y, classes=classes)
        
        # Save every 3 cycles
        if cycles % 3 == 0:
            save_model(model, scaler)
            
        # Brief pause to avoid destroying APIs
        time.sleep(2)

if __name__ == "__main__":
    main()
