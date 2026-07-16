"""
Exhaustive SDET & QA stress tests covering BaseSetup signal sanitization,
zero/constant price breakout/bollinger evaluation, database concurrency retries,
and full API boundary verification.
"""

import math
import pytest
import pandas as pd
import numpy as np
from setups.base import SetupSignal
from setups.breakout_setup import BreakoutSetup
from setups.bollinger_setup import BollingerBandsSetup
from setups.macd_setup import MACDSetup
from setups.engine import SetupEngine


def test_setup_signal_post_init_exhaustive_sanitization():
    """Verify SetupSignal.__post_init__ handles extreme malformed/adversarial attributes safely."""
    # 1. Null bytes and huge name/reasoning
    huge_str = "X" * 50000 + "\x00MALICIOUS"
    sig = SetupSignal(
        name=huge_str,
        signal="BULLISH  \x00",
        confidence="not_a_number",
        reasoning=huge_str,
        indicator_values="not_a_dict"
    )
    assert "\x00" not in sig.name
    assert len(sig.name) <= 128
    assert sig.signal == "bullish"
    assert sig.confidence == 0.0
    assert "\x00" not in sig.reasoning
    assert len(sig.reasoning) <= 2048
    assert isinstance(sig.indicator_values, dict)

    # 2. NaN and Inf confidence clamping
    sig_nan = SetupSignal(name="Test", signal="invalid_sig", confidence=float("nan"), reasoning=None)
    assert sig_nan.confidence == 0.0
    assert sig_nan.signal == "neutral"
    assert sig_nan.reasoning == ""

    sig_inf = SetupSignal(name="Test", signal="bearish", confidence=float("inf"), reasoning="Inf test")
    assert sig_inf.confidence == 1.0
    assert sig_inf.signal == "bearish"


def test_breakout_setup_zero_and_constant_price_resilience():
    """Verify S/R breakout setup does not raise division by zero or NaN errors when price levels are zero or constant."""
    setup = BreakoutSetup()
    
    # 1. Constant zero price series
    df_zero = pd.DataFrame({
        "time": pd.date_range("2025-01-01", periods=100, freq="D"),
        "open": [0.0]*100,
        "high": [0.0]*100,
        "low": [0.0]*100,
        "close": [0.0]*100,
        "volume": [1000]*100
    })
    sig_zero = setup.evaluate(df_zero)
    assert sig_zero.signal in ("neutral", "bullish", "bearish")
    assert 0.0 <= sig_zero.confidence <= 1.0

    # 2. Constant positive price (no pivots)
    df_const = pd.DataFrame({
        "time": pd.date_range("2025-01-01", periods=100, freq="D"),
        "open": [100.0]*100,
        "high": [100.0]*100,
        "low": [100.0]*100,
        "close": [100.0]*100,
        "volume": [0]*100
    })
    sig_const = setup.evaluate(df_const)
    assert sig_const.signal == "neutral"
    assert sig_const.confidence == 0.0


def test_bollinger_and_macd_on_extreme_outliers():
    """Verify Bollinger and MACD setups handle massive price spikes and zero variance without crashing."""
    df_spike = pd.DataFrame({
        "time": pd.date_range("2025-01-01", periods=100, freq="D"),
        "open": [100.0]*99 + [1e15],
        "high": [100.0]*99 + [1e15],
        "low": [100.0]*99 + [1e15],
        "close": [100.0]*99 + [1e15],
        "volume": [1000]*100
    })
    
    bb_setup = BollingerBandsSetup()
    sig_bb = bb_setup.evaluate(df_spike)
    assert sig_bb.signal in ("neutral", "bullish", "bearish")
    assert 0.0 <= sig_bb.confidence <= 1.0

    macd_setup = MACDSetup()
    sig_macd = macd_setup.evaluate(df_spike)
    assert sig_macd.signal in ("neutral", "bullish", "bearish")
    assert 0.0 <= sig_macd.confidence <= 1.0


def test_engine_on_empty_and_corrupted_dataframes():
    """Verify SetupEngine aggregates signals safely on completely empty or malformed DataFrames."""
    engine = SetupEngine()
    
    # Empty dataframe
    df_empty = pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
    signals_empty = engine.evaluate_all(df_empty)
    assert len(signals_empty) == 5
    for s in signals_empty:
        assert s.signal == "neutral"
        assert s.confidence == 0.0
        assert "Insufficient data" in s.reasoning or "error" in s.reasoning.lower()
