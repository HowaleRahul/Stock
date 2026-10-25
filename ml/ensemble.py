import os
import math
import logging
from typing import List, Dict, Any, Tuple
import joblib
import numpy as np
from ml.assets import asset_flags, fo_asset_flags

logger = logging.getLogger("trading.ml.ensemble")

# Constants
REGISTRY_DIR = os.path.join(os.path.dirname(__file__), "registry")
CONTINUOUS_BUNDLE_PATH = os.path.join(os.path.dirname(__file__), "models", "continuous_brain_bundle.pkl")
os.makedirs(REGISTRY_DIR, exist_ok=True)

MACRO_NEUTRAL_DEFAULTS: Dict[str, float] = {
    "macro_spx_ret": 0.0,
    "macro_usdinr_ret": 0.0,
    "macro_vix": 15.0,
    "macro_btc_volume_ret": 0.0,
    "opt_delta": 0.5,
    "opt_gamma": 0.0,
    "psych_fomo_streak": 0.0,
    "psych_panic_index": 0.0,
    "psych_dist_to_round": 0.5,
    "psych_session_phase": 0.5,
    "atr": 10.0,
    "tf_hint": 1.0,
}

class EnsembleModel:
    """
    Loads the trained Logistic Regression stacking ensemble.
    Predicts the forward return direction and generates Explainable AI (XAI) insights.
    """
    def __init__(self, timeframe: str = "1d"):
        self.timeframe = timeframe
        self.model_path = os.path.join(REGISTRY_DIR, f"model_{timeframe}.pkl")
        self.model = None
        self.feature_names = None
        self.scaler = None
        self.feature_version = None
        self.asset_class = None
        
        self.load_model()

    def load_model(self):
        loaded_from_registry = False
        if os.path.exists(self.model_path):
            try:
                data = joblib.load(self.model_path)
                self.model = data.get("model")
                self.feature_names = data.get("features")
                self.scaler = data.get("scaler")
                self.feature_version = data.get("feature_version")
                self.asset_class = data.get("asset_class")
                if self.model is not None and self.scaler is not None and self.feature_names is not None:
                    logger.info(f"Loaded ensemble model for {self.timeframe}")
                    loaded_from_registry = True
                else:
                    logger.warning(f"Registry model for {self.timeframe} missing scaler/model metadata.")
            except Exception as e:
                logger.error(f"Failed to load model for {self.timeframe}: {e}")

        # Check continuous brain bundle as high-quality fallback
        if not loaded_from_registry and os.path.exists(CONTINUOUS_BUNDLE_PATH):
            try:
                bundle = joblib.load(CONTINUOUS_BUNDLE_PATH)
                if bundle.get("model") is not None and bundle.get("scaler") is not None and bundle.get("features"):
                    self.model = bundle["model"]
                    self.feature_names = bundle["features"]
                    self.scaler = bundle["scaler"]
                    self.feature_version = bundle.get("feature_version", "continuous_bundle")
                    self.asset_class = bundle.get("asset_class", "IN_INDEX_FO")
                    logger.info(f"Loaded continuous brain bundle fallback for {self.timeframe}")
                    return
            except Exception as e:
                logger.debug(f"Could not load continuous brain bundle: {e}")

        if not loaded_from_registry and not self.model:
            logger.warning(f"No trained model found for {self.timeframe}. Will fallback to simple voting.")

    def _signal_to_num(self, signal: str) -> int:
        if signal.lower() == "bullish": return 1
        if signal.lower() == "bearish": return -1
        return 0
        
    def _regime_to_num(self, regime: str) -> int:
        r = regime.lower()
        if r == "trending-bullish": return 1
        if r == "trending-bearish": return -1
        return 0 # range-bound or neutral

    def predict(
        self,
        regime_data: Dict[str, Any],
        setups: List[Any],
        setup_weights: Dict[str, float] = None,
        asset_class: str = "IN_INDEX_FO",
        df: Any = None,
    ) -> Dict[str, Any]:
        """
        Takes the regime and the raw setups from SetupEngine and outputs the ensemble prediction.
        """
        # Feature extraction
        features_dict = {}
        features_dict["regime_val"] = self._regime_to_num(regime_data.get("regime", "neutral"))
        features_dict["regime_adx"] = float(regime_data.get("adx", 0.0))
        features_dict.update(asset_flags(asset_class))
        
        setup_map = {s.name: s for s in setups}
        
        if self.feature_names:
            expected_setups = [f.replace("_sig", "") for f in self.feature_names if f.endswith("_sig")]
        else:
            expected_setups = [s.name for s in setups]
            
        for s_name in expected_setups:
            s = setup_map.get(s_name)
            if s:
                features_dict[f"{s_name}_sig"] = self._signal_to_num(s.signal)
                features_dict[f"{s_name}_conf"] = float(s.confidence)
            else:
                features_dict[f"{s_name}_sig"] = 0
                features_dict[f"{s_name}_conf"] = 0.0

        # Extract macro/Greeks/psychology features from DataFrame if provided
        if df is not None:
            try:
                import pandas as pd
                if isinstance(df, pd.DataFrame) and not df.empty:
                    last_row = df.iloc[-1]
                    for col in MACRO_NEUTRAL_DEFAULTS.keys():
                        if col in df.columns:
                            val = last_row[col]
                            if pd.notnull(val):
                                try:
                                    f_val = float(val)
                                    if not (math.isnan(f_val) or math.isinf(f_val)):
                                        features_dict[col] = f_val
                                except (ValueError, TypeError):
                                    pass
            except Exception as e:
                logger.debug(f"Error extracting features from df: {e}")

        # Fill neutral baseline values for expected features not present in inputs
        if self.feature_names:
            for name in self.feature_names:
                if name not in features_dict and name in MACRO_NEUTRAL_DEFAULTS:
                    features_dict[name] = MACRO_NEUTRAL_DEFAULTS[name]
                
        # If no model is trained yet, fallback to heuristic unweighted voting
        if not self.model or not self.feature_names or self.scaler is None:
            if self.model and self.feature_names:
                logger.warning("Ignoring registry model without compatible scaler metadata.")
            return self._fallback_voting(features_dict, expected_setups, setup_weights)

        if self.asset_class and self.asset_class != asset_class:
            logger.warning(
                "Ignoring %s model trained for %s during %s inference.",
                self.timeframe, self.asset_class, asset_class,
            )
            return self._fallback_voting(features_dict, expected_setups, setup_weights)

        missing_features = [name for name in self.feature_names if name not in features_dict]
        if missing_features:
            logger.error("Model feature contract is incomplete: %s", missing_features)
            return self._fallback_voting(features_dict, expected_setups, setup_weights)
            
        # Build clean raw feature values matching scaler expectation
        import pandas as pd
        clean_vals = []
        for f in self.feature_names:
            val = features_dict.get(f)
            if val is None or not isinstance(val, (int, float)) or math.isnan(val) or math.isinf(val):
                val = MACRO_NEUTRAL_DEFAULTS.get(f, 0.0)
            clean_vals.append(float(val))

        raw_vals = [clean_vals]
        if hasattr(self.scaler, "feature_names_in_") and self.scaler.feature_names_in_ is not None:
            X_df = pd.DataFrame(raw_vals, columns=self.feature_names)
            X = self.scaler.transform(X_df)
        else:
            X = self.scaler.transform(raw_vals)

        # Zero-variance or singular feature protection: sanitize NaN/Inf from scaler transform
        if np.isnan(X).any() or np.isinf(X).any():
            X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        
        # Predict
        try:
            pred_class = self.model.predict(X)[0]
            probs = self.model.predict_proba(X)[0]
            
            classes = list(self.model.classes_)
            
            def _get_prob(cls_val):
                if cls_val in classes:
                    p = probs[classes.index(cls_val)]
                    if math.isnan(p) or math.isinf(p):
                        return 0.5
                    # Probability calibration bounds: prevent uncalibrated extreme confidence
                    return float(np.clip(p, 0.05, 0.95))
                return 0.5
                
            if pred_class == 1:
                direction = "bullish"
                prob = _get_prob(1)
            elif pred_class == -1:
                direction = "bearish"
                prob = _get_prob(-1)
            else:
                direction = "neutral"
                prob = _get_prob(0)
                
            # Explainability: feature contributions (Logit * Coef)
            contributions = X[0] * self.model.coef_[0]  # Using coef of class 1 (bullish) for analysis
            
            # Find top driver
            driver_idx = np.argmax(np.abs(contributions))
            top_driver_feature = self.feature_names[driver_idx]
            
            # Generate alternative scenario
            if top_driver_feature.startswith("feat_is_"):
                asset_name = top_driver_feature.removeprefix("feat_is_").replace("_", " ")
                driver = f"Asset class: {asset_name}"
                alt_scenario = "This prediction depends materially on the asset-class regime; validate it against asset-specific history."
            else:
                driver = top_driver_feature.replace("_sig", "").replace("_conf", "")
                alt_scenario = f"If {driver} reverses signal, this prediction may be invalidated."
            
            prob = float(np.clip(prob, 0.0, 1.0))
            return {
                "signal": direction,
                "probability": float(prob),
                "drivers": [driver],
                "alternative_scenario": alt_scenario,
                "model_version": "v1.0"
            }
            
        except Exception as e:
            logger.error(f"Ensemble prediction error: {e}")
            return self._fallback_voting(features_dict, expected_setups, setup_weights)

    def _fallback_voting(self, features: Dict[str, float], setups_list: List[str], setup_weights: Dict[str, float] = None) -> Dict[str, Any]:
        """Simple tally if ML model isn't trained yet, weighted by RL setup_weights if provided."""
        if setup_weights is None:
            setup_weights = {s: 1.0 for s in setups_list}
        else:
            # Provide default weight of 1.0 if not found in setup_weights
            setup_weights = {s: setup_weights.get(s, 1.0) for s in setups_list}
            
        bull_score = sum([features.get(f"{s}_conf", 0.0) * setup_weights.get(s, 1.0) for s in setups_list if features.get(f"{s}_sig", 0) == 1])
        bear_score = sum([features.get(f"{s}_conf", 0.0) * setup_weights.get(s, 1.0) for s in setups_list if features.get(f"{s}_sig", 0) == -1])
        
        total = bull_score + bear_score
        
        if total == 0:
            return {
                "signal": "neutral",
                "probability": 0.0,
                "drivers": [],
                "alternative_scenario": "Awaiting market momentum to build.",
                "model_version": "fallback_heuristic"
            }
            
        if bull_score > bear_score:
            direction = "bullish"
            raw_prob = bull_score / total
            # Calibrate fallback heuristic: cap at 0.85 to prevent overconfidence
            prob = float(np.clip(0.50 + raw_prob * 0.35, 0.50, 0.85))
            sorted_drivers = sorted(setups_list, key=lambda s: features.get(f"{s}_conf", 0.0) if features.get(f"{s}_sig", 0) == 1 else 0, reverse=True)
            driver = sorted_drivers[0] if sorted_drivers else "Unknown"
        elif bear_score > bull_score:
            direction = "bearish"
            raw_prob = bear_score / total
            prob = float(np.clip(0.50 + raw_prob * 0.35, 0.50, 0.85))
            sorted_drivers = sorted(setups_list, key=lambda s: features.get(f"{s}_conf", 0.0) if features.get(f"{s}_sig", 0) == -1 else 0, reverse=True)
            driver = sorted_drivers[0] if sorted_drivers else "Unknown"
        else:
            return {
                "signal": "neutral",
                "probability": 0.5,
                "drivers": [],
                "alternative_scenario": "Bullish and bearish setup signals are equally balanced.",
                "model_version": "fallback_heuristic"
            }
            
        return {
            "signal": direction,
            "probability": prob,
            "drivers": [driver],
            "alternative_scenario": f"If {driver} momentum fails, the trend may reverse.",
            "model_version": "fallback_heuristic"
        }
