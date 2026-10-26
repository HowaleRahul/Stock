"""
Unit & Adversarial Tests for Broker Adapter, Matching Engine, and Greek Specifications
"""

import math
import pytest
from datetime import datetime
from starlette.testclient import TestClient

from api.broker_adapter import UnifiedBrokerAdapter, PaperMatchingEngine, NormalizedOrder
from api.main import app


# ===========================================================================
# 1. Paper Matching Engine Adversarial & Edge Cases
# ===========================================================================

def test_paper_matching_engine_rejects_invalid_inputs():
    engine = PaperMatchingEngine()

    # Negative quantity
    o1 = NormalizedOrder(order_id="INV_01", symbol="NIFTY", direction="BUY", quantity=-10, order_type="MARKET")
    res1 = engine.submit_order(o1, current_ltp=22000.0)
    assert res1.status == "REJECTED"

    # Zero quantity
    o2 = NormalizedOrder(order_id="INV_02", symbol="NIFTY", direction="BUY", quantity=0, order_type="MARKET")
    res2 = engine.submit_order(o2, current_ltp=22000.0)
    assert res2.status == "REJECTED"

    # Invalid direction
    o3 = NormalizedOrder(order_id="INV_03", symbol="NIFTY", direction="SIDEWAYS", quantity=25, order_type="MARKET")
    res3 = engine.submit_order(o3, current_ltp=22000.0)
    assert res3.status == "REJECTED"

    # Invalid order type
    o4 = NormalizedOrder(order_id="INV_04", symbol="NIFTY", direction="BUY", quantity=25, order_type="OCO")
    res4 = engine.submit_order(o4, current_ltp=22000.0)
    assert res4.status == "REJECTED"

    # Non-positive limit price for LIMIT order
    o5 = NormalizedOrder(order_id="INV_05", symbol="NIFTY", direction="BUY", quantity=25, order_type="LIMIT", price=0.0)
    res5 = engine.submit_order(o5, current_ltp=22000.0)
    assert res5.status == "REJECTED"

    # Non-positive trigger price for SL-M order
    o6 = NormalizedOrder(order_id="INV_06", symbol="NIFTY", direction="SELL", quantity=25, order_type="SL-M", trigger_price=-10.0)
    res6 = engine.submit_order(o6, current_ltp=22000.0)
    assert res6.status == "REJECTED"

    # Invalid LTP
    o7 = NormalizedOrder(order_id="INV_07", symbol="NIFTY", direction="BUY", quantity=25, order_type="MARKET")
    res7 = engine.submit_order(o7, current_ltp=0.0)
    assert res7.status == "REJECTED"


def test_paper_matching_engine_sl_limit_multi_tick_continuation():
    engine = PaperMatchingEngine(slippage_pct=0.0)

    # Establish long position at 100
    buy = NormalizedOrder(order_id="BUY_POS", symbol="NIFTY_OPT", direction="BUY", quantity=50, order_type="MARKET")
    engine.submit_order(buy, current_ltp=100.0)
    assert engine.positions["NIFTY_OPT"]["quantity"] == 50

    # Place Stop-Loss Limit: Sell if price drops to/below 95, but only sell at 96 or higher
    sl_limit = NormalizedOrder(
        order_id="SL_L_01",
        symbol="NIFTY_OPT",
        direction="SELL",
        quantity=50,
        order_type="SL",
        trigger_price=95.0,
        price=96.0
    )
    engine.submit_order(sl_limit, current_ltp=100.0)
    assert "SL_L_01" in engine.resting_orders
    assert engine.resting_orders["SL_L_01"].status == "PENDING"

    # Tick 1: ltp = 97.0 (above trigger) -> nothing happens
    fills_t1 = engine.on_tick("NIFTY_OPT", ltp=97.0)
    assert len(fills_t1) == 0
    assert engine.resting_orders["SL_L_01"].status == "PENDING"

    # Tick 2: ltp = 94.0, low = 94.0 -> triggers (94 <= 95), but market is 94 < limit 96
    fills_t2 = engine.on_tick("NIFTY_OPT", ltp=94.0, low=94.0, high=95.0)
    assert len(fills_t2) == 0
    assert "SL_L_01" in engine.resting_orders
    assert engine.resting_orders["SL_L_01"].status == "TRIGGERED"

    # Tick 3: price rebounds to 96.5, high = 97.0 -> even though price is above trigger,
    # order is already TRIGGERED and now limit condition (h >= 96) is met!
    fills_t3 = engine.on_tick("NIFTY_OPT", ltp=96.5, low=95.5, high=97.0)
    assert len(fills_t3) == 1
    assert fills_t3[0].status == "FILLED"
    assert fills_t3[0].fill_price == 96.0
    assert "SL_L_01" not in engine.resting_orders
    assert engine.positions["NIFTY_OPT"]["quantity"] == 0

    # Verify order is in history
    assert any(o.order_id == "SL_L_01" and o.status == "FILLED" for o in engine.order_history)


def test_paper_matching_engine_order_cancellation_and_lookup():
    engine = PaperMatchingEngine()

    limit_order = NormalizedOrder(
        order_id="LMT_999",
        symbol="BANKNIFTY",
        direction="BUY",
        quantity=15,
        order_type="LIMIT",
        price=45000.0
    )
    engine.submit_order(limit_order, current_ltp=46000.0)
    assert "LMT_999" in engine.resting_orders

    # Lookup resting order
    found = engine.get_order("LMT_999")
    assert found is not None
    assert found.status == "PENDING"

    # Cancel order
    ok = engine.cancel_order("LMT_999")
    assert ok is True
    assert "LMT_999" not in engine.resting_orders

    # Order is now in history with CANCELLED status
    cancelled = engine.get_order("LMT_999")
    assert cancelled is not None
    assert cancelled.status == "CANCELLED"

    # Cancel non-existent order returns False
    assert engine.cancel_order("NON_EXISTENT") is False


def test_unified_broker_adapter_methods():
    adapter = UnifiedBrokerAdapter(broker_name="paper")
    assert adapter.connect() is True

    # Place limit order
    oid = adapter.place_order(
        symbol="NIFTY",
        quantity=25,
        direction="BUY",
        order_type="LIMIT",
        price=21000.0,
        current_ltp=22000.0
    )
    assert adapter.get_order(oid) is not None
    assert adapter.get_order(oid).status == "PENDING"

    # Cancel via adapter
    cancelled = adapter.cancel_order(oid)
    assert cancelled is True
    assert adapter.get_order(oid).status == "CANCELLED"

    history = adapter.get_order_history()
    assert any(o.order_id == oid for o in history)


# ===========================================================================
# 2. Options Greeks (Rho & Wing Specs) API Verification
# ===========================================================================

def test_market_router_option_tick_returns_rho():
    client = TestClient(app)
    resp = client.get("/api/v1/market/option-tick", params={"underlying": "NIFTY", "strike": 22800, "option_type": "CE"})
    assert resp.status_code == 200
    data = resp.json()
    assert "rho" in data
    assert isinstance(data["rho"], (int, float))
    assert "delta" in data
    assert "theta" in data
    assert "gamma" in data
    assert "vega" in data
    assert "iv" in data


def test_market_router_option_chart_returns_rho():
    client = TestClient(app)
    resp = client.get("/api/v1/market/option-chart", params={"underlying": "NIFTY", "strike": 22800, "option_type": "CE"})
    assert resp.status_code == 200
    data = resp.json()
    assert "greeks" in data
    greeks = data["greeks"]
    assert "rho" in greeks
    assert isinstance(greeks["rho"], (int, float))
    assert "delta" in greeks
    assert "theta" in greeks
    assert "gamma" in greeks
    assert "vega" in greeks
    assert "iv" in greeks


def test_dashboard_portfolio_returns_enhanced_fo_specs(monkeypatch):
    client = TestClient(app)
    # Mock database to force fallback to paper_trades.json with full condor specs
    import os
    import json
    mock_trade = [{
        "id": "TRADE_CONDOR_01",
        "ticker": "NIFTY",
        "direction": "SELL",
        "status": "OPEN",
        "entry_price": 85.0,
        "quantity": 25,
        "invested": 2125.0,
        "tp": 25.0,
        "sl": 150.0,
        "strategy_type": "IRON_CONDOR",
        "action": "SELL",
        "is_fo": True,
        "opt_delta": -0.05,
        "opt_theta": 18.5,
        "opt_gamma": 0.0008,
        "opt_vega": -14.2,
        "opt_rho": 0.12,
        "opt_iv": 16.5,
        "short_put_strike": 22700,
        "long_put_strike": 22600,
        "short_call_strike": 22900,
        "long_call_strike": 23000,
        "lower_breakeven": 22615.0,
        "upper_breakeven": 22985.0,
        "net_credit": 85.0,
    }]
    monkeypatch.setattr("os.path.exists", lambda p: True if "paper_trades.json" in p or "paper_account.json" in p else False)
    
    import builtins
    orig_open = builtins.open
    def mock_open(file, *args, **kwargs):
        if "paper_trades.json" in str(file):
            import io
            return io.StringIO(json.dumps(mock_trade))
        elif "paper_account.json" in str(file):
            import io
            return io.StringIO(json.dumps({"capital": 100000.0, "peak_capital": 100000.0, "status": "ACTIVE"}))
        return orig_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", mock_open)
    
    # Force database failure so fallback is invoked
    from api import dashboard_router
    async def mock_fail_session():
        raise RuntimeError("DB simulated offline")
    monkeypatch.setattr(dashboard_router, "async_session_factory", mock_fail_session)

    resp = client.get("/api/v1/dashboard/portfolio")
    assert resp.status_code == 200
    data = resp.json()
    assert "open_trades" in data
    assert len(data["open_trades"]) == 1
    t = data["open_trades"][0]
    assert t["order_id"] == "TRADE_CONDOR_01"
    assert t["strategy_type"] == "IRON_CONDOR"
    assert t["action"] == "SELL"
    assert t["short_put_strike"] == 22700
    assert t["long_put_strike"] == 22600
    assert t["short_call_strike"] == 22900
    assert t["long_call_strike"] == 23000
    assert t["lower_breakeven"] == 22615.0
    assert t["upper_breakeven"] == 22985.0
    assert t["net_credit"] == 85.0
    assert t["opt_rho"] == 0.12
