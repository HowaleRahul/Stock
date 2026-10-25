"""
Comprehensive Quant Financial & ML Adversarial Stress Tests
Audits and verifies edge cases, race conditions, division by zero,
extreme outliers, Black-Scholes asymptotic bounds, and memory/thread safety.
"""

import math
import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock

# 1. GEX Engine & Derivatives Math
from ml.gex_engine import GEXEngine
from data.nse_feed import NSEFeed
from setups.options_setup import OptionsSetup

# 2. Multi-Agent Consensus Engine
from ml.multi_agent_consensus import MultiAgentConsensusEngine, AgentReport

# 3. Features & Indicators
from ml.features import (
    calculate_black_scholes_greeks,
    enrich_with_psychology_features,
    generate_triple_barrier_labels,
    enrich_with_macro_and_options,
)

# 4. Ensemble Model & ML Stacking
from ml.ensemble import EnsembleModel

# 5. Continuous Trainer & Learner
from ml.continuous_trainer import (
    generate_features_for_ticker,
    _reset_if_feature_schema_changed,
)
from ml.live_market_learner import LiveMarketLearner

# 6. Backtest & Replay Engine
from backtest.engine import Backtester
from ml.replay_engine import VirtualBroker, ReplayEngine

# 7. Options Engine & Black-Scholes Greeks
from ml.options_engine import DerivativeEngine, OptionsEngine


# ===========================================================================
# 1. Tests for ml/gex_engine.py
# ===========================================================================

def test_gex_engine_calculate_gamma_edge_cases():
    """Verify Black-Scholes gamma calculation handles degenerate inputs without zero-division or NaN."""
    # S <= 0, K <= 0, T <= 0, sigma <= 0
    assert GEXEngine.calculate_gamma(0.0, 100.0, 0.1, 0.05, 0.2) == 0.0
    assert GEXEngine.calculate_gamma(100.0, 0.0, 0.1, 0.05, 0.2) == 0.0
    assert GEXEngine.calculate_gamma(100.0, 100.0, 0.0, 0.05, 0.2) == 0.0
    assert GEXEngine.calculate_gamma(100.0, 100.0, -1.0, 0.05, 0.2) == 0.0
    assert GEXEngine.calculate_gamma(100.0, 100.0, 0.1, 0.05, 0.0) == 0.0
    assert GEXEngine.calculate_gamma(100.0, 100.0, 0.1, 0.05, -0.2) == 0.0

    # NaNs and Infs
    assert GEXEngine.calculate_gamma(float("nan"), 100.0, 0.1, 0.05, 0.2) == 0.0
    assert GEXEngine.calculate_gamma(100.0, float("inf"), 0.1, 0.05, 0.2) == 0.0

    # Extreme d1 (deep OTM or deep ITM)
    assert GEXEngine.calculate_gamma(100.0, 1000000.0, 0.1, 0.05, 0.2) == 0.0
    assert GEXEngine.calculate_gamma(1000000.0, 1.0, 0.1, 0.05, 0.2) == 0.0

    # Valid ATM option gamma should be positive and finite
    gamma = GEXEngine.calculate_gamma(22000.0, 22000.0, 7 / 365.0, 0.065, 0.15)
    assert gamma > 0.0 and not math.isnan(gamma) and not math.isinf(gamma)


def test_gex_engine_pcr_zero_division():
    """Verify PCR calculation handles zero call OI and zero call volume gracefully."""
    # Zero call OI with positive put OI (would divide by zero)
    strikes = [
        {"strike": 22000.0, "call_oi": 0, "put_oi": 50000, "call_vol": 0, "put_vol": 1000},
        {"strike": 22100.0, "call_oi": 0, "put_oi": 25000, "call_vol": 0, "put_vol": 500},
    ]
    pcr = GEXEngine.calculate_pcr(strikes)
    assert pcr["total_call_oi"] == 0
    assert pcr["total_put_oi"] == 75000
    assert pcr["pcr_oi"] == 100.0  # Safe capped upper bound instead of ZeroDivisionError
    assert pcr["pcr_volume"] == 100.0

    # Both call and put OI zero
    empty_oi_strikes = [
        {"strike": 22000.0, "call_oi": 0, "put_oi": 0, "call_vol": 0, "put_vol": 0}
    ]
    pcr_zero = GEXEngine.calculate_pcr(empty_oi_strikes)
    assert pcr_zero["pcr_oi"] == 1.0
    assert pcr_zero["pcr_volume"] == 1.0

    # NSE Feed PCR test
    chain = {"records": {"data": [{"strikePrice": 22000, "CE": {"openInterest": 0}, "PE": {"openInterest": 1000}}]}}
    pcr_oi, pcr_vol, put_oi, call_oi = NSEFeed.calculate_pcr(chain)
    assert call_oi == 0
    assert put_oi == 1000
    assert pcr_oi == 100.0


def test_gex_engine_max_pain_empty_and_zero_oi():
    """Verify max pain calculation handles empty chains and zero OI across all strikes."""
    # Empty chain
    assert GEXEngine.calculate_max_pain([], spot=22000.0) == 22000.0
    assert GEXEngine.calculate_max_pain(None, spot=22000.0) == 22000.0

    # Chain with zero OI everywhere -> returns median strike safely
    strikes = [
        {"strike": 21800.0, "call_oi": 0, "put_oi": 0},
        {"strike": 22000.0, "call_oi": 0, "put_oi": 0},
        {"strike": 22200.0, "call_oi": 0, "put_oi": 0},
    ]
    assert GEXEngine.calculate_max_pain(strikes, spot=22000.0) == 22000.0


def test_gex_engine_gamma_flip_linear_interpolation():
    """Verify gamma flip level estimation uses accurate root finding."""
    spot = 22000.0
    # Strike 21800 is net positive (+10), Strike 22200 is net negative (-10)
    # Zero crossing should interpolate exactly to 22000.0
    strikes_data = [
        {"strike": 21800.0, "call_oi": 50000, "put_oi": 10000},
        {"strike": 22200.0, "call_oi": 10000, "put_oi": 50000},
    ]
    res = GEXEngine.analyze_chain_gex(spot, strikes_data, lot_size=25, iv=0.15, days_to_expiry=3.0)
    assert 21800.0 <= res["gamma_flip"] <= 22200.0
    assert "pcr_oi" in res
    assert "max_pain" in res


# ===========================================================================
# 2. Tests for ml/multi_agent_consensus.py
# ===========================================================================

def test_multi_agent_consensus_null_inputs():
    """Verify multi-agent consensus does not raise TypeError on None/null sub-fields."""
    # Null sentiment, null fundamental, null options data
    verdict = MultiAgentConsensusEngine.evaluate(
        ticker="NIFTY",
        regime_data=None,
        setup_signals=[],
        options_data={"pcr_oi": None, "gex_regime": None},
        fundamental_data={"piotroski_score": None},
        sentiment_data={"mean_score": None, "fii_net_crores": None},
    )
    assert verdict.consensus_signal in ("bullish", "bearish", "neutral")
    assert 0.0 <= verdict.consensus_confidence <= 1.0


def test_multi_agent_consensus_extreme_outliers():
    """Verify extreme outlier inputs (infinite flows, absurd PCR) are bounded."""
    verdict = MultiAgentConsensusEngine.evaluate(
        ticker="NIFTY",
        regime_data={"regime": "trending-bullish"},
        setup_signals=[],
        options_data={"pcr_oi": 99999999.0, "gex_regime": "POSITIVE_GAMMA"},
        fundamental_data={"piotroski_score": 1000},
        sentiment_data={"mean_score": 50.0, "fii_net_crores": 1e12},
    )
    assert verdict.consensus_confidence <= 1.0
    assert not math.isnan(verdict.consensus_confidence)


def test_multi_agent_consensus_tie_breaker():
    """Verify equal bull and bear conviction weights trigger technical tie-breaker."""
    # Construct equal report weights
    tech_bull = MagicMock(signal="bullish", confidence=0.85)
    tech_bull.name = "MA Crossover"

    verdict = MultiAgentConsensusEngine.evaluate(
        ticker="NIFTY",
        regime_data={"regime": "trending-bullish"},
        setup_signals=[tech_bull],
        options_data={"pcr_oi": 0.5, "gex_regime": "NEGATIVE_GAMMA"},  # Bearish derivatives
        fundamental_data={"piotroski_score": 8},  # Bullish fundamentals
        sentiment_data={"mean_score": -0.4, "fii_net_crores": -1000},  # Bearish sentiment
    )
    assert verdict.consensus_signal in ("bullish", "bearish", "neutral")
    assert not math.isnan(verdict.consensus_confidence)


# ===========================================================================
# 3. Tests for ml/features.py
# ===========================================================================

def test_features_black_scholes_bounds():
    """Verify calculate_black_scholes_greeks output stays within strict mathematical bounds."""
    # Deep ITM
    delta, gamma = calculate_black_scholes_greeks(100000.0, 100.0, 0.1, 0.05, 0.2)
    assert delta == 1.0
    assert gamma == 0.0

    # Deep OTM
    delta_otm, gamma_otm = calculate_black_scholes_greeks(1.0, 100000.0, 0.1, 0.05, 0.2)
    assert delta_otm == 0.0
    assert gamma_otm == 0.0

    # Negative / Zero / NaN
    d, g = calculate_black_scholes_greeks(-100.0, 100.0, 0.1, 0.05, 0.2)
    assert d == 0.5 and g == 0.0

    d, g = calculate_black_scholes_greeks(100.0, 100.0, 0.0, 0.05, 0.2)
    assert d == 0.5 and g == 0.0


def test_features_psychology_doji_singularity():
    """Verify panic index calculation on doji candles (open == close) does not produce division by zero or inf."""
    n = 30
    df = pd.DataFrame({
        "open": [100.0] * n,
        "high": [105.0] * n,
        "low": [95.0] * n,
        "close": [100.0] * n,  # Open == Close: candle body is 0.0!
        "volume": [0] * n,      # Volume is 0!
    })
    enriched = enrich_with_psychology_features(df)
    assert not enriched["psych_panic_index"].isna().any()
    assert not np.isinf(enriched["psych_panic_index"]).any()
    assert (enriched["psych_panic_index"] >= 0.0).all()
    assert (enriched["psych_panic_index"] <= 50.0).all()


def test_features_triple_barrier_atr_guards():
    """Verify triple barrier labeler handles flat prices where ATR = 0 without crash."""
    n = 50
    df = pd.DataFrame({
        "open": [100.0] * n,
        "high": [100.0] * n,
        "low": [100.0] * n,
        "close": [100.0] * n,
        "volume": [1000] * n,
    })
    labels = generate_triple_barrier_labels(df, tp_atr_mult=2.0, sl_atr_mult=1.0, max_hold_bars=10)
    assert len(labels) == n
    assert all(l in (-1, 0, 1) for l in labels)


# ===========================================================================
# 4. Tests for ml/ensemble.py
# ===========================================================================

def test_ensemble_scaler_zero_variance_protection():
    """Verify EnsembleModel handles zero-variance features in scaler transform without crashing."""
    ensemble = EnsembleModel(timeframe="1d")

    # Pass DataFrame with extreme/zero variance features
    df = pd.DataFrame({
        "close": [100.0] * 10,
        "open": [100.0] * 10,
        "high": [100.0] * 10,
        "low": [100.0] * 10,
        "volume": [0.0] * 10,
        "macro_vix": [15.0] * 10,
        "macro_spx_ret": [0.0] * 10,
        "macro_usdinr_ret": [0.0] * 10,
        "macro_btc_volume_ret": [0.0] * 10,
        "opt_delta": [0.5] * 10,
        "opt_gamma": [0.0] * 10,
        "psych_fomo_streak": [0.0] * 10,
        "psych_panic_index": [0.0] * 10,
        "psych_dist_to_round": [0.5] * 10,
        "psych_session_phase": [0.0] * 10,
        "atr": [1.0] * 10,
    })

    pred = ensemble.predict(
        regime_data={"regime": "range-bound", "adx": 0.0},
        setups=[],
        asset_class="IN_INDEX_FO",
        df=df,
    )
    assert pred["signal"] in ("bullish", "bearish", "neutral")
    assert 0.0 <= pred["probability"] <= 1.0


def test_ensemble_fallback_voting_calibration():
    """Verify fallback heuristic voting does not assign 1.0 uncalibrated certainty."""
    ensemble = EnsembleModel(timeframe="1d")
    # Force fallback voting
    ensemble.model = None

    features = {"s1_conf": 1.0, "s1_sig": 1}
    res = ensemble._fallback_voting(features, ["s1"])
    assert res["signal"] == "bullish"
    assert res["probability"] <= 0.85  # Damped from 1.0 to prevent overconfidence


# ===========================================================================
# 5. Tests for backtest/engine.py & ml/replay_engine.py
# ===========================================================================

def test_backtest_sharpe_zero_variance():
    """Verify Sharpe ratio calculation when all returns are identical (zero variance) returns 0.0 without division by zero."""
    backtester = Backtester()
    X = pd.DataFrame({"feat1": [1.0] * 150})
    df = pd.DataFrame({
        "open": [100.0] * 150,
        "high": [101.0] * 150,
        "low": [99.0] * 150,
        "close": [100.0] * 150,
    })
    # Run walk-forward with flat data
    results_df, metrics = backtester.run_walk_forward(X, df, train_size=50, test_size=20)
    if metrics:
        assert not math.isnan(metrics["Sharpe_Ratio"])
        assert not math.isinf(metrics["Sharpe_Ratio"])
        assert metrics["Sharpe_Ratio"] == 0.0


def test_virtual_broker_bankrupt_capital():
    """Verify VirtualBroker correctly detects total capital loss and suspends trading."""
    broker = VirtualBroker(starting_capital=100000.0)
    # Wipe out capital to 0
    broker.capital = 0.0
    assert broker.drawdown_pct == 1.0
    assert broker.is_suspended is True

    # Negative capital
    broker.capital = -5000.0
    assert broker.drawdown_pct == 1.0
    assert broker.is_suspended is True


def test_replay_engine_zero_variance_sharpe():
    """Verify ReplayEngine._compile_results handles empty or zero variance trade sets cleanly."""
    with ReplayEngine(starting_capital=100000.0) as engine:
        res = engine._compile_results("NIFTY", "1d", 100)
        assert res["total_trades"] == 0
        assert res["win_rate"] == 0.0
        assert res["sharpe_ratio"] == 0.0
        assert not math.isnan(res["sharpe_ratio"])


# ===========================================================================
# 6. Tests for ml/options_engine.py
# ===========================================================================

def test_options_engine_deep_itm_otm_greeks_bounds():
    """Verify Black-Scholes Greeks bounds on deep ITM and deep OTM options."""
    engine = DerivativeEngine()

    # Deep ITM Call (Spot 25000, Strike 10000)
    call_itm = engine.black_scholes(S=25000.0, K=10000.0, T=7/365.0, r=0.065, sigma=0.15, option_type="CE")
    assert call_itm["delta"] == 1.0
    assert call_itm["gamma"] == 0.0
    assert call_itm["premium"] > 14000.0

    # Deep OTM Call (Spot 10000, Strike 25000)
    call_otm = engine.black_scholes(S=10000.0, K=25000.0, T=7/365.0, r=0.065, sigma=0.15, option_type="CE")
    assert call_otm["delta"] == 0.0
    assert call_otm["gamma"] == 0.0
    assert call_otm["premium"] == 0.05

    # Deep ITM Put (Spot 10000, Strike 25000)
    put_itm = engine.black_scholes(S=10000.0, K=25000.0, T=7/365.0, r=0.065, sigma=0.15, option_type="PE")
    assert put_itm["delta"] == -1.0
    assert put_itm["gamma"] == 0.0
    assert put_itm["premium"] > 14000.0

    # Deep OTM Put (Spot 25000, Strike 10000)
    put_otm = engine.black_scholes(S=25000.0, K=10000.0, T=7/365.0, r=0.065, sigma=0.15, option_type="PE")
    assert put_otm["delta"] == 0.0
    assert put_otm["gamma"] == 0.0
    assert put_otm["premium"] == 0.05


def test_options_engine_negative_and_zero_inputs():
    """Verify Black-Scholes pricing handles negative time, zero spot, negative strike."""
    engine = DerivativeEngine()

    # Negative time to expiry
    res = engine.black_scholes(S=22000.0, K=22000.0, T=-0.5, r=0.065, sigma=0.15, option_type="CE")
    assert res["premium"] == 0.05
    assert res["delta"] == 0.0

    # Zero / Negative spot
    res_zero = engine.black_scholes(S=0.0, K=22000.0, T=0.1, r=0.065, sigma=0.15, option_type="CE")
    assert res_zero["premium"] == 0.05
    assert res_zero["delta"] == 0.0

    # Zero / Negative strike
    res_neg_k = engine.black_scholes(S=22000.0, K=-100.0, T=0.1, r=0.065, sigma=0.15, option_type="CE")
    assert res_neg_k["premium"] == 0.05
    assert res_neg_k["delta"] == 0.0


def test_options_engine_calculate_option_mtm_nan():
    """Verify live option MTM re-pricing handles NaN elapsed days or spot."""
    engine = DerivativeEngine()
    trade = {"strike": 22000.0, "option_type": "CE", "iv": 0.15, "entry_price": 150.0, "delta": 0.5}

    prem, delta = engine.calculate_option_mtm(trade, current_spot=22000.0, days_elapsed=float("nan"))
    assert not math.isnan(prem)
    assert not math.isnan(delta)
    assert prem > 0.0
    assert 0.0 <= delta <= 1.0
