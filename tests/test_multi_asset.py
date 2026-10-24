import pytest
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from unittest.mock import patch

from ml.assets import asset_flags, fo_asset_flags, classify_ticker, normalize_ticker, get_fo_name
from ml.ensemble import EnsembleModel
from ml.features import _align_daily_series, enrich_with_macro_and_options
from ml.continuous_trainer import generate_features_for_ticker


def test_asset_classification_is_fo_only():
    # Indian F&O Underlyings must classify cleanly as IN_INDEX_FO
    assert classify_ticker("NIFTY") == "IN_INDEX_FO"
    assert classify_ticker("BANKNIFTY") == "IN_INDEX_FO"
    assert classify_ticker("SENSEX") == "IN_INDEX_FO"
    assert classify_ticker("^NSEI") == "IN_INDEX_FO"
    assert classify_ticker("^NSEBANK") == "IN_INDEX_FO"
    assert classify_ticker("^BSESN") == "IN_INDEX_FO"

    # Non-F&O instruments must fail closed
    with pytest.raises(ValueError):
        classify_ticker("BTC-USD")
    with pytest.raises(ValueError):
        classify_ticker("^GSPC")
    with pytest.raises(ValueError):
        classify_ticker("AAPL")


def test_fo_asset_flags_one_hot():
    nifty_flags = fo_asset_flags("NIFTY")
    assert nifty_flags["feat_is_nifty"] == 1.0
    assert nifty_flags["feat_is_banknifty"] == 0.0
    assert nifty_flags["feat_is_sensex"] == 0.0

    bank_flags = fo_asset_flags("BANKNIFTY")
    assert bank_flags["feat_is_nifty"] == 0.0
    assert bank_flags["feat_is_banknifty"] == 1.0
    assert bank_flags["feat_is_sensex"] == 0.0

    sensex_flags = fo_asset_flags("SENSEX")
    assert sensex_flags["feat_is_nifty"] == 0.0
    assert sensex_flags["feat_is_banknifty"] == 0.0
    assert sensex_flags["feat_is_sensex"] == 1.0


def test_fo_name_resolution():
    assert get_fo_name("^NSEI") == "NIFTY"
    assert get_fo_name("^NSEBANK") == "BANKNIFTY"
    assert get_fo_name("^BSESN") == "SENSEX"
    assert get_fo_name("SENSEX") == "SENSEX"
    assert get_fo_name("BANKNIFTY") == "BANKNIFTY"


def test_macro_alignment_without_lookahead():
    primary_index = pd.date_range("2026-01-02", periods=3, freq="D", tz="UTC")
    delayed_macro = pd.Series(
        [17.0], index=pd.DatetimeIndex(["2026-01-02"], tz="UTC")
    )
    aligned = _align_daily_series(delayed_macro, primary_index)
    assert aligned.tolist() == [17.0, 17.0, 17.0]


def test_fo_macro_and_options_enrichment():
    index = pd.date_range("2026-01-01", periods=25, freq="D", tz="UTC")
    primary = pd.DataFrame(
        {"open": 24000.0, "high": 24200.0, "low": 23900.0, "close": 24100.0, "volume": 50000.0}, index=index
    )
    macro_index = pd.date_range("2025-12-01", periods=40, freq="D", tz="UTC")

    def fake_download(symbol, **_kwargs):
        return pd.DataFrame({"Close": np.linspace(10, 50, 40), "Volume": np.arange(40) + 100}, index=macro_index)

    with patch("ml.features.yf.download", side_effect=fake_download):
        enriched = enrich_with_macro_and_options(primary, "^NSEI", asset_class="IN_INDEX_FO")

    assert {"macro_vix", "macro_spx_ret", "macro_usdinr_ret", "opt_delta", "opt_gamma"} <= set(enriched.columns)
    assert enriched[["macro_vix", "opt_delta", "opt_gamma"]].notna().all().all()


def test_continuous_trainer_dry_run_for_fo():
    index = pd.date_range("2026-01-01", periods=110, freq="D")
    raw = pd.DataFrame(
        {
            "Open": np.linspace(24000, 24500, len(index)),
            "High": np.linspace(24100, 24600, len(index)),
            "Low": np.linspace(23900, 24400, len(index)),
            "Close": np.linspace(24000, 24500, len(index)),
            "Volume": np.full(len(index), 100000),
        }, index=index,
    )

    def fake_macro(df, *_args, **_kwargs):
        result = df.copy()
        result["macro_vix"] = 15.0
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
        X, y = generate_features_for_ticker("^NSEI", {"tf": "1d", "period": "1y", "tp_atr": 2.0, "sl_atr": 1.0, "max_hold": 10}, "IN_INDEX_FO")

    assert X is not None and len(X) == len(y) and not X.empty
    assert "regime_val" in X.columns
    assert "regime_adx" in X.columns


def test_continuous_trainer_schema_reset_pd_index_safety():
    """Verify _reset_if_feature_schema_changed never evaluates ambiguous truth value of pd.Index."""
    from ml.continuous_trainer import _reset_if_feature_schema_changed
    from sklearn.linear_model import SGDClassifier

    model = SGDClassifier(loss="log_loss")
    scaler = StandardScaler()

    # Fit initial scaler on a 2-column DataFrame
    initial_df = pd.DataFrame({"regime_val": [0.0, 1.0], "regime_adx": [15.0, 25.0]})
    scaler.fit(initial_df)

    # 1. Calling with identical schema using a pd.Index (e.g. df.columns)
    new_model, new_scaler = _reset_if_feature_schema_changed(model, scaler, initial_df, initial_df.columns)
    assert new_model is model
    assert new_scaler is scaler

    # 2. Calling with feature_names=None
    new_model2, new_scaler2 = _reset_if_feature_schema_changed(model, scaler, initial_df, None)
    assert new_model2 is model
    assert new_scaler2 is scaler

    # 3. Calling with modified schema (columns added) safely triggers reset without Index exception
    altered_df = pd.DataFrame({"regime_val": [0.0], "regime_adx": [15.0], "new_feat": [1.0]})
    reset_model, reset_scaler = _reset_if_feature_schema_changed(model, scaler, altered_df, altered_df.columns)
    assert reset_model is not model
    assert reset_scaler is not scaler
    assert getattr(reset_scaler, "n_features_in_", None) is None

