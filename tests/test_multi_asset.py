import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from unittest.mock import patch

from ml.assets import asset_flags, classify_ticker
from ml.ensemble import EnsembleModel
from ml.features import _align_daily_series, enrich_with_macro_and_options
from ml.continuous_trainer import generate_features_for_ticker


def test_asset_classification_is_explicit_and_one_hot():
    assert classify_ticker("BTC-USD") == "CRYPTO"
    assert classify_ticker("^GSPC") == "US_EQUITY"
    # A foreign-exchange symbol must not be incorrectly treated as crypto.
    assert classify_ticker("INR=X") == "IN_EQUITY"
    assert sum(asset_flags("CRYPTO").values()) == 1.0


def test_crypto_weekend_uses_last_available_macro_value_without_lookahead():
    primary_index = pd.date_range("2026-01-02", periods=3, freq="D", tz="UTC")
    delayed_macro = pd.Series(
        [17.0], index=pd.DatetimeIndex(["2026-01-02"], tz="UTC")
    )
    aligned = _align_daily_series(delayed_macro, primary_index)
    assert aligned.tolist() == [17.0, 17.0, 17.0]


def test_crypto_macro_enrichment_adds_btc_volume_context():
    index = pd.date_range("2026-01-01", periods=25, freq="D", tz="UTC")
    primary = pd.DataFrame(
        {"open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "volume": 10.0}, index=index
    )
    macro_index = pd.date_range("2025-12-01", periods=40, freq="D", tz="UTC")

    def fake_download(symbol, **_kwargs):
        if symbol == "BTC-USD":
            return pd.DataFrame({"Close": np.linspace(90, 130, 40), "Volume": np.arange(40) + 100}, index=macro_index)
        return pd.DataFrame({"Close": np.linspace(10, 50, 40)}, index=macro_index)

    with patch("ml.features.yf.download", side_effect=fake_download):
        enriched = enrich_with_macro_and_options(primary, "BTC-USD", asset_class="CRYPTO")

    assert {"macro_vix", "macro_btc_volume", "macro_btc_volume_ret", "opt_delta", "opt_gamma"} <= set(enriched.columns)
    assert enriched[["macro_vix", "macro_btc_volume"]].notna().all().all()


def test_ensemble_explains_asset_class_driver():
    class DummyModel:
        classes_ = np.array([-1, 0, 1])
        coef_ = np.array([[0.0, 0.0, 0.0]])

        def predict(self, _X): return np.array([1])
        def predict_proba(self, _X): return np.array([[0.1, 0.1, 0.8]])

    model = EnsembleModel("nonexistent-test-timeframe")
    model.model = DummyModel()
    model.feature_names = ["feat_is_crypto", "feat_is_in_equity", "feat_is_us_equity"]
    model.scaler = StandardScaler().fit(np.zeros((1, 3)))
    model.asset_class = "CRYPTO"
    model.model.coef_[0][0] = 3.0
    result = model.predict({"regime": "unknown", "adx": 0}, [], asset_class="CRYPTO")
    assert result["drivers"] == ["Asset class: crypto"]
    assert "asset-class" in result["alternative_scenario"]


def test_crypto_trainer_dry_run_emits_one_hot_features():
    index = pd.date_range("2026-01-01", periods=110, freq="D")
    raw = pd.DataFrame(
        {
            "Open": np.linspace(100, 130, len(index)),
            "High": np.linspace(101, 131, len(index)),
            "Low": np.linspace(99, 129, len(index)),
            "Close": np.linspace(100, 130, len(index)),
            "Volume": np.full(len(index), 1000),
        }, index=index,
    )

    def fake_macro(df, *_args, **_kwargs):
        result = df.copy()
        result["macro_vix"] = 20.0
        result["macro_spx_ret"] = 0.0
        result["macro_usdinr_ret"] = 0.0
        result["macro_btc_volume_ret"] = 0.0
        result["opt_delta"] = 0.5
        result["opt_gamma"] = 0.0
        return result

    def fake_psychology(df):
        result = df.copy()
        for column in ("psych_fomo_streak", "psych_panic_index", "psych_dist_to_round", "psych_session_phase"):
            result[column] = 0.0
        return result

    with patch("ml.continuous_trainer.yf.download", return_value=raw), \
         patch("ml.continuous_trainer.enrich_with_macro_and_options", side_effect=fake_macro), \
         patch("ml.continuous_trainer.enrich_with_psychology_features", side_effect=fake_psychology):
        X, y = generate_features_for_ticker("BTC-USD", {"tf": "1d", "period": "1y", "tp_atr": 3.0, "sl_atr": 1.5, "max_hold": 20}, "CRYPTO")

    assert X is not None and len(X) == len(y) and not X.empty
    assert (X["feat_is_crypto"] == 1.0).all()
    assert (X["feat_is_in_equity"] == 0.0).all()
