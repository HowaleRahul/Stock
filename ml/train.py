import os
import argparse
import logging
from typing import List, Dict, Any, Tuple

import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
import joblib

from setups.engine import SetupEngine
from ml.ensemble import REGISTRY_DIR
from ml.features import enrich_with_macro_and_options, generate_triple_barrier_labels

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("trading.ml.train")

# Silence expected engine warnings during sequential slicing
logging.getLogger("trading.setups.engine").setLevel(logging.ERROR)

def create_dataset(df: pd.DataFrame, ticker: str, forward_periods: int = 10, return_threshold: float = 0.01) -> Tuple[pd.DataFrame, pd.Series]:
    """
    Simulates the SetupEngine sequentially over the dataframe to avoid lookahead bias.
    Creates feature vectors and labels (1 if forward return > threshold, -1 if < -threshold, 0 otherwise).
    """
    # Enrich with Macro and Options Data First
    df = enrich_with_macro_and_options(df, ticker)
    
    # Generate advanced triple-barrier path-dependent labels
    # Note: These parameters should ideally match the backtest/engine settings
    triple_barrier_labels = generate_triple_barrier_labels(df, tp_pct=0.05, sl_pct=0.02, max_hold_bars=20)
    
    engine = SetupEngine()
    features = []
    labels = []
    
    # We need a decent window to generate setups (e.g. 100 periods)
    min_periods = 100
    
    logger.info(f"Generating features via sequential engine evaluation for {ticker} (Rows: {len(df)})")
    
    for i in range(min_periods, len(df)):
        # If the label is 0 (timeout or end of data), we optionally skip it for training
        # to force the model to only learn explicit Win (1) vs Loss (-1) patterns.
        # But for robustness, we'll include it.
        label = triple_barrier_labels[i]
        
        window_df = df.iloc[:i+1]
        
        labels.append(label)
        
        # Evaluate setups
        regime, setups = engine.evaluate_all(window_df, ticker=ticker)
        
        # Build feature dict
        feat_dict = {}
        r_val = 0
        if regime["regime"] == "trending-bullish": r_val = 1
        if regime["regime"] == "trending-bearish": r_val = -1
        
        feat_dict["regime_val"] = r_val
        feat_dict["regime_adx"] = float(regime["adx"])
        
        # Add higher-order Macro/Options Features
        feat_dict["macro_spx_ret"] = float(df['macro_spx_ret'].iloc[i])
        feat_dict["macro_usdinr_ret"] = float(df['macro_usdinr_ret'].iloc[i])
        feat_dict["macro_vix"] = float(df['macro_vix'].iloc[i])
        feat_dict["opt_delta"] = float(df['opt_delta'].iloc[i])
        feat_dict["opt_gamma"] = float(df['opt_gamma'].iloc[i])
        
        for s in setups:
            sig_val = 1 if s.signal == "bullish" else -1 if s.signal == "bearish" else 0
            feat_dict[f"{s.name}_sig"] = sig_val
            feat_dict[f"{s.name}_conf"] = s.confidence
            
        features.append(feat_dict)
        
    feature_df = pd.DataFrame(features)
    label_series = pd.Series(labels)
    
    return feature_df, label_series

def train_and_evaluate(df: pd.DataFrame, ticker: str, timeframe: str):
    logger.info(f"Starting training pipeline for {timeframe}")
    X, y = create_dataset(df, ticker)
    
    if len(X) < 50:
        logger.error("Not enough data points to train a reliable model.")
        return
        
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
    
    # Meta-Model: Logistic Regression (works well for stacking classifications)
    model = LogisticRegression(class_weight='balanced', max_iter=1000)
    model.fit(X_train, y_train)
    
    y_pred = model.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    
    logger.info(f"Trained Meta-Model. Hold-out Accuracy: {acc:.2f}")
    
    # Check registry for existing model
    model_path = os.path.join(REGISTRY_DIR, f"model_{timeframe}.pkl")
    deploy = True
    
    if os.path.exists(model_path):
        try:
            old_data = joblib.load(model_path)
            old_model = old_data["model"]
            old_acc = accuracy_score(y_test, old_model.predict(X_test))
            logger.info(f"Previous Model Hold-out Accuracy: {old_acc:.2f}")
            if acc <= old_acc:
                logger.warning("New model did not outperform deployed model. Skipping deployment.")
                deploy = False
        except Exception as e:
            logger.error(f"Error evaluating old model: {e}")
            
    if deploy:
        payload = {
            "model": model,
            "features": list(X.columns),
            "accuracy": acc
        }
        joblib.dump(payload, model_path)
        logger.info(f"Deployed new Meta-Model to {model_path}")

if __name__ == "__main__":
    # Example usage for CLI training
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--timeframe", default="1d")
    args = parser.parse_args()
    
    # Fetch real data via fetcher
    import asyncio
    from data.fetcher import YFinanceFetcher
    
    async def run():
        period = "2y"
        tf = args.timeframe.lower()
        if tf in ["1m"]: period = "7d"
        elif tf in ["2m", "5m", "15m", "30m", "90m"]: period = "60d"
        elif tf in ["1h"]: period = "730d"
        
        bars = await YFinanceFetcher.fetch_ohlcv_bars(args.ticker, period=period, interval=args.timeframe)
        if not bars:
            logger.error(f"No data fetched for timeframe {args.timeframe}.")
            return
            
        df = pd.DataFrame(bars)
        # SetupEngine expects lowercase: open, high, low, close, volume
        if "time" in df.columns:
            df.set_index("time", inplace=True)
        
        train_and_evaluate(df, args.ticker, args.timeframe)
        
    asyncio.run(run())
