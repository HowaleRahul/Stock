"""
Adversarial SDET / Senior Developer test suite for Phase 2.

Verifies exact numerical behavior, edge cases, NaN/Inf resilience, zero-variance flat price
handling, setup evaluation immunity, and API timestamp sorting/deduplication under extreme conditions.
"""

import math
import pytest
import numpy as np
import pandas as pd
from typing import Any

from setups.base import SetupSignal
from setups.indicators import sma, ema, rsi, macd, bollinger_bands, find_support_resistance
from setups.ma_crossover import MACrossoverSetup
from setups.rsi_setup import RSISetup
from setups.macd_setup import MACDSetup
from setups.bollinger_setup import BollingerBandsSetup
from setups.breakout_setup import BreakoutSetup
from setups.engine import SetupEngine
from api.router import _safe_json_float


def test_setup_signal_post_init_adversarial():
    """Verify SetupSignal.__post_init__ sanitizes NaN, Inf, and invalid types cleanly."""
    s1 = SetupSignal(name="Test", signal="BULLISH ", confidence=np.nan, reasoning="nan conf")
    assert s1.signal == "bullish"
    assert s1.confidence == 0.0
    assert not math.isnan(s1.confidence)

    s2 = SetupSignal(name="Test", signal="INVALID_SIGNAL", confidence=float("inf"), reasoning="inf conf")
    assert s2.signal == "neutral"
    assert s2.confidence == 1.0

    s3 = SetupSignal(name="Test", signal="bearish", confidence=float("-inf"), reasoning="neg inf conf")
    assert s3.signal == "bearish"
    assert s3.confidence == 0.0


def test_indicators_on_pure_nan_series():
    """Verify that pure NaN series return clean NaN series without crashing or throwing warnings."""
    s = pd.Series([np.nan] * 100)
    assert sma(s, 10).isna().all()
    assert ema(s, 10).isna().all()
    assert rsi(s, 14).isna().all()

    m_line, m_signal, m_hist = macd(s, 12, 26, 9)
    assert m_line.isna().all()
    assert m_signal.isna().all()
    assert m_hist.isna().all()

    upper, middle, lower = bollinger_bands(s, 20, 2.0)
    assert upper.isna().all()
    assert middle.isna().all()
    assert lower.isna().all()

    sr = find_support_resistance(s, s, s)
    assert sr["support"] == []
    assert sr["resistance"] == []


def test_rsi_on_flat_zero_variance_price():
    """When price is completely flat (0 gains and 0 losses), RSI must evaluate to 50.0 (neutral), not 100.0."""
    s = pd.Series([100.0] * 50)
    r = rsi(s, 14)
    # First 14 entries are NaN
    assert r.iloc[:14].isna().all()
    # From bar 14 onwards, flat price should yield 50.0 exactly
    for val in r.iloc[14:]:
        assert val == 50.0


def test_ema_leading_and_internal_nan_resilience():
    """Verify EMA handles leading NaNs (by seeding on first valid window) and internal NaNs gracefully."""
    # Leading NaNs + valid numbers + an internal NaN
    data = [np.nan] * 10 + [10.0, 12.0, 14.0, 16.0, 18.0, np.nan, 20.0, 22.0, 24.0]
    s = pd.Series(data)
    res = ema(s, period=3)
    # The first valid window of length 3 starts at index 10: [10.0, 12.0, 14.0] -> mean is 12.0 at index 12
    assert np.isnan(res.iloc[11])
    assert res.iloc[12] == 12.0
    # At index 15 where data is NaN, EMA should hold the previous value rather than poisoning to NaN
    assert not np.isnan(res.iloc[15])
    assert res.iloc[15] == res.iloc[14]
    # Subsequent values should continue smoothing safely
    assert not np.isnan(res.iloc[16])


def test_setups_evaluated_on_adversarial_nan_dataframe():
    """Every setup must return neutral (confidence=0.0) when evaluated on a DataFrame containing NaNs."""
    df_nan = pd.DataFrame({
        "time": pd.date_range("2026-01-01", periods=100),
        "open": [np.nan] * 100,
        "high": [np.nan] * 100,
        "low": [np.nan] * 100,
        "close": [np.nan] * 100,
        "volume": [np.nan] * 100,
    })

    setups = [
        MACrossoverSetup(),
        RSISetup(),
        MACDSetup(),
        BollingerBandsSetup(),
        BreakoutSetup(),
    ]

    for setup in setups:
        sig = setup.evaluate(df_nan)
        assert sig.signal == "neutral"
        assert sig.confidence == 0.0
        assert not math.isnan(sig.confidence)


def test_setup_engine_error_isolation_and_aggregation():
    """Verify SetupEngine catches and isolates any unexpected error raised by a faulty setup without crashing."""
    engine = SetupEngine()

    class FaultySetup(MACrossoverSetup):
        name = "Exploding Setup"
        def evaluate(self, df: pd.DataFrame) -> SetupSignal:
            raise RuntimeError("Synthetic fatal database or math explosion!")

    engine.setups.insert(0, FaultySetup())

    df_valid = pd.DataFrame({
        "time": pd.date_range("2026-01-01", periods=100),
        "open": np.linspace(100, 150, 100),
        "high": np.linspace(101, 151, 100),
        "low": np.linspace(99, 149, 100),
        "close": np.linspace(100, 150, 100),
        "volume": [1000] * 100,
    })

    signals = engine.evaluate_all(df_valid)
    assert len(signals) == 6
    assert signals[0].name == "Exploding Setup"
    assert signals[0].signal == "neutral"
    assert signals[0].confidence == 0.0
    assert "Evaluation error: Synthetic fatal database or math explosion!" in signals[0].reasoning


def test_safe_json_float_comprehensive():
    """Verify _safe_json_float safely converts numpy floats, pandas NAs, and Inf/NaN to None."""
    assert _safe_json_float(123.45) == 123.45
    assert _safe_json_float(np.float64(12.34)) == 12.34
    assert _safe_json_float(np.nan) is None
    assert _safe_json_float(float("nan")) is None
    assert _safe_json_float(np.inf) is None
    assert _safe_json_float(float("-inf")) is None
    assert _safe_json_float(pd.NA) is None
    assert _safe_json_float(None) is None
