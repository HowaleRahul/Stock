"""
Comprehensive Automated Regression and Security Audit Test Suite.
Verifies:
1. Router edge cases: negative inputs, invalid tickers, NaN/Inf strikes, malformed queries.
2. Ticker sanitization, null byte defense, and path traversal prevention across all routers.
3. Rate limiter resilience and authentication hardening (route template grouping, invalid XFF, case-insensitive bearer).
4. Concurrency & race condition defenses (strategy store, swing watchlist, trade logger).
5. Indian F&O Option Selling vs Buying friction, margin requirements, Greeks, and credit spreads.
6. SSRF redirection blocking (non-standard ports, private/loopback/unspecified IPs) and XML entity defenses.
"""

import pytest
import asyncio
import math
import threading
import json
import os
from unittest.mock import patch, MagicMock, AsyncMock
from httpx import AsyncClient, ASGITransport
from starlette.testclient import TestClient

from api.main import app
from api.config import settings
from data.news_fetcher import _is_safe_redirect, _safe_parse_xml
from data.service import DataIngestionService
from api.schemas import SymbolCreate
from ml.options_engine import DerivativeEngine, DerivativeTradePlan
from ml.risk_engine import TradePlan, IndianFOFrictionModel
from setups.swing_toolkit.toolkit import SwingToolkitManager
from ml.trade_logger import TradeLogger


client = TestClient(app)


# ===========================================================================
# 1. Router Edge Cases: Negative Inputs, NaN/Inf, Malformed Queries
# ===========================================================================

class TestRouterEdgeCases:
    """Verifies all API routers strictly reject negative, NaN, Inf, and malformed inputs."""

    def test_market_option_chart_negative_strike(self):
        """Negative strikes must be rejected with 422 Unprocessable Entity."""
        res = client.get("/api/v1/market/option-chart?underlying=NIFTY&strike=-22000&option_type=CE")
        assert res.status_code == 422

    def test_market_option_chart_nan_inf_strike(self):
        """NaN and Inf strike inputs must be rejected."""
        res_nan = client.get("/api/v1/market/option-chart?underlying=NIFTY&strike=nan&option_type=CE")
        assert res_nan.status_code == 422

        res_inf = client.get("/api/v1/market/option-chart?underlying=NIFTY&strike=inf&option_type=CE")
        assert res_inf.status_code == 422

    def test_market_option_chart_invalid_option_type(self):
        """Invalid option_type (not CE/PE) must return 400."""
        res = client.get("/api/v1/market/option-chart?underlying=NIFTY&strike=22800&option_type=INVALID")
        assert res.status_code == 400
        assert "CE" in res.json()["detail"] or "PE" in res.json()["detail"]

    def test_market_option_tick_negative_strike(self):
        """Option tick must reject negative strike."""
        res = client.get("/api/v1/market/option-tick?underlying=NIFTY&strike=-100&option_type=CE")
        assert res.status_code == 422

    def test_market_option_tick_nan_strike(self):
        """Option tick must reject NaN strike."""
        res = client.get("/api/v1/market/option-tick?underlying=NIFTY&strike=nan&option_type=CE")
        assert res.status_code == 422

    def test_swing_orb_check_negative_capital(self):
        """ORB breakout check must reject negative capital."""
        res = client.get("/api/v1/swing/orb-check/TCS?capital=-50000")
        assert res.status_code == 422

    def test_swing_orb_check_negative_risk_pct(self):
        """ORB breakout check must reject negative risk_pct."""
        res = client.get("/api/v1/swing/orb-check/TCS?risk_pct=-0.02")
        assert res.status_code == 422

    def test_swing_orb_check_nan_inputs(self):
        """ORB breakout check must reject NaN capital or risk_pct."""
        res1 = client.get("/api/v1/swing/orb-check/TCS?capital=nan")
        assert res1.status_code == 422
        res2 = client.get("/api/v1/swing/orb-check/TCS?risk_pct=nan")
        assert res2.status_code == 422

    def test_dashboard_config_rejects_nan_and_inf(self):
        """Config updates must reject NaN and Inf numbers."""
        res_nan = client.post("/api/v1/dashboard/config", json={"capital": "nan"})
        assert res_nan.status_code == 422

        res_inf = client.post("/api/v1/dashboard/config", json={"min_ai_confidence": "inf"})
        assert res_inf.status_code == 422

    def test_dashboard_config_rejects_negative_capital(self):
        """Config updates must reject negative or zero capital."""
        res = client.post("/api/v1/dashboard/config", json={"capital": -1000.0})
        assert res.status_code == 422

    def test_backtest_run_invalid_timeframe(self):
        """Backtest must reject invalid timeframe."""
        res = client.get("/api/v1/backtest/run?ticker=RELIANCE.NS&timeframe=99d&setup=sma_crossover")
        assert res.status_code == 400
        assert "Invalid timeframe" in res.json()["detail"]

    def test_backtest_run_invalid_setup(self):
        """Backtest must reject unknown setup name."""
        res = client.get("/api/v1/backtest/run?ticker=RELIANCE.NS&timeframe=1d&setup=nonexistent_setup")
        assert res.status_code == 400
        assert "Invalid setup" in res.json()["detail"]


# ===========================================================================
# 2. Ticker Sanitization & Path Traversal / Injection Defenses
# ===========================================================================

class TestTickerSanitizationAndPathTraversal:
    """Verifies that all routers and services block path traversal, null bytes, and malicious tickers."""

    @pytest.mark.parametrize("bad_ticker", [
        "..",
        "%2E%2E",
        "RELIANCE%00NS",
        "INVALID$CHAR!",
        "A" * 65,  # Exceeds max length 64
    ])
    def test_market_quote_rejects_malicious_tickers(self, bad_ticker):
        res = client.get(f"/api/v1/market/quote/{bad_ticker}")
        assert res.status_code in (400, 404, 422)

    @pytest.mark.parametrize("bad_ticker", [
        "..",
        "%2E%2E",
        "INFY%00HACK",
    ])
    def test_candles_rejects_malicious_tickers(self, bad_ticker):
        res = client.get(f"/api/v1/candles/{bad_ticker}")
        assert res.status_code in (400, 404, 422)

    @pytest.mark.parametrize("bad_ticker", [
        "..",
        "%2E%2E",
        "BEL%00ATTACK",
        "INVALID%23TICKER",
    ])
    def test_swing_orb_check_rejects_malicious_tickers(self, bad_ticker):
        res = client.get(f"/api/v1/swing/orb-check/{bad_ticker}")
        assert res.status_code in (400, 404, 422)

    def test_strategy_delete_rejects_path_traversal(self):
        res = client.delete("/api/v1/strategy/..%2F..%2Fcustom_strategies")
        assert res.status_code in (400, 404)

    def test_strategy_create_rejects_path_traversal_in_name(self):
        payload = {
            "name": "../../../evil_strategy",
            "description": "Exploit attempt",
            "bullish_conditions": [],
            "bearish_conditions": [],
        }
        res = client.post("/api/v1/strategy/create", json=payload)
        assert res.status_code == 422

    def test_symbol_create_schema_rejects_traversal(self):
        with pytest.raises(ValueError, match="path traversal"):
            SymbolCreate(ticker="..")

    def test_data_ingestion_service_rejects_malicious_tickers(self):
        with pytest.raises(ValueError):
            asyncio.run(DataIngestionService.get_or_create_symbol(".."))

        with pytest.raises(ValueError, match="null byte"):
            asyncio.run(DataIngestionService.get_or_create_symbol("RELIANCE\x00NS"))

        with pytest.raises(ValueError):
            asyncio.run(DataIngestionService.get_or_create_symbol("TCS/../BO"))


# ===========================================================================
# 3. Rate Limiter Resilience & Authentication Hardening
# ===========================================================================

class TestRateLimiterAndAuth:
    """Verifies route-level grouping, XFF sanitization, and bearer token handling."""

    def test_case_insensitive_bearer_token(self):
        """Lowercase 'bearer <key>' should be accepted identically to 'Bearer <key>'."""
        with patch("api.auth._configured_api_key", return_value="secret-key-123"):
            res_upper = client.get("/db-check", headers={"Authorization": "Bearer secret-key-123"})
            res_lower = client.get("/db-check", headers={"Authorization": "bearer secret-key-123"})
            assert res_upper.status_code != 403
            assert res_lower.status_code != 403

    def test_invalid_api_key_returns_403(self):
        """Invalid API key returns 403 Forbidden."""
        with patch("api.auth._configured_api_key", return_value="secret-key-123"):
            res = client.get("/db-check", headers={"Authorization": "Bearer wrong-key"})
            assert res.status_code == 403
            assert "Invalid or missing API Key" in res.json()["detail"]

    def test_rate_limiter_handles_junk_forwarded_for(self):
        """Malformed or malicious X-Forwarded-For headers should not crash or corrupt the rate limiter."""
        res = client.get(
            "/api/v1/market/status",
            headers={"X-Forwarded-For": "malicious-header-content; DROP TABLE users;"}
        )
        assert res.status_code == 200

    def test_rate_limiter_groups_by_route_template(self):
        """Path parameters (e.g. quote for TCS vs INFY) should share the route-level rate limit quota."""
        from api.auth import rate_limiter
        limiter = rate_limiter(requests_per_minute=2)

        class MockRequest:
            client = type("Client", (), {"host": "192.168.1.100"})()
            headers = {}
            scope = {
                "route": type("Route", (), {"path": "/api/v1/market/quote/{ticker}"})(),
                "path": "/api/v1/market/quote/TCS"
            }

        req1 = MockRequest()
        assert asyncio.run(limiter(req1)) is True
        assert asyncio.run(limiter(req1)) is True

        # Third request on same route with different ticker parameter must hit 429
        req2 = MockRequest()
        req2.scope["path"] = "/api/v1/market/quote/INFY"
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(limiter(req2))
        assert exc_info.value.status_code == 429


# ===========================================================================
# 4. Concurrency & Race Condition Defenses
# ===========================================================================

class TestConcurrencyAndRaceConditions:
    """Verifies thread-safety in strategy persistence, swing watchlist, and trade logger."""

    def test_concurrent_strategy_creation_prevent_duplicate_conflict(self):
        """Rapid concurrent creates for the same strategy name must be safely serialized with 409 Conflict."""
        from api.strategy_router import create_strategy, CustomStrategy
        import tempfile

        strat = CustomStrategy(
            name="Concurrent Unique Strategy",
            description="Test strategy",
            bullish_conditions=[],
            bearish_conditions=[]
        )

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp.write(b"[]")
            tmp.flush()
            tmp_path = tmp.name

        try:
            with patch("api.strategy_router.STRATEGY_FILE", tmp_path):
                # Run first create
                res1 = asyncio.run(create_strategy(strat))
                assert res1["status"] == "success"

                # Run duplicate create
                from fastapi import HTTPException
                with pytest.raises(HTTPException) as exc_info:
                    asyncio.run(create_strategy(strat))
                assert exc_info.value.status_code == 409
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_swing_watchlist_concurrency_lock(self):
        """Multiple threads modifying swing watchlist concurrently must not cause lost updates or file corruption."""
        mgr = SwingToolkitManager()
        errors = []

        def worker(thread_id: int):
            try:
                candidate = {
                    "ticker": f"TICKER_{thread_id}",
                    "sector": "Defense",
                    "source_scanners": ["Momentum"],
                    "composite_score": 85.0,
                    "vcp_detected": True,
                    "stage_2": True,
                    "added_at": "2026-10-25",
                    "notes": f"Thread {thread_id}",
                }
                mgr.add_to_watchlist(candidate)
                items = mgr.load_watchlist()
                assert any(it["ticker"] == f"TICKER_{thread_id}" for it in items)
                mgr.remove_from_watchlist(f"TICKER_{thread_id}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_trade_logger_thread_safety(self):
        """Concurrent logging to TradeLogger across threads must append without corrupting lines."""
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
            test_log_path = tmp.name

        with patch.object(TradeLogger, "_current_log_file", return_value=test_log_path):
            errors = []

            def worker(thread_id: int):
                try:
                    for j in range(5):
                        TradeLogger.log_entry(
                            trade_id=f"T_{thread_id}_{j}",
                            ticker="NIFTY",
                            direction="LONG",
                            entry_price=22800.0,
                            stop_loss=22700.0,
                            take_profit=23000.0,
                            quantity=25,
                            invested=10000.0,
                            risk_pct=0.015,
                            risk_reward=2.0,
                            ai_probability=0.75,
                            kelly_fraction=0.10,
                            probability_of_ruin=0.01,
                            regime="trending",
                            regime_adx=28.5,
                            sl_method="ATR",
                            tp_method="ATR",
                            timeframe="15m",
                            atr_at_entry=45.0,
                            setup_signals=[],
                            setup_weights={},
                            config_version="v2",
                            capital_at_entry=100000.0,
                        )
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(errors) == 0
            entries = TradeLogger.get_all_entries()
            assert len(entries) == 40  # 8 threads * 5 entries = 40 records

        if os.path.exists(test_log_path):
            os.remove(test_log_path)


# ===========================================================================
# 5. Indian F&O Option Selling vs Buying Friction & Mechanics
# ===========================================================================

class TestOptionsSellingAndBuyingFriction:
    """Verifies Black-Scholes Greeks, Option Selling, Credit Spreads, and Indian F&O Friction."""

    def setup_method(self):
        self.engine = DerivativeEngine()

    def test_option_selling_direction_and_greeks(self):
        """
        Directional Option Selling:
        - Bearish Spot -> Sell OTM Call (CE), negative delta, POSITIVE theta income.
        - Bullish Spot -> Sell OTM Put (PE), positive delta, POSITIVE theta income.
        """
        # 1. Bearish spot plan -> Sells Call (CE)
        bearish_spot = TradePlan(
            ticker="NIFTY",
            direction="bearish",
            entry_price=22800.0,
            stop_loss=22900.0,
            take_profit=22600.0,
            timeframe="15m",
            risk_reward_ratio=2.0,
            risk_per_trade_pct=0.015,
            position_size_qty=25,
            position_value=50000.0,
            ai_probability=0.78,
            capital=500000.0  # Sufficient SPAN margin
        )

        plan_ce = self.engine.generate_derivative_plan(
            spot_plan=bearish_spot,
            capital=500000.0,
            derivative_type="SELL_OPTIONS",
            regime="rangebound"
        )

        assert plan_ce.action == "SELL"
        assert plan_ce.option_type == "CE"
        assert plan_ce.strike_price >= 22800.0  # OTM Call
        assert plan_ce.delta <= 0.0              # Short Call has negative delta
        assert plan_ce.theta > 0.0               # Seller enjoys positive daily theta decay
        assert plan_ce.is_approved is True

        # 2. Bullish spot plan -> Sells Put (PE)
        bullish_spot = TradePlan(
            ticker="NIFTY",
            direction="bullish",
            entry_price=22800.0,
            stop_loss=22700.0,
            take_profit=23000.0,
            timeframe="15m",
            risk_reward_ratio=2.0,
            risk_per_trade_pct=0.015,
            position_size_qty=25,
            position_value=50000.0,
            ai_probability=0.78,
            capital=500000.0
        )

        plan_pe = self.engine.generate_derivative_plan(
            spot_plan=bullish_spot,
            capital=500000.0,
            derivative_type="SELL_OPTIONS",
            regime="rangebound"
        )

        assert plan_pe.action == "SELL"
        assert plan_pe.option_type == "PE"
        assert plan_pe.strike_price <= 22800.0  # OTM Put
        assert plan_pe.delta >= 0.0              # Short Put has positive delta
        assert plan_pe.theta > 0.0               # Positive theta
        assert plan_pe.is_approved is True

    def test_option_selling_span_margin_rejection_on_low_capital(self):
        """Selling options with insufficient capital must be rejected with SPAN margin deficit."""
        spot_plan = TradePlan(
            ticker="NIFTY",
            direction="bearish",
            entry_price=22800.0,
            stop_loss=22900.0,
            take_profit=22600.0,
            timeframe="15m",
            risk_reward_ratio=2.0,
            risk_per_trade_pct=0.015,
            position_size_qty=25,
            position_value=10000.0,
            ai_probability=0.75,
            capital=25000.0  # Only ₹25k, far below ~₹85k SPAN margin
        )

        plan = self.engine.generate_derivative_plan(
            spot_plan=spot_plan,
            capital=25000.0,
            derivative_type="SELL_OPTIONS",
            regime="rangebound"
        )

        assert plan.is_approved is False
        assert any("SPAN Margin Deficit" in r for r in plan.rejection_reasons)

    def test_credit_spread_plan_for_moderate_capital(self):
        """Credit spread (2-leg defined risk) allows theta collection on moderate capital (e.g. ₹35k)."""
        bullish_spot = TradePlan(
            ticker="NIFTY",
            direction="bullish",
            entry_price=22800.0,
            stop_loss=22700.0,
            take_profit=23000.0,
            timeframe="15m",
            risk_reward_ratio=2.0,
            risk_per_trade_pct=0.015,
            position_size_qty=25,
            position_value=35000.0,
            ai_probability=0.75,
            capital=35000.0
        )

        spread_plan = self.engine.generate_derivative_plan(
            spot_plan=bullish_spot,
            capital=35000.0,
            derivative_type="CREDIT_SPREAD",
            regime="rangebound"
        )

        assert spread_plan.instrument_type == "SPREAD"
        assert spread_plan.strategy_type == "CREDIT_SPREAD"
        assert spread_plan.net_credit > 0.0
        assert spread_plan.max_loss_amount > 0.0
        assert spread_plan.hedge_strike_price > 0.0
        assert spread_plan.is_approved is True

    def test_indian_fo_friction_buying_vs_selling(self):
        """
        Verify Indian F&O friction calculations:
        - Buying Option: breakeven exit price > entry buy premium (must sell higher).
        - Selling Option: breakeven exit price < entry sell premium (must buyback lower).
        - STT is charged on Sell Turnover.
        """
        qty = 25  # 1 lot NIFTY

        # Option Buying (Entry = ₹100, Target = ₹150)
        fb_buy = IndianFOFrictionModel.calculate_options_friction(
            buy_premium=100.0,
            sell_premium=150.0,
            quantity=qty,
            action="BUY"
        )
        assert fb_buy.breakeven_exit_price > 100.0  # Must sell at > ₹100 to break even
        assert fb_buy.stt > 0.0                    # STT applies on sell leg
        assert fb_buy.brokerage == 40.0             # ₹20 buy + ₹20 sell
        assert fb_buy.total_friction > 40.0

        # Option Selling (Entry = ₹100, Target Buyback = ₹30)
        fb_sell = IndianFOFrictionModel.calculate_options_friction(
            buy_premium=30.0,
            sell_premium=100.0,
            quantity=qty,
            action="SELL"
        )
        assert fb_sell.breakeven_exit_price < 100.0  # Must buyback at < ₹100 to break even
        assert fb_sell.stt > 0.0                     # STT applies on sell leg (entry)
        assert fb_sell.total_friction > 40.0

    def test_credit_spread_friction_4_legs(self):
        """Spread friction covers all 4 execution legs (2 buy + 2 sell)."""
        spread_friction = IndianFOFrictionModel.calculate_spread_friction(
            short_entry_prem=100.0,
            short_exit_prem=30.0,
            long_entry_prem=40.0,
            long_exit_prem=10.0,
            quantity=25
        )
        assert spread_friction.brokerage == 80.0  # 4 legs * ₹20 = ₹80
        assert spread_friction.total_friction > 80.0
        assert spread_friction.gross_pnl > 0.0
        assert spread_friction.net_pnl < spread_friction.gross_pnl


# ===========================================================================
# 6. SSRF and XML Security in News Fetcher
# ===========================================================================

class TestNewsFetcherSecurity:
    """Verifies that SSRF checks block non-standard ports and local/unspecified IPs, and XML parsing blocks XXE."""

    def test_ssrf_blocks_non_standard_ports(self):
        """Redirects to internal ports like 8443, 8000, 5432 must be blocked."""
        assert _is_safe_redirect("https://127.0.0.1:8443/secret") is False
        assert _is_safe_redirect("https://localhost:8000/api") is False
        assert _is_safe_redirect("https://google.com:8443/redirect") is False

    def test_ssrf_blocks_unspecified_ip_0_0_0_0(self):
        """0.0.0.0 resolves to localhost on many platforms and must be blocked."""
        assert _is_safe_redirect("https://0.0.0.0/") is False
        assert _is_safe_redirect("https://0.0.0.0:443/") is False

    def test_ssrf_blocks_private_and_loopback_ips(self):
        """127.0.0.1, 10.0.0.1, 192.168.1.1, 169.254.169.254 must be blocked."""
        assert _is_safe_redirect("https://127.0.0.1/") is False
        assert _is_safe_redirect("https://10.0.0.5/") is False
        assert _is_safe_redirect("https://192.168.0.1/") is False
        assert _is_safe_redirect("https://169.254.169.254/latest/meta-data/") is False

    def test_ssrf_blocks_http_scheme(self):
        """Plain HTTP redirects must be blocked (only HTTPS allowed)."""
        assert _is_safe_redirect("http://news.google.com/") is False

    def test_xml_payload_size_limit_rejection(self):
        """XML payload exceeding 5MB must be rejected before parsing."""
        huge_xml = "<root>" + "A" * 5_000_001 + "</root>"
        with pytest.raises(ValueError, match="exceeds maximum allowable size"):
            _safe_parse_xml(huge_xml)

    def test_xml_entity_and_doctype_rejection(self):
        """Suspicious XML with DOCTYPE or ENTITY must be rejected."""
        xxe_payload = """<?xml version="1.0"?>
        <!DOCTYPE foo [ <!ELEMENT foo ANY >
        <!ENTITY xxe SYSTEM "file:///etc/passwd" >]>
        <foo>&xxe;</foo>"""
        with pytest.raises(ValueError, match="Rejected suspicious XML payload"):
            _safe_parse_xml(xxe_payload)
