"""
Unit and Integration Tests for Live Market Paper Trading, Market Hours,
Real-Time Feed, and TradingView Charting Engine.
"""

import pytest
import datetime
from unittest.mock import patch, MagicMock

from data.market_hours import (
    IST,
    get_market_session,
    is_market_open,
    is_weekend,
    is_nse_holiday,
    get_market_status
)
from data.realtime_feed import RealTimeDataFeed
from ml.live_market_learner import LiveMarketLearner


# =========================================================================
# 1. Market Hours Tests
# =========================================================================

def test_market_session_regular_hours():
    # Wednesday at 11:30 AM IST
    wed_1130 = datetime.datetime(2026, 10, 21, 11, 30, tzinfo=IST)
    assert get_market_session(wed_1130) == "REGULAR"
    assert is_market_open("NSE", wed_1130) is True


def test_market_session_pre_open():
    # Wednesday at 09:05 AM IST
    wed_0905 = datetime.datetime(2026, 10, 21, 9, 5, tzinfo=IST)
    assert get_market_session(wed_0905) == "PRE_OPEN"
    assert is_market_open("NSE", wed_0905) is False


def test_market_session_after_hours():
    # Wednesday at 17:30 IST
    wed_1730 = datetime.datetime(2026, 10, 21, 17, 30, tzinfo=IST)
    assert get_market_session(wed_1730) == "CLOSED"
    assert is_market_open("NSE", wed_1730) is False


def test_market_session_weekend():
    # Saturday at 11:00 AM IST
    sat_1100 = datetime.datetime(2026, 10, 24, 11, 0, tzinfo=IST)
    assert is_weekend(sat_1100) is True
    assert get_market_session(sat_1100) == "CLOSED"
    assert is_market_open("NSE", sat_1100) is False


def test_crypto_is_always_open():
    wed_midnight = datetime.datetime(2026, 10, 21, 0, 0, tzinfo=IST)
    assert is_market_open("CRYPTO", wed_midnight) is True
    assert is_market_open("BINANCE", wed_midnight) is True


def test_get_market_status_structure():
    status = get_market_status("NSE")
    assert "exchange" in status
    assert "is_open" in status
    assert "session" in status
    assert "current_time_ist" in status
    assert "seconds_until_open" in status
    assert "message" in status


# =========================================================================
# 2. Real-Time Feed Tests
# =========================================================================

def test_symbol_resolution():
    sym, ex, sc = RealTimeDataFeed._resolve_symbol("NIFTY")
    assert sym == "NIFTY"
    assert ex == "NSE"
    assert sc == "india"

    sym, ex, sc = RealTimeDataFeed._resolve_symbol("^NSEBANK")
    assert sym == "BANKNIFTY"
    assert ex == "NSE"

    sym, ex, sc = RealTimeDataFeed._resolve_symbol("RELIANCE.NS")
    assert sym == "RELIANCE"
    assert ex == "NSE"


def test_quote_structure():
    quote = RealTimeDataFeed.get_realtime_quote_sync("NIFTY")
    assert "ticker" in quote
    assert "ltp" in quote
    assert "open" in quote
    assert "high" in quote
    assert "low" in quote
    assert "recommendation" in quote
    assert quote["exchange"] == "NSE"


def test_tradingview_ta_structure():
    ta = RealTimeDataFeed.get_tradingview_analysis_sync("NIFTY", interval="1h")
    assert "ticker" in ta
    assert "summary" in ta
    assert "indicators" in ta
    assert "RECOMMENDATION" in ta["summary"]


def test_chart_candles_structure():
    candles = RealTimeDataFeed.get_chart_candles_sync("NIFTY", timeframe="1d", limit=10)
    assert isinstance(candles, list)
    if candles:
        first = candles[0]
        assert "time" in first
        assert "open" in first
        assert "high" in first
        assert "low" in first
        assert "close" in first


# =========================================================================
# 3. Live Market Learner & Virtual Capital Tests (Frontpage mechanics)
# =========================================================================

def test_virtual_capital_initialization():
    learner = LiveMarketLearner(starting_capital=1000000.0)
    state = learner.get_portfolio_state()
    assert state["starting_capital"] == 1000000.0
    assert state["cash_balance"] == 1000000.0
    assert state["net_liquidation_value"] == 1000000.0
    assert state["open_positions_count"] == 0
    assert state["unrealized_mtm"] == 0.0


def test_live_mtm_calculation():
    learner = LiveMarketLearner(starting_capital=1000000.0)
    # Simulate an open LONG trade
    fake_trade = {
        "id": "trade_001",
        "ticker": "NIFTY",
        "direction": "LONG",
        "quantity": 50,
        "entry_price": 22000.0,
        "invested": 100000.0,
        "sl": 21800.0,
        "tp": 22500.0,
        "trailing_stop": 21800.0,
        "bars_held": 1,
        "status": "OPEN"
    }
    learner.open_trades.append(fake_trade)

    with patch.object(RealTimeDataFeed, "get_realtime_quote_sync", return_value={"ltp": 22100.0, "high": 22150.0, "low": 22050.0}):
        learner.update_live_mtm()
        state = learner.get_portfolio_state()
        # 50 qty * (22100 - 22000) = +5,000 MTM
        assert state["unrealized_mtm"] == 5000.0
        assert state["net_liquidation_value"] == 1005000.0


def test_stop_loss_trigger_and_learning():
    learner = LiveMarketLearner(starting_capital=1000000.0)
    fake_trade = {
        "id": "trade_002",
        "ticker": "NIFTY",
        "direction": "LONG",
        "quantity": 50,
        "entry_price": 22000.0,
        "invested": 100000.0,
        "sl": 21800.0,
        "tp": 22500.0,
        "trailing_stop": 21800.0,
        "bars_held": 2,
        "status": "OPEN",
        "setup_signals": [{"name": "rsi_setup", "signal": "bullish", "confidence": 0.8}],
        "regime": "trending"
    }
    learner.open_trades.append(fake_trade)

    # Price falls below SL (low = 21750 <= 21800)
    with patch.object(RealTimeDataFeed, "get_realtime_quote_sync", return_value={"ltp": 21780.0, "high": 21900.0, "low": 21750.0}):
        learner.manage_open_trades()
        # Trade should be closed
        assert len(learner.open_trades) == 0
        assert len(learner.closed_trades) == 1
        closed = learner.closed_trades[0]
        assert closed["status"] in ("STOP_LOSS", "TRAILING_SL")
        assert closed["pnl_pct"] < 0


# =========================================================================
# 4. Micro-Capital & Dynamic Capital Tier Protection Tests (₹10,000 Support)
# =========================================================================

import pandas as pd
from ml.risk_engine import RiskEngine


def test_capital_tier_classification():
    micro = RiskEngine.get_capital_tier(10000.0)
    assert micro["tier"] == "MICRO"
    assert micro["max_risk_pct"] == 0.015
    assert micro["max_allocation_pct"] == 0.35
    assert micro["min_ai_confidence"] == 0.68
    assert micro["min_rr_ratio"] == 1.8
    assert micro["early_breakeven_atr"] == 0.8

    small = RiskEngine.get_capital_tier(50000.0)
    assert small["tier"] == "SMALL"
    assert small["max_risk_pct"] == 0.02
    assert small["min_ai_confidence"] == 0.65

    growth = RiskEngine.get_capital_tier(1000000.0)
    assert growth["tier"] == "GROWTH"
    assert growth["max_risk_pct"] == 0.02
    assert growth["min_ai_confidence"] == 0.60


def test_micro_capital_spot_unaffordable_gate():
    engine = RiskEngine()
    df = pd.DataFrame({
        "close": [22800.0] * 30,
        "high": [22850.0] * 30,
        "low": [22750.0] * 30,
        "atr": [100.0] * 30
    })
    plan = engine.generate_trade_plan(
        ticker="NIFTY",
        direction="bullish",
        ai_probability=0.75,
        df=df,
        capital=10000.0
    )
    assert plan.is_approved is False
    assert len(plan.rejection_reasons) > 0
    assert any("exceeds available capital" in r for r in plan.rejection_reasons)
    assert any("affordable constituent" in r for r in plan.rejection_reasons)


def test_micro_capital_affordable_stock_sizing():
    engine = RiskEngine()
    # High at 800 gives ample R:R (> 1.8:1) to satisfy MICRO tier quality gate
    df = pd.DataFrame({
        "close": [780.0] * 30,
        "high": [800.0] * 30,
        "low": [775.0] * 30,
        "atr": [10.0] * 30
    })
    plan = engine.generate_trade_plan(
        ticker="SBIN",
        direction="bullish",
        ai_probability=0.72,
        df=df,
        capital=10000.0
    )
    assert plan.is_approved is True
    assert plan.capital_tier == "MICRO"
    assert plan.position_size_qty > 0
    assert plan.position_size_qty * plan.entry_price <= 3500.0
    risk_amount = plan.position_size_qty * (plan.entry_price - plan.stop_loss)
    assert risk_amount <= 150.01


def test_micro_capital_confidence_gate_rejection():
    engine = RiskEngine()
    df = pd.DataFrame({
        "close": [780.0] * 30,
        "high": [800.0] * 30,
        "low": [775.0] * 30,
        "atr": [10.0] * 30
    })
    plan = engine.generate_trade_plan(
        ticker="SBIN",
        direction="bullish",
        ai_probability=0.62,
        df=df,
        capital=10000.0
    )
    assert plan.is_approved is False
    assert any("requirement for MICRO capital tier" in r for r in plan.rejection_reasons)


def test_micro_capital_early_breakeven_trailing_stop():
    trade = {
        "direction": "LONG",
        "entry_price": 780.0,
        "atr_at_entry": 10.0,
        "sl": 765.0,
        "trailing_stop": 765.0,
        "capital_tier": "MICRO",
        "invested": 3120.0
    }
    updated = RiskEngine.update_trailing_stop(trade, current_high=788.5, current_low=779.0)
    assert updated["trailing_stop"] >= 780.0


# =========================================================================
# 5. F&O Derivative Smart Routing, Strike Selection & FOLearner Tests
# =========================================================================

import os
from ml.options_engine import DerivativeEngine, FOLearner


def test_fo_auto_routing_budget_selects_options_on_micro_capital():
    engine = DerivativeEngine()
    risk_eng = RiskEngine()
    df = pd.DataFrame({
        "close": [22800.0] * 30,
        "high": [22950.0] * 30,
        "low": [22750.0] * 30,
        "atr": [70.0] * 30
    })
    spot_plan = risk_eng.generate_trade_plan(
        ticker="NIFTY",
        direction="bullish",
        ai_probability=0.75,
        df=df,
        capital=100000.0
    )
    # Under ₹10,000 budget, AUTO mode must route to Options (Futures margin ~₹85k-₹1.15L is unaffordable)
    d_plan = engine.generate_derivative_plan(
        spot_plan=spot_plan,
        capital=10000.0,
        derivative_type="AUTO",
        strike_pref="AUTO",
        regime="trending"
    )
    assert d_plan.instrument_type == "OPTION"
    assert d_plan.option_type == "CE"
    assert d_plan.lot_size == 25
    assert d_plan.total_quantity == 25
    assert d_plan.margin_or_premium_required <= 10000.0
    assert d_plan.entry_price > 0.0


def test_fo_futures_rejection_on_insufficient_margin():
    engine = DerivativeEngine()
    risk_eng = RiskEngine()
    df = pd.DataFrame({
        "close": [22800.0] * 30,
        "high": [22950.0] * 30,
        "low": [22750.0] * 30,
        "atr": [70.0] * 30
    })
    spot_plan = risk_eng.generate_trade_plan(
        ticker="NIFTY",
        direction="bullish",
        ai_probability=0.75,
        df=df,
        capital=100000.0
    )
    # Explicitly requesting FUTURES with only ₹10k capital must be rejected with helpful margin notice
    d_plan = engine.generate_derivative_plan(
        spot_plan=spot_plan,
        capital=10000.0,
        derivative_type="FUTURES",
        regime="trending"
    )
    assert d_plan.instrument_type == "FUTURE"
    assert d_plan.is_approved is False
    assert any("Futures Margin Deficit" in r for r in d_plan.rejection_reasons)


def test_fo_futures_approval_on_ample_capital():
    engine = DerivativeEngine()
    risk_eng = RiskEngine()
    df = pd.DataFrame({
        "close": [22800.0] * 30,
        "high": [22950.0] * 30,
        "low": [22750.0] * 30,
        "atr": [70.0] * 30
    })
    spot_plan = risk_eng.generate_trade_plan(
        ticker="NIFTY",
        direction="bullish",
        ai_probability=0.80,
        df=df,
        capital=1000000.0
    )
    # With ₹10 Lakh capital, Futures is approved with exact NSE lot size
    d_plan = engine.generate_derivative_plan(
        spot_plan=spot_plan,
        capital=1000000.0,
        derivative_type="FUTURES",
        regime="trending"
    )
    assert d_plan.instrument_type == "FUTURE"
    assert d_plan.is_approved is True
    assert d_plan.lot_size == 25
    assert d_plan.lots_to_trade == 1
    assert d_plan.delta == 1.0


def test_fo_strike_selection_deltas():
    engine = DerivativeEngine()
    # At spot 22,800:
    # ITM (22,750 CE) should have delta > ATM (22,800 CE) > OTM (22,850 CE)
    bs_itm = engine.black_scholes(S=22800, K=22750, T=7/365, r=0.065, sigma=0.14, option_type="CE")
    bs_atm = engine.black_scholes(S=22800, K=22800, T=7/365, r=0.065, sigma=0.14, option_type="CE")
    bs_otm = engine.black_scholes(S=22800, K=22850, T=7/365, r=0.065, sigma=0.14, option_type="CE")

    assert bs_itm["delta"] > bs_atm["delta"]
    assert bs_atm["delta"] > bs_otm["delta"]
    assert bs_itm["premium"] > bs_atm["premium"]
    assert bs_atm["premium"] > bs_otm["premium"]


def test_fo_learner_reinforcement_updates():
    test_path = "ml/models/test_fo_weights.json"
    learner = FOLearner(state_file=test_path)
    fake_trade = {
        "instrument_type": "OPTION",
        "strike_type": "ATM",
        "ticker": "NIFTY",
        "regime": "trending"
    }
    learner.update_from_trade(fake_trade, net_pnl_pct=0.20)
    summary = learner.get_summary()
    assert summary["total_fo_trades"] >= 1
    assert summary["options_win_rate"] > 0
    if os.path.exists(test_path):
        try:
            os.unlink(test_path)
        except Exception:
            pass


