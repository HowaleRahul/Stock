"""
Unit Tests for RL and Paper Trading Enhancements
Covers:
- Risk-adjusted reward shaping (R-multiples) in ReinforcementLearner
- Adaptive prior discounting upon regime change in ReinforcementLearner
- ExecutionArmBandit for dynamic parameter adaptation
- Integration of DrawdownCircuitBreaker and AgentReflector into LiveMarketLearner
- MultiAgentConsensus confirmation gate
"""

import os
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

from ml.reinforcement_learner import ReinforcementLearner, ExecutionArmBandit
from ml.circuit_breaker import DrawdownCircuitBreaker, CircuitConfig
from ml.agent_reflection import AgentReflector
from ml.multi_agent_consensus import MultiAgentConsensusEngine
from ml.live_market_learner import LiveMarketLearner
from data.realtime_feed import RealTimeDataFeed


def test_risk_adjusted_reward_shaping(tmp_path):
    """Verifies that R-multiple scaling adjusts Beta alpha and beta proportionally to risk."""
    weights_path = str(tmp_path / "setup_weights.json")
    learner = ReinforcementLearner(weights_file=weights_path)

    # 1. Trade with +4% gain on 2% risk (2R win)
    learner.update_from_trade(
        setup_signals=[{"name": "vcp_setup", "signal": "bullish", "confidence": 0.9}],
        regime="trending",
        pnl_pct=0.04,
        is_win=True,
        risk_pct=0.02,
        save=False
    )
    state_vcp = learner._state["weights"]["vcp_setup"]["trending"]
    # Baseline 1.0 + 2.0 (2R) = 3.0
    assert state_vcp["alpha"] == pytest.approx(3.0, rel=1e-2)
    assert state_vcp["beta"] == 1.0

    # 2. Trade with -3% loss on 1% risk (3R blowout loss)
    learner.update_from_trade(
        setup_signals=[{"name": "breakout_setup", "signal": "bullish", "confidence": 0.8}],
        regime="trending",
        pnl_pct=-0.03,
        is_win=False,
        risk_pct=0.01,
        save=False
    )
    state_bo = learner._state["weights"]["breakout_setup"]["trending"]
    # Baseline 1.0 + 3.0 (3R capped at 3.0) = 4.0
    assert state_bo["beta"] == pytest.approx(4.0, rel=1e-2)
    assert state_bo["alpha"] == 1.0


def test_adaptive_prior_discounting(tmp_path):
    """Verifies exponential decay of alpha and beta towards (1.0, 1.0) on regime shifts."""
    weights_path = str(tmp_path / "setup_weights.json")
    learner = ReinforcementLearner(weights_file=weights_path)

    learner.update_from_trade(
        setup_signals=[{"name": "ema_trend", "signal": "bullish", "confidence": 0.8}],
        regime="volatile",
        pnl_pct=0.06,
        is_win=True,
        risk_pct=0.02,
        save=False
    )
    # alpha should now be 1.0 + 3.0 = 4.0
    state = learner._state["weights"]["ema_trend"]["volatile"]
    assert state["alpha"] == pytest.approx(4.0, rel=1e-2)

    # Apply 50% discount
    updated = learner.discount_priors(regime="volatile", decay=0.5)
    assert updated == 1
    # alpha_new = 1.0 + (4.0 - 1.0) * 0.5 = 2.5
    assert state["alpha"] == pytest.approx(2.5, rel=1e-2)


def test_execution_arm_bandit():
    """Tests the Multi-Armed Bandit for execution parameter tuning."""
    bandit = ExecutionArmBandit(arms=[0.8, 1.0, 1.5, 2.0])
    selected = bandit.select_arm()
    assert selected in [0.8, 1.0, 1.5, 2.0]

    # Repeatedly reward arm 1.5 with high gains
    for _ in range(10):
        bandit.update_arm(arm=1.5, pnl_pct=0.05, is_win=True, risk_pct=0.02)

    # Arm 1.5 should now have the highest expected win probability
    summary = bandit.get_summary()
    assert summary["1.5"]["pulls"] == 10
    assert summary["1.5"]["expected_win_prob"] > 0.8
    assert summary["1.5"]["total_reward"] == pytest.approx(0.50, rel=1e-2)


def test_circuit_breaker_halts_live_scanning():
    """Tests that 3 consecutive losses trigger cooldown and halt LiveMarketLearner scans."""
    learner = LiveMarketLearner(starting_capital=100000.0)

    # Record 3 consecutive losses
    learner.circuit_breaker.record_trade_outcome(-0.02, -2000.0)
    learner.circuit_breaker.record_trade_outcome(-0.02, -2000.0)
    learner.circuit_breaker.record_trade_outcome(-0.02, -2000.0)

    decision = learner.circuit_breaker.evaluate(current_capital=learner.capital)
    assert not decision.is_allowed
    assert decision.status == "COOLDOWN"
    assert decision.consecutive_losses == 3

    # Scan for entries should immediately halt and open 0 positions
    learner.scan_for_entries()
    assert len(learner.open_trades) == 0


def test_agent_reflection_on_trade_exit(tmp_path):
    """Tests that AgentReflector generates structured post-trade memory lessons upon trade close."""
    reflections_file = str(tmp_path / "agent_reflections.jsonl")
    learner = LiveMarketLearner(starting_capital=100000.0)
    learner.agent_reflector = AgentReflector(reflections_file=reflections_file)

    fake_trade = {
        "id": "trade_ref_01",
        "ticker": "NIFTY",
        "direction": "LONG",
        "instrument_type": "OPTION",
        "quantity": 50,
        "entry_price": 100.0,
        "invested": 5000.0,
        "sl": 70.0,
        "tp": 160.0,
        "trailing_stop": 70.0,
        "bars_held": 3,
        "status": "OPEN",
        "current_ltp": 165.0,
        "setup_signals": [{"name": "vcp_setup", "signal": "bullish", "confidence": 0.85}],
        "regime": "trending"
    }
    learner.open_trades.append(fake_trade)

    # Trigger TP exit
    with patch.object(RealTimeDataFeed, "get_realtime_quote_sync", return_value={"ltp": 22200.0, "high": 22250.0, "low": 22150.0}), \
         patch.object(learner.derivative_engine, "calculate_option_mtm", return_value=(165.0, 0.65)):
        learner.manage_open_trades()

    assert len(learner.open_trades) == 0
    assert len(learner.closed_trades) == 1
    assert learner.closed_trades[0]["status"] == "TAKE_PROFIT"

    # Verify reflection was generated and persisted
    reflections = learner.agent_reflector.get_recent_reflections(limit=5)
    assert len(reflections) == 1
    assert "Rule:" in reflections[0]["lesson"]
    assert "vcp_setup" in reflections[0]["lesson"]


def test_portfolio_state_includes_circuit_breaker():
    """Verifies that get_portfolio_state exposes the circuit breaker status to the UI."""
    learner = LiveMarketLearner(starting_capital=50000.0)
    state = learner.get_portfolio_state()
    assert "circuit_breaker" in state
    assert state["circuit_breaker"]["status"] == "TRADING_ALLOWED"
    assert state["circuit_breaker"]["is_allowed"] is True
