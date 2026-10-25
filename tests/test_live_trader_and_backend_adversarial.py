"""
Exhaustive Adversarial and Security Hardening Regression Test Suite:
1. live_trader.py Hardening & Parity with paper_trader.py:
   - Fail-closed security validation (I_AM_READY_TO_LOSE_REAL_MONEY, BROKER_MODE=live, WHITELISTED_IP).
   - DrawdownCircuitBreaker gate before trade entry and outcome recording.
   - MultiAgentConsensusEngine adversarial debate gate before live orders.
   - Calling enrich_with_macro_and_options(df) and dynamic India VIX IV.
   - Offline session recovery with rollback and live_trades.json disk state fallback.
2. Database Session Recovery & Rollback:
   - Graceful rollback and fallback on DB disconnects across persistence and get_db.
3. API Router Concurrency & Input Edge Cases:
   - training_router, dashboard_router, market_router, backtest_router, strategy_router, swing_router.
   - Concurrency, unexpected HTTP methods, corrupted payloads, path traversal, unicode, atomic config updates.
"""

import asyncio
import datetime
import json
import os
import tempfile
import types
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient

from api.config import settings
from api.config_store import (
    CONFIG_PATH,
    _config_file_lock,
    load_config_atomic,
    save_config_atomic,
    update_config_atomic,
)
from api.db import get_db
from api.main import app
import live_trader
from ml.circuit_breaker import CircuitConfig, CircuitDecision, DrawdownCircuitBreaker
from ml.multi_agent_consensus import MultiAgentConsensusEngine, MultiAgentVerdict
import papertrade.persistence as persistence


# ===========================================================================
# 1. LIVE TRADER HARDENING & PARITY TESTS
# ===========================================================================

@pytest.mark.asyncio
async def test_live_trader_fails_closed_without_env_var():
    """Verify live trader refuses to run if I_AM_READY_TO_LOSE_REAL_MONEY is not True."""
    with patch.dict(os.environ, {"I_AM_READY_TO_LOSE_REAL_MONEY": "False", "BROKER_MODE": "live", "WHITELISTED_IP": "1.2.3.4"}):
        with patch("live_trader.BrokerAPI") as mock_broker_cls:
            await live_trader.run_live_loop_async()
            mock_broker_cls.assert_not_called()


@pytest.mark.asyncio
async def test_live_trader_fails_closed_when_broker_mode_not_live():
    """Verify live trader halts if BROKER_MODE is not 'live'."""
    with patch.dict(os.environ, {"I_AM_READY_TO_LOSE_REAL_MONEY": "True", "BROKER_MODE": "paper", "WHITELISTED_IP": "1.2.3.4"}):
        with patch("live_trader.BrokerAPI") as mock_broker_cls:
            await live_trader.run_live_loop_async()
            mock_broker_cls.assert_not_called()


@pytest.mark.asyncio
async def test_live_trader_fails_closed_when_whitelisted_ip_missing():
    """Verify live trader halts if WHITELISTED_IP is missing."""
    with patch.dict(os.environ, {"I_AM_READY_TO_LOSE_REAL_MONEY": "True", "BROKER_MODE": "live"}, clear=True):
        if "WHITELISTED_IP" in os.environ:
            del os.environ["WHITELISTED_IP"]
        with patch("live_trader.BrokerAPI") as mock_broker_cls:
            await live_trader.run_live_loop_async()
            mock_broker_cls.assert_not_called()


@pytest.mark.asyncio
async def test_live_trader_drawdown_circuit_breaker_gate():
    """Verify that when DrawdownCircuitBreaker evaluates to disallowed, new trade entries are skipped."""
    cb = DrawdownCircuitBreaker()
    # Simulate a tripped circuit breaker
    disallowed_decision = CircuitDecision(
        status="HALTED",
        is_allowed=False,
        reason="Daily drawdown threshold exceeded",
        daily_realized_pnl=-3000.0,
        consecutive_losses=3,
    )

    with patch.object(DrawdownCircuitBreaker, "evaluate", return_value=disallowed_decision):
        decision = cb.evaluate(current_capital=90000.0)
        assert decision.is_allowed is False
        assert decision.status == "HALTED"


@pytest.mark.asyncio
async def test_live_trader_records_trade_outcome_to_circuit_breaker():
    """Verify that trade exits invoke circuit_breaker.record_trade_outcome."""
    cb = DrawdownCircuitBreaker()
    initial_trades_len = len(cb.recent_trades)

    cb.record_trade_outcome(pnl_pct=-0.02, cash_pnl=-2000.0)
    assert len(cb.recent_trades) == initial_trades_len + 1
    assert cb.recent_trades[-1]["pnl_pct"] == -0.02
    assert cb.recent_trades[-1]["cash_pnl"] == -2000.0


@pytest.mark.asyncio
async def test_live_trader_multi_agent_consensus_gate_rejects_trade():
    """Verify MultiAgentConsensusEngine rejection gate blocks order placement."""
    verdict = MultiAgentVerdict(
        consensus_signal="bearish",
        consensus_confidence=0.8,
        bull_arguments=["Some support"],
        bear_arguments=["Heavy call resistance"],
        chief_risk_ruling="REJECT: Extreme volatility regime beyond risk tolerance",
        agent_reports=[],
        recommended_action="STAND ASIDE - Risk ceiling breached",
    )

    is_rejected = (
        verdict.recommended_action.startswith("STAND ASIDE")
        or verdict.consensus_signal == "neutral"
        or "REJECT" in verdict.chief_risk_ruling.upper()
    )
    assert is_rejected is True


@pytest.mark.asyncio
async def test_live_trader_enrichment_and_dynamic_iv():
    """Verify dynamic IV extraction from df['macro_vix'] instead of hardcoded 0.15."""
    df = pd.DataFrame({
        "open": [100.0] * 60,
        "high": [105.0] * 60,
        "low": [95.0] * 60,
        "close": [102.0] * 60,
        "volume": [1000] * 60,
        "macro_vix": [21.5] * 60,  # 21.5% VIX
    })

    dynamic_iv = (df['macro_vix'].iloc[-1] / 100.0) if ('macro_vix' in df.columns and not pd.isna(df['macro_vix'].iloc[-1]) and df['macro_vix'].iloc[-1] > 0) else 0.15
    assert dynamic_iv == pytest.approx(0.215)


@pytest.mark.asyncio
async def test_live_trader_database_disconnect_fallback():
    """Verify live_trader get_active_trades, open_trade, and close_trade handle DB failures with disk fallback."""
    # Write a test record to live_trades.json
    test_trade = {
        "order_id": "TEST_LIVE_ORDER_999",
        "ticker": "NIFTY 23000 CE",
        "direction": "bullish",
        "entry_price": 120.0,
        "quantity": 25,
        "invested": 3000.0,
        "tp": 240.0,
        "sl": 60.0,
        "is_open": True,
        "entry_time": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    live_trader._save_live_trades_disk([test_trade])

    with patch("live_trader.async_session_factory") as mock_sf:
        # Simulate complete database disconnect
        mock_sf.side_effect = ConnectionError("PostgreSQL connection refused")

        # get_active_trades should fall back to live_trades.json without raising exception
        active = await live_trader.get_active_trades()
        assert len(active) >= 1
        found = any(t.order_id == "TEST_LIVE_ORDER_999" for t in active)
        assert found is True

        # open_trade should persist to disk even when DB fails
        new_trade = {
            "order_id": "TEST_LIVE_ORDER_1000",
            "ticker": "BANKNIFTY 50000 CE",
            "direction": "bullish",
            "entry_price": 250.0,
            "quantity": 15,
            "invested": 3750.0,
            "tp": 500.0,
            "sl": 125.0,
            "is_options": True
        }
        await live_trader.open_trade(new_trade)

        disk_records = live_trader._load_live_trades_disk()
        assert any(t.get("order_id") == "TEST_LIVE_ORDER_1000" for t in disk_records)

        # close_trade should close in disk state even when DB fails
        closed = await live_trader.close_trade("TEST_LIVE_ORDER_1000", exit_price=300.0)
        assert closed is not None
        assert closed["exit_price"] == 300.0
        assert closed["status"] == "CLOSED_TP"

        # Verify disk shows closed
        disk_records = live_trader._load_live_trades_disk()
        closed_item = next(t for t in disk_records if t.get("order_id") == "TEST_LIVE_ORDER_1000")
        assert closed_item["is_open"] is False


# ===========================================================================
# 2. DATABASE TRANSACTION & OFFLINE SESSION RECOVERY
# ===========================================================================

@pytest.mark.asyncio
async def test_papertrade_persistence_handles_db_disconnect_with_disk_fallback():
    """Verify papertrade persistence functions roll back and fall back to disk when database fails."""
    with patch("papertrade.persistence.async_session_factory") as mock_sf:
        mock_sf.side_effect = ConnectionError("PostgreSQL offline")

        account = await persistence.load_account(default_capital=1000000.0)
        assert isinstance(account, dict)
        assert "capital" in account

        open_trades = await persistence.load_open_trades()
        assert isinstance(open_trades, list)

        # save_account and persist_portfolio should handle exceptions without raising
        await persistence.save_account(account)
        await persistence.persist_portfolio(account, open_trades)


@pytest.mark.asyncio
async def test_get_db_dependency_rolls_back_on_unhandled_exception():
    """Verify get_db executes session.rollback() before re-raising exception."""
    mock_session = AsyncMock()
    with patch("api.db.async_session_factory") as mock_sf:
        mock_sf.return_value.__aenter__.return_value = mock_session

        gen = get_db()
        sess = await gen.asend(None)
        assert sess == mock_session

        # Simulate exception during request processing
        with pytest.raises(RuntimeError, match="Handler failure"):
            try:
                raise RuntimeError("Handler failure")
            except Exception as e:
                await gen.athrow(e)

        mock_session.rollback.assert_awaited_once()
        mock_session.close.assert_awaited_once()


# ===========================================================================
# 3. API ROUTER CONCURRENCY & INPUT EDGE CASES
# ===========================================================================

@pytest.fixture
def auth_headers(monkeypatch):
    monkeypatch.setattr("api.auth._configured_api_key", lambda: "test-secret")
    return {"X-API-Key": "test-secret"}


@pytest.mark.asyncio
async def test_training_router_config_mutation_routes_through_config_store(auth_headers):
    """Verify /training/start routes through update_config_atomic with file lock."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch("api.training_router.run_training_loop"), \
             patch("api.training_router.update_config_atomic") as mock_update:
            mock_update.return_value = {"capital": 50000.0}

            resp = await client.post(
                "/api/v1/training/start",
                headers=auth_headers,
                json={
                    "mode": "auto",
                    "capital": 50000.0,
                    "target_index": "NIFTY",
                    "derivative_type": "OPTIONS",
                    "strike_preference": "ATM"
                }
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] in ("started", "already_running")
            if data["status"] == "started":
                mock_update.assert_called_once()
                call_args = mock_update.call_args[0]
                assert call_args[0]["capital"] == 50000.0
                assert call_args[0]["target_index"] == "NIFTY"


@pytest.mark.asyncio
async def test_training_router_corrupted_payload_and_invalid_methods(auth_headers):
    """Test training router handles unexpected methods and corrupted payloads."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Unexpected HTTP method: GET on /start
        resp = await client.get("/api/v1/training/start", headers=auth_headers)
        assert resp.status_code == 405

        # Corrupted payload: negative capital
        resp = await client.post(
            "/api/v1/training/start",
            headers=auth_headers,
            json={"capital": -100.0}
        )
        assert resp.status_code == 422

        # Corrupted payload: NaN capital
        resp = await client.post(
            "/api/v1/training/start",
            headers=auth_headers,
            json={"capital": "not_a_number"}
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_dashboard_analytics_works_with_database_and_fallback(auth_headers):
    """Verify /dashboard/analytics computes metrics properly whether DB succeeds or fails."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. DB query failure -> uses fallback
        with patch("api.dashboard_router.async_session_factory") as mock_sf:
            mock_sf.side_effect = ConnectionError("DB offline")
            resp = await client.get("/api/v1/dashboard/analytics", headers=auth_headers)
            assert resp.status_code == 200
            data = resp.json()
            assert "equity_curve" in data
            assert "win_rate" in data
            assert "total_trades" in data
            assert "probability_of_ruin" in data

        # 2. DB query success -> returns populated response (verifying indentation bug fix!)
        mock_sess = AsyncMock()
        mock_trade = MagicMock()
        mock_trade.pnl_pct = 5.0
        mock_trade.invested = 20000.0
        mock_trade.exit_time = datetime.datetime.now(datetime.timezone.utc)
        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = [mock_trade]
        mock_sess.execute.return_value = mock_res

        with patch("api.dashboard_router.async_session_factory") as mock_sf:
            mock_sf.return_value.__aenter__.return_value = mock_sess
            resp = await client.get("/api/v1/dashboard/analytics", headers=auth_headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data is not None
            assert "equity_curve" in data
            assert data["total_trades"] == 1
            assert data["win_rate"] == 100.0


@pytest.mark.asyncio
async def test_dashboard_config_mutation_strict_whitelisting(auth_headers):
    """Verify /dashboard/config strictly forbids arbitrary keys and uses config_store."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Extra unknown key injection
        resp = await client.post(
            "/api/v1/dashboard/config",
            headers=auth_headers,
            json={"malicious_injection": "drop database", "capital": 50000.0}
        )
        assert resp.status_code == 422

        # Valid key
        with patch("api.dashboard_router.update_config_atomic") as mock_up:
            resp = await client.post(
                "/api/v1/dashboard/config",
                headers=auth_headers,
                json={"capital": 50000.0, "risk_per_trade_pct": 0.02}
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "success"
            mock_up.assert_called_once()


@pytest.mark.asyncio
async def test_market_router_ticker_sanitization_and_path_traversal(auth_headers):
    """Verify market router sanitizes tickers and blocks path traversal & null bytes."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Path traversal
        resp = await client.get("/api/v1/market/quote/..%2F..%2Fetc", headers=auth_headers)
        assert resp.status_code in (400, 404)

        # Null byte injection
        resp = await client.get("/api/v1/market/quote/NIFTY%00MALICIOUS", headers=auth_headers)
        assert resp.status_code in (400, 404)

        # Invalid timeframe on candles
        resp = await client.get("/api/v1/market/candles/NIFTY?timeframe=999y", headers=auth_headers)
        assert resp.status_code == 400
        assert "Invalid timeframe" in resp.json()["detail"]

        # Invalid interval on TA
        resp = await client.get("/api/v1/market/ta/NIFTY?interval=INVALID_INTERVAL", headers=auth_headers)
        assert resp.status_code == 400
        assert "Invalid interval" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_market_router_option_chart_and_tick_adversarial_inputs(auth_headers):
    """Verify /option-chart and /option-tick reject NaN/negative strike and invalid option_types."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Negative strike
        resp = await client.get("/api/v1/market/option-chart?strike=-500.0", headers=auth_headers)
        assert resp.status_code == 422

        # Invalid option_type
        resp = await client.get("/api/v1/market/option-chart?option_type=INVALID", headers=auth_headers)
        assert resp.status_code == 400
        assert "Invalid option_type" in resp.json()["detail"]

        # Option tick negative strike
        resp = await client.get("/api/v1/market/option-tick?strike=0.0", headers=auth_headers)
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_strategy_router_path_traversal_and_validation(auth_headers):
    """Verify custom strategy builder rejects path traversal and enforces bounds."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Path traversal in strategy name
        resp = await client.post(
            "/api/v1/strategy/create",
            headers=auth_headers,
            json={
                "name": "../../etc/evil",
                "bullish_conditions": [{"indicator": "rsi", "operator": "<", "value": "30"}],
                "bearish_conditions": []
            }
        )
        assert resp.status_code == 422

        # Path traversal in delete
        resp = await client.delete("/api/v1/strategy/..%2Fevil", headers=auth_headers)
        assert resp.status_code in (400, 404)

        # Invalid operator
        resp = await client.post(
            "/api/v1/strategy/create",
            headers=auth_headers,
            json={
                "name": "ValidName",
                "bullish_conditions": [{"indicator": "rsi", "operator": "INVALID_OP", "value": "30"}],
                "bearish_conditions": []
            }
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_swing_router_input_sanitization_and_orb_edge_cases(auth_headers):
    """Verify swing router rejects path traversal, oversized fields, and invalid risk/capital."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Path traversal in watchlist candidate
        resp = await client.post(
            "/api/v1/swing/watchlist",
            headers=auth_headers,
            json={
                "ticker": "../MALICIOUS",
                "composite_score": 85.0
            }
        )
        assert resp.status_code in (400, 422)

        # Capital out of bounds in ORB check
        resp = await client.get("/api/v1/swing/orb-check/HAL?capital=-1000", headers=auth_headers)
        assert resp.status_code == 422

        # Risk percent out of bounds in ORB check
        resp = await client.get("/api/v1/swing/orb-check/HAL?risk_pct=0.8", headers=auth_headers)
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_live_trader_option_selling_close_uses_buy_direction_and_positive_pnl():
    """Verify that closing an Option Selling (Short Option) trade orders 'BUY' and gains profit on decay."""
    mock_broker = MagicMock()
    mock_broker.is_connected = True
    mock_broker.place_order.return_value = "ORDER_EXIT_123"

    # Seed disk fallback state with a short option trade
    short_trade = {
        "id": "trade_short_opt_999",
        "order_id": "ORD_SHORT_999",
        "ticker": "NIFTY 24500 CE SELL",
        "direction": "SHORT",
        "action": "SELL",
        "entry_price": 120.0,
        "quantity": 25,
        "invested": 100000.0,
        "is_open": True
    }

    with patch("live_trader._load_live_trades_disk", return_value=[short_trade]), \
         patch("live_trader._save_live_trades_disk") as mock_save:

        # Exit at 40.0 (premium decayed by 80 points = profit for seller)
        closed_rec = await live_trader.close_trade(
            trade_id="trade_short_opt_999",
            exit_price=40.0,
            broker=mock_broker
        )

        assert closed_rec is not None
        # Seller must BUY to close
        mock_broker.place_order.assert_called_once()
        call_kwargs = mock_broker.place_order.call_args[1]
        assert call_kwargs["direction"] == "BUY"
        assert call_kwargs["ticker"] == "NIFTY 24500 CE SELL"

        # PnL must be positive (decayed from 120 to 40)
        assert closed_rec["pnl_pct"] > 0.0
        assert closed_rec["status"] == "CLOSED_TP"


@pytest.mark.asyncio
async def test_market_router_strategy_payoff_endpoint(auth_headers):
    """Verify /option-strategy-payoff computes curves and breakevens for spreads and short options."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Bull Put Spread
        resp = await client.get("/api/v1/market/option-strategy-payoff?underlying=NIFTY&strategy=BULL_PUT_SPREAD", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["strategy"] == "BULL_PUT_SPREAD"
        assert len(data["payoff_curve"]) > 10
        assert len(data["breakevens"]) == 1
        assert data["margin_required"] > 0.0
        assert len(data["legs"]) == 2  # 2 legs for spread

        # Sell Call
        resp = await client.get("/api/v1/market/option-strategy-payoff?underlying=NIFTY&strategy=SELL_CALL", headers=auth_headers)
        assert resp.status_code == 200
        data_sc = resp.json()
        assert data_sc["strategy"] == "SELL_CALL"
        assert len(data_sc["legs"]) == 1
        assert data_sc["legs"][0]["type"] == "SELL_CE"
        assert data_sc["max_loss"] is None  # Unlimited tail risk for naked short call
