import time
import random
import logging
import os
from typing import Dict, Any, Optional
import joblib
import pandas as pd
import numpy as np
import yfinance as yf
from sklearn.linear_model import SGDClassifier
from sklearn.preprocessing import StandardScaler
from ml.features import enrich_with_macro_and_options, enrich_with_psychology_features, generate_triple_barrier_labels
from ml.assets import TARGETS, asset_flags, barrier_config
from setups.engine import SetupEngine
from data.market_hours import is_market_open, get_market_status
from ml.live_market_learner import LiveMarketLearner

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

    # Compute ATR (required by feature extraction below)
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    df['atr'] = true_range.rolling(14, min_periods=1).mean()
        
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

# Global training telemetry state
_training_state_lock = threading.Lock() if "threading" in globals() else None
import threading
_training_state_lock = threading.Lock()
_live_learner: Optional[LiveMarketLearner] = None
_current_mode: str = "IDLE"
_total_training_cycles: int = 0


def get_training_telemetry() -> Dict[str, Any]:
    """Returns real-time telemetry including mode, market status, and live portfolio MTM."""
    with _training_state_lock:
        market_stat = get_market_status("NSE")
        portfolio = _live_learner.get_portfolio_state() if _live_learner else None
        return {
            "mode": _current_mode,
            "market_status": market_stat,
            "portfolio": portfolio,
            "cycles": _total_training_cycles,
        }


def run_training_loop(
    stop_event=None,
    log_callback=None,
    mode: str = "auto",
    capital: Optional[float] = None,
    target_index: Optional[str] = None,
    derivative_type: Optional[str] = None,
    strike_preference: Optional[str] = None,
):
    """
    Continuous Training Loop with Live Market Hours Integration & Dynamic Capital Scaling.
    Supports Index Selection (NIFTY/BANKNIFTY) and F&O Derivative (Futures/Options) Execution.

    Modes:
    - 'auto': Checks NSE market hours. If OPEN, takes paper trades in live market
              and learns in real time. If CLOSED, runs offline historical replay
              and auto-switches to live trading when market opens at 09:15 IST.
    - 'simulate_live' / 'force_live': Runs live market paper trading and learning
              using real-time/latest market quotes even outside regular hours.
    - 'offline_only': Pure historical backdata replay and model self-play.
    """
    global _live_learner, _current_mode, _total_training_cycles

    def log(msg: str):
        logger.info(msg)
        if log_callback:
            try:
                log_callback(msg)
            except Exception:
                pass

    log("==================================================")
    log("STARTING CONTINUOUS TRAINING & TRADING ENGINE")
    log("==================================================")

    model, scaler = load_or_create_model()
    classes = np.array([-1, 0, 1])

    with _training_state_lock:
        _live_learner = LiveMarketLearner(
            starting_capital=capital,
            target_index=target_index,
            derivative_type=derivative_type,
            strike_preference=strike_preference,
            log_callback=log
        )
        _total_training_cycles = 0

    from ml.risk_engine import RiskEngine
    tier_info = RiskEngine.get_capital_tier(_live_learner.capital)
    log(
        f"[VIRTUAL CAPITAL] Initialized wallet with ₹{_live_learner.capital:,.2f} "
        f"({tier_info['label']}). Max risk/trade: {tier_info['max_risk_pct']*100:.1f}% "
        f"(₹{_live_learner.capital * tier_info['max_risk_pct']:,.2f}) | Min AI Conf: {tier_info['min_ai_confidence']*100:.0f}%"
    )
    log(
        f"[DERIVATIVES ENGINE] Index Target: {_live_learner.target_index} | "
        f"Instrument: {_live_learner.derivative_type} | Strike Pref: {_live_learner.strike_preference}"
    )

    while True:
        if stop_event and stop_event.is_set():
            log("[STOP] Stop signal received. Halting training and live trading loop.")
            with _training_state_lock:
                _current_mode = "STOPPED"
            break

        _total_training_cycles += 1
        market_stat = get_market_status("NSE")
        market_is_open = market_stat["is_open"]

        should_run_live = (
            (mode == "auto" and market_is_open)
            or mode in ("simulate_live", "force_live", "live_only")
        )

        if should_run_live:
            with _training_state_lock:
                _current_mode = "LIVE_MARKET" if market_is_open else "SIMULATED_LIVE"

            log(
                f"[LIVE CYCLE {_total_training_cycles}] Mode: {_current_mode} | "
                f"NSE: {market_stat['session']} | Scanning live setups on NIFTY, BANKNIFTY & Equities..."
            )

            try:
                # 1. Execute live market cycle: update active positions MTM & check TP/SL/Trailing exits
                _live_learner.execute_live_cycle()

                # 2. Log live telemetry
                p_state = _live_learner.get_portfolio_state()
                log(
                    f"[LIVE MTM TICK] Capital: ₹{p_state['cash_balance']:,.2f} | "
                    f"Net Value: ₹{p_state['net_liquidation_value']:,.2f} | "
                    f"Live MTM: ₹{p_state['unrealized_mtm']:+,.2f} | "
                    f"Open Positions: {p_state['open_positions_count']} | "
                    f"Win Rate: {p_state['win_rate']:.1f}%"
                )

                # 3. LIVE MARKET F&O MODEL TRAINING:
                # Continuously retrains the AI Brain on live market ticks and option features
                if _total_training_cycles % 3 == 0:
                    target_sym = "^NSEI" if _live_learner.target_index in ("NIFTY", "ALL") else ("^NSEBANK" if _live_learner.target_index == "BANKNIFTY" else "^NSEI")
                    try:
                        live_tf = {"tf": "1h", "period": "60d", "tp_atr": 2.0, "sl_atr": 1.0, "max_hold": 40}
                        log(f"⚡ [LIVE F&O TRAINING] Retraining AI Brain on live incoming stream for {target_sym}...")
                        X_live, y_live = generate_features_for_ticker(target_sym, live_tf, "IN_EQUITY")
                        if X_live is not None and len(X_live) > 0:
                            model, scaler = _reset_if_feature_schema_changed(model, scaler, X_live, X_live.columns)
                            scaler.partial_fit(X_live)
                            X_scaled = scaler.transform(X_live)
                            model.partial_fit(X_scaled, y_live, classes=classes)
                            save_model(model, scaler, X_live.columns, "IN_EQUITY", "1h")
                            log(f"🧠 [LIVE BRAIN UPDATED] Model fitted on {len(X_live)} live {target_sym} bars! Checkpoint saved.")
                    except Exception as live_train_err:
                        log(f"[WARNING] Live F&O training step error: {live_train_err}")

            except Exception as live_err:
                log(f"[WARNING] Live trading cycle error: {live_err}")

            # Sleep in 1-second chunks for 15 seconds to allow responsive stopping
            for _ in range(15):
                if stop_event and stop_event.is_set():
                    break
                time.sleep(1)

        else:
            with _training_state_lock:
                _current_mode = "OFFLINE_HISTORICAL"

            log(
                f"[HISTORICAL CYCLE {_total_training_cycles}] NSE is CLOSED ({market_stat['message']}). "
                f"Running Continuous Historical Replay & Training until 09:15 AM IST next session."
            )

            asset_class = random.choice(list(TARGET_CLASSES.keys()))
            ticker = random.choice(TARGET_CLASSES[asset_class])
            base_config = random.choice(TIMEFRAME_CONFIGS)
            tf_config = {**base_config, **barrier_config(asset_class, base_config["tf"])}

            log(f"[REPLAY] Target: {ticker} ({asset_class}) | Timeframe: {tf_config['tf']}")

            try:
                X, y = generate_features_for_ticker(ticker, tf_config, asset_class)
                if X is not None and len(X) > 0:
                    log(f"Simulated {len(X)} trades. Win: {y.count(1)}, Loss: {y.count(-1)}, Timeout: {y.count(0)}")
                    model, scaler = _reset_if_feature_schema_changed(model, scaler, X, X.columns)
                    scaler.partial_fit(X)
                    X_scaled = scaler.transform(X)
                    model.partial_fit(X_scaled, y, classes=classes)

                    if _total_training_cycles % 3 == 0:
                        save_model(model, scaler, X.columns, asset_class, tf_config["tf"])
                        log("💾 Model Checkpoint Saved.")
                else:
                    log(f"Not enough data for {ticker}. Skipping...")
            except Exception as replay_err:
                log(f"[WARNING] Historical training error: {replay_err}")

            # Sleep in 1-second chunks for 30 seconds
            for _ in range(30):
                if stop_event and stop_event.is_set():
                    break
                time.sleep(1)


def main():
    run_training_loop()


if __name__ == "__main__":
    main()
