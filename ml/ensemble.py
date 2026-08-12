import os
import logging
from typing import List, Dict, Any, Tuple
import joblib
import numpy as np

logger = logging.getLogger("trading.ml.ensemble")

# Constants
REGISTRY_DIR = os.path.join(os.path.dirname(__file__), "registry")
os.makedirs(REGISTRY_DIR, exist_ok=True)

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
        
        self.load_model()

    def load_model(self):
        if os.path.exists(self.model_path):
            try:
                data = joblib.load(self.model_path)
                self.model = data["model"]
                self.feature_names = data["features"]
                logger.info(f"Loaded ensemble model for {self.timeframe}")
            except Exception as e:
                logger.error(f"Failed to load model for {self.timeframe}: {e}")
        else:
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

    def predict(self, regime_data: Dict[str, Any], setups: List[Any]) -> Dict[str, Any]:
        """
        Takes the regime and the raw setups from SetupEngine and outputs the ensemble prediction.
        """
        # Feature extraction
        features_dict = {}
        features_dict["regime_val"] = self._regime_to_num(regime_data.get("regime", "neutral"))
        features_dict["regime_adx"] = float(regime_data.get("adx", 0.0))
        
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
                
        # If no model is trained yet, fallback to heuristic unweighted voting
        if not self.model or not self.feature_names:
            return self._fallback_voting(features_dict, expected_setups)
            
        # Build feature vector
        X = np.array([[features_dict.get(f, 0.0) for f in self.feature_names]])
        
        # Predict
        try:
            pred_class = self.model.predict(X)[0]
            probs = self.model.predict_proba(X)[0]
            
            if pred_class == 1:
                direction = "bullish"
                prob = probs[list(self.model.classes_).index(1)]
            elif pred_class == -1:
                direction = "bearish"
                prob = probs[list(self.model.classes_).index(-1)]
            else:
                direction = "neutral"
                prob = probs[list(self.model.classes_).index(0)]
                
            # Explainability: feature contributions (Logit * Coef)
            contributions = X[0] * self.model.coef_[0]  # Using coef of class 1 (bullish) for analysis
            
            # Find top driver
            driver_idx = np.argmax(np.abs(contributions))
            top_driver_feature = self.feature_names[driver_idx]
            
            # Generate alternative scenario
            alt_scenario = f"If {top_driver_feature.replace('_sig', '').replace('_conf', '')} reverses signal, this prediction may be invalidated."
            
            return {
                "signal": direction,
                "probability": float(prob),
                "drivers": [top_driver_feature.replace("_sig", "").replace("_conf", "")],
                "alternative_scenario": alt_scenario,
                "model_version": "v1.0"
            }
            
        except Exception as e:
            logger.error(f"Ensemble prediction error: {e}")
            return self._fallback_voting(features_dict, expected_setups)

    def _fallback_voting(self, features: Dict[str, float], setups_list: List[str]) -> Dict[str, Any]:
        """Simple tally if ML model isn't trained yet."""
        bull_score = sum([features[f"{s}_conf"] for s in setups_list if features[f"{s}_sig"] == 1])
        bear_score = sum([features[f"{s}_conf"] for s in setups_list if features[f"{s}_sig"] == -1])
        
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
            prob = bull_score / total
            driver = sorted(setups_list, key=lambda s: features[f"{s}_conf"] if features[f"{s}_sig"] == 1 else 0, reverse=True)[0]
        else:
            direction = "bearish"
            prob = bear_score / total
            driver = sorted(setups_list, key=lambda s: features[f"{s}_conf"] if features[f"{s}_sig"] == -1 else 0, reverse=True)[0]
            
        return {
            "signal": direction,
            "probability": prob,
            "drivers": [driver],
            "alternative_scenario": f"If {driver} momentum fails, the trend may reverse.",
            "model_version": "fallback_heuristic"
        }
