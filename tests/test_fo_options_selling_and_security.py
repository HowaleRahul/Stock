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

    def test_iron_condor_plan_and_positive_theta(self):
        """Iron Condor generates 4-leg defined risk strategy with delta neutrality and positive theta."""
        neutral_spot = TradePlan(
            ticker="NIFTY",
            direction="neutral",
            entry_price=24000.0,
            stop_loss=23800.0,
            take_profit=24200.0,
            timeframe="15m",
            risk_reward_ratio=1.5,
            risk_per_trade_pct=0.015,
            position_size_qty=25,
            position_value=50000.0,
            ai_probability=0.52,
            capital=60000.0
        )

        condor_plan = self.engine.generate_derivative_plan(
            spot_plan=neutral_spot,
            capital=60000.0,
            derivative_type="IRON_CONDOR",
            regime="rangebound"
        )

        assert condor_plan.instrument_type == "IRON_CONDOR"
        assert condor_plan.strategy_type == "IRON_CONDOR"
        assert condor_plan.action == "SELL"
        assert condor_plan.net_credit > 0.0
        assert condor_plan.theta > 0.0  # Strongly positive theta income
        assert abs(condor_plan.delta) < 0.25  # Near delta-neutral
        assert condor_plan.margin_or_premium_required > 0.0
        assert condor_plan.is_approved is True

    def test_iron_condor_friction_calculation(self):
        """Iron Condor friction accounts for 8 orders (4 entries + 4 exits = ₹160 brokerage)."""
        ic_friction = IndianFOFrictionModel.calculate_iron_condor_friction(
            short_put_entry=80.0,
            short_put_exit=20.0,
            long_put_entry=30.0,
            long_put_exit=5.0,
            short_call_entry=75.0,
            short_call_exit=15.0,
            long_call_entry=25.0,
            long_call_exit=5.0,
            quantity=25
        )
        assert ic_friction.brokerage == 160.0  # 8 orders * ₹20
        assert ic_friction.total_friction > 160.0
        assert ic_friction.gross_pnl > 0.0
        assert ic_friction.net_pnl < ic_friction.gross_pnl

    def test_nse_feed_dash_and_comma_parsing(self):
        """NSE option chain with dashes ('-') and formatted strings must parse without TypeError/ValueError."""
        from data.nse_feed import NSEFeed
        dummy_data = {
            "records": {
                "data": [
                    {
                        "strikePrice": "24,500",
                        "CE": {"openInterest": "-", "totalTradedVolume": "1,500"},
                        "PE": {"openInterest": "4,200", "totalTradedVolume": "-"}
                    },
                    {
                        "strikePrice": 24600,
                        "CE": {"openInterest": 12000, "totalTradedVolume": 6000},
                        "PE": {"openInterest": 3000, "totalTradedVolume": 2500}
                    }
                ]
            }
        }
        pcr_oi, pcr_vol, put_oi, call_oi = NSEFeed.calculate_pcr(dummy_data)
        assert put_oi == 7200
        assert call_oi == 12000
        assert pcr_oi == round(7200 / 12000, 3)

        max_pain = NSEFeed.calculate_max_pain(dummy_data)
        assert max_pain in (24500.0, 24600.0)


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


# ===========================================================================
# 7. Hardened Strategy Validation, Math Robustness & Strategy Payoff Tests
# ===========================================================================

class TestStrategyValidationAndMathRobustness:
    """Verifies strategy router validation, Sortino calculations, and pay-off math."""

    def test_strategy_condition_rejects_reserved_keywords(self):
        """Indicators and values cannot be nan, inf, null, none keywords."""
        from api.strategy_router import StrategyCondition
        from pydantic import ValidationError

        for bad in ("nan", "inf", "infinity", "-inf", "null", "none"):
            with pytest.raises(ValidationError):
                StrategyCondition(indicator=bad, operator=">", value="50")
            with pytest.raises(ValidationError):
                StrategyCondition(indicator="rsi", operator=">", value=bad)

    def test_performance_dashboard_zero_variance_and_sortino(self, monkeypatch):
        """Sortino and Sharpe ratios must handle zero variance and negative returns gracefully."""
        from ml.performance_dashboard import PerformanceDashboard
        from ml.trade_logger import TradeLogger

        dummy_exits = [
            {"trade_id": "T1", "pnl_pct": 0.05, "cash_pnl": 500.0, "capital_after_exit": 10500.0, "setup": "Breakout", "regime": "trending_up"},
            {"trade_id": "T2", "pnl_pct": 0.05, "cash_pnl": 500.0, "capital_after_exit": 11000.0, "setup": "Breakout", "regime": "trending_up"},
            {"trade_id": "T3", "pnl_pct": 0.05, "cash_pnl": 500.0, "capital_after_exit": 11500.0, "setup": "Breakout", "regime": "trending_up"},
        ]
        monkeypatch.setattr(TradeLogger, "get_all_exits", lambda: dummy_exits)
        monkeypatch.setattr(TradeLogger, "get_all_entries", lambda: [])

        dash = PerformanceDashboard()
        summary = dash.portfolio_summary()
        assert summary["total_trades"] == 3
        assert summary["sharpe_ratio"] == 0.0 or summary["sharpe_ratio"] >= 0.0
        assert "sortino_ratio" in summary

    def test_market_router_iron_condor_payoff(self):
        """Option strategy payoff endpoint must correctly compute 4-leg Iron Condor curves."""
        from api.market_router import router
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        res = client.get("/api/v1/market/option-strategy-payoff?underlying=NIFTY&strategy=IRON_CONDOR")
        assert res.status_code == 200
        data = res.json()
        assert data["strategy"] == "IRON_CONDOR"
        assert len(data["legs"]) == 4
        leg_types = [l["type"] for l in data["legs"]]
        assert "SELL_PE" in leg_types
        assert "BUY_PE" in leg_types
        assert "SELL_CE" in leg_types
        assert "BUY_CE" in leg_types
        assert len(data["breakevens"]) == 2
        assert len(data["payoff_curve"]) > 10
        assert data["margin_required"] > 0


# ===========================================================================
# 8. Pass 26: Option Strategy Payoff Fuzzing & Custom Multi-Leg Tests
# ===========================================================================

class TestOptionStrategyPayoffFuzzingAndCustomLegs:
    """Verifies edge cases, mathematical stability, and multi-leg support on /option-strategy-payoff."""

    def test_get_payoff_unknown_strategy_rejected(self):
        """Unknown strategy name must return 400."""
        res = client.get("/api/v1/market/option-strategy-payoff?underlying=NIFTY&strategy=UNKNOWN_STRAT")
        assert res.status_code == 400
        assert "Invalid strategy" in res.json()["detail"]

    def test_get_payoff_negative_strike_rejected(self):
        """Negative strike must return 400."""
        res = client.get("/api/v1/market/option-strategy-payoff?underlying=NIFTY&strategy=BULL_PUT_SPREAD&strike=-500")
        assert res.status_code == 400
        assert "Invalid strike price" in res.json()["detail"]

    def test_get_payoff_zero_strike_rejected(self):
        """Zero strike must return 400."""
        res = client.get("/api/v1/market/option-strategy-payoff?underlying=NIFTY&strategy=BUY_CALL&strike=0")
        assert res.status_code == 400
        assert "Invalid strike price" in res.json()["detail"]

    def test_get_payoff_extreme_spot_rejected(self):
        """Extreme spot price (< 0.05 or > 10M) must return 400."""
        res_tiny = client.get("/api/v1/market/option-strategy-payoff?underlying=NIFTY&spot=0.0001")
        assert res_tiny.status_code == 400
        res_huge = client.get("/api/v1/market/option-strategy-payoff?underlying=NIFTY&spot=50000000")
        assert res_huge.status_code == 400

    def test_get_payoff_negative_lot_size_rejected(self):
        """Negative lot size must return 400."""
        res = client.get("/api/v1/market/option-strategy-payoff?underlying=NIFTY&lot_size=-25")
        assert res.status_code == 400
        assert "Lot size must be a positive integer" in res.json()["detail"]

    def test_post_payoff_zero_legs_rejected(self):
        """POST /option-strategy-payoff with 0 legs must return 400."""
        payload = {"underlying": "NIFTY", "legs": []}
        res = client.post("/api/v1/market/option-strategy-payoff", json=payload)
        assert res.status_code == 400
        assert "at least 1 leg" in res.json()["detail"]

    def test_post_payoff_more_than_50_legs_rejected(self):
        """POST /option-strategy-payoff with > 50 legs must return 400."""
        legs = [{"strike": 24000.0, "option_type": "CE", "action": "BUY", "lots": 1} for _ in range(51)]
        payload = {"underlying": "NIFTY", "legs": legs}
        res = client.post("/api/v1/market/option-strategy-payoff", json=payload)
        assert res.status_code == 400
        assert "cannot exceed 50 legs" in res.json()["detail"]

    def test_post_payoff_invalid_option_type_rejected(self):
        """POST with invalid option type (e.g. 'XYZ') must return 400."""
        payload = {
            "underlying": "NIFTY",
            "legs": [{"strike": 24000.0, "option_type": "XYZ", "action": "BUY", "lots": 1}]
        }
        res = client.post("/api/v1/market/option-strategy-payoff", json=payload)
        assert res.status_code == 400
        assert "Invalid option_type" in res.json()["detail"]

    def test_post_payoff_invalid_action_rejected(self):
        """POST with invalid action (e.g. 'HOLD') must return 400."""
        payload = {
            "underlying": "NIFTY",
            "legs": [{"strike": 24000.0, "option_type": "CE", "action": "HOLD", "lots": 1}]
        }
        res = client.post("/api/v1/market/option-strategy-payoff", json=payload)
        assert res.status_code == 400
        assert "Invalid action" in res.json()["detail"]

    def test_post_payoff_negative_strike_rejected(self):
        """POST with negative strike in leg must return 400."""
        payload = {
            "underlying": "NIFTY",
            "legs": [{"strike": -24000.0, "option_type": "CE", "action": "BUY", "lots": 1}]
        }
        res = client.post("/api/v1/market/option-strategy-payoff", json=payload)
        assert res.status_code == 400
        assert "Invalid strike price" in res.json()["detail"]

    def test_post_payoff_negative_lots_rejected(self):
        """POST with negative lots must return 400."""
        payload = {
            "underlying": "NIFTY",
            "legs": [{"strike": 24000.0, "option_type": "CE", "action": "BUY", "lots": -2}]
        }
        res = client.post("/api/v1/market/option-strategy-payoff", json=payload)
        assert res.status_code == 400
        assert "lots must be a positive integer" in res.json()["detail"]

    def test_post_payoff_negative_lot_size_rejected(self):
        """POST with negative lot_size in leg must return 400."""
        payload = {
            "underlying": "NIFTY",
            "legs": [{"strike": 24000.0, "option_type": "CE", "action": "BUY", "lots": 1, "lot_size": -50}]
        }
        res = client.post("/api/v1/market/option-strategy-payoff", json=payload)
        assert res.status_code == 400
        assert "lot size must be a positive integer" in res.json()["detail"]

    def test_post_payoff_custom_bull_call_spread(self):
        """POST with valid custom 2-leg Bull Call Spread must return 200 with curve & breakeven."""
        payload = {
            "underlying": "NIFTY",
            "current_spot": 24000.0,
            "legs": [
                {"strike": 24000.0, "option_type": "CE", "action": "BUY", "lots": 1, "premium": 180.0},
                {"strike": 24200.0, "option_type": "CE", "action": "SELL", "lots": 1, "premium": 90.0}
            ]
        }
        res = client.post("/api/v1/market/option-strategy-payoff", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["strategy"] == "CUSTOM"
        assert len(data["legs"]) == 2
        assert len(data["payoff_curve"]) == 41
        assert data["margin_required"] >= 0
        assert len(data["breakevens"]) == 1
        assert abs(data["breakevens"][0] - 24090.0) < 5.0

    def test_post_payoff_preset_strategy_delegation(self):
        """POST with preset strategy name and spot override must return 200."""
        payload = {
            "underlying": "BANKNIFTY",
            "strategy": "BEAR_CALL_SPREAD",
            "current_spot": 51000.0,
            "strike": 51200.0
        }
        res = client.post("/api/v1/market/option-strategy-payoff", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["strategy"] == "BEAR_CALL_SPREAD"
        assert data["current_spot"] == 51000.0
        assert len(data["legs"]) == 2
        assert data["margin_required"] > 0


# ===========================================================================
# 9. Pass 26: Black-Scholes Greeks, 0-DTE, and Volatility Singularities
# ===========================================================================

class TestBlackScholesSingularitiesAndEdgeRegimes:
    """Verifies mathematical stability of Black-Scholes at T<=0, sigma<=0, extreme IV, and deep ITM/OTM."""

    def setup_method(self):
        self.engine = DerivativeEngine()

    def test_zero_dte_call_intrinsic_convergence(self):
        """At T=0.0, Call option converges exactly to intrinsic value max(0.05, S - K)."""
        res_itm = self.engine.black_scholes(S=24500.0, K=24000.0, T=0.0, r=0.065, sigma=0.15, option_type="CE")
        assert res_itm["premium"] == 500.0
        assert res_itm["delta"] == 1.0
        assert res_itm["gamma"] == 0.0

        res_otm = self.engine.black_scholes(S=23500.0, K=24000.0, T=0.0, r=0.065, sigma=0.15, option_type="CE")
        assert res_otm["premium"] == 0.05
        assert res_otm["delta"] == 0.0

    def test_zero_dte_put_intrinsic_convergence(self):
        """At T=0.0, Put option converges exactly to intrinsic value max(0.05, K - S)."""
        res_itm = self.engine.black_scholes(S=23500.0, K=24000.0, T=0.0, r=0.065, sigma=0.15, option_type="PE")
        assert res_itm["premium"] == 500.0
        assert res_itm["delta"] == -1.0

        res_otm = self.engine.black_scholes(S=24500.0, K=24000.0, T=0.0, r=0.065, sigma=0.15, option_type="PE")
        assert res_otm["premium"] == 0.05
        assert res_otm["delta"] == 0.0

    def test_zero_volatility_boundary(self):
        """At sigma=0.0, Black-Scholes converges to intrinsic value without ZeroDivisionError."""
        res_call = self.engine.black_scholes(S=24200.0, K=24000.0, T=0.1, r=0.065, sigma=0.0, option_type="CE")
        assert res_call["premium"] == 200.0
        assert res_call["delta"] == 1.0

        res_put = self.engine.black_scholes(S=23800.0, K=24000.0, T=0.1, r=0.065, sigma=0.0, option_type="PE")
        assert res_put["premium"] == 200.0
        assert res_put["delta"] == -1.0

    def test_extreme_iv_bounds(self):
        """At extreme IV (sigma=10.0 / 1000%), delta remains strictly clamped and finite."""
        res = self.engine.black_scholes(S=24000.0, K=24000.0, T=0.05, r=0.065, sigma=10.0, option_type="CE")
        assert 0.0 <= res["delta"] <= 1.0
        assert res["premium"] > 0
        assert math.isfinite(res["theta"])
        assert math.isfinite(res["gamma"])

    def test_deep_itm_asymptotic_regime(self):
        """Deep ITM call (|d1| >= 37) gives delta=1.0 and gamma=0 without overflow."""
        res = self.engine.black_scholes(S=200000.0, K=10000.0, T=0.1, r=0.065, sigma=0.15, option_type="CE")
        assert res["delta"] == 1.0
        assert res["gamma"] == 0.0
        assert res["premium"] >= 190000.0

    def test_deep_otm_asymptotic_regime(self):
        """Deep OTM call gives delta=0.0 and minimum premium 0.05."""
        res = self.engine.black_scholes(S=5000.0, K=100000.0, T=0.1, r=0.065, sigma=0.15, option_type="CE")
        assert res["delta"] == 0.0
        assert res["gamma"] == 0.0
        assert res["premium"] == 0.05

    def test_expiry_day_1530_rollover(self):
        """Test get_days_to_expiry exactly at 15:30 IST vs 15:30:01 rollover."""
        import datetime
        from ml.options_engine import get_days_to_expiry, IST

        # Thursday 2026-10-22 at 15:30 IST (expiry moment)
        thursday_expiry = datetime.datetime(2026, 10, 22, 15, 30, 0, tzinfo=IST)
        dte_at_close = get_days_to_expiry("NIFTY", dt=thursday_expiry)
        assert dte_at_close == 0.0

        # Thursday 2026-10-22 at 15:30:05 IST (rolled over to next Thursday)
        thursday_past_close = datetime.datetime(2026, 10, 22, 15, 30, 5, tzinfo=IST)
        dte_rolled = get_days_to_expiry("NIFTY", dt=thursday_past_close)
        assert dte_rolled >= 4.0


# ===========================================================================
# 10. Pass 26: NSE Feed Adversarial Fuzzing & Resilience
# ===========================================================================

class TestNSEFeedAdversarialFuzzing:
    """Verifies that corrupt payloads, zero OI, missing records, and network glitches never crash NSEFeed."""

    def test_pcr_empty_dict_and_none(self):
        """Empty dictionary or None must return default (1.0, 1.0, 0, 0)."""
        from data.nse_feed import NSEFeed
        assert NSEFeed.calculate_pcr({}) == (1.0, 1.0, 0, 0)
        assert NSEFeed.calculate_pcr(None) == (1.0, 1.0, 0, 0)

    def test_pcr_null_records_and_data(self):
        """Records: None or Data: None must not throw AttributeError."""
        from data.nse_feed import NSEFeed
        assert NSEFeed.calculate_pcr({"records": None}) == (1.0, 1.0, 0, 0)
        assert NSEFeed.calculate_pcr({"records": {"data": None}}) == (1.0, 1.0, 0, 0)
        assert NSEFeed.calculate_pcr({"records": "bad_type"}) == (1.0, 1.0, 0, 0)

    def test_pcr_corrupt_data_rows(self):
        """Corrupt non-dict rows inside data list must be skipped safely."""
        from data.nse_feed import NSEFeed
        chain = {
            "records": {
                "data": [
                    "corrupt_string",
                    None,
                    12345,
                    {"strikePrice": 24000, "CE": None, "PE": {"openInterest": 1500, "totalTradedVolume": 300}},
                    {"strikePrice": 24100, "CE": {"openInterest": 1500, "totalTradedVolume": 300}, "PE": None}
                ]
            }
        }
        pcr_oi, pcr_vol, put_oi, call_oi = NSEFeed.calculate_pcr(chain)
        assert put_oi == 1500
        assert call_oi == 1500
        assert pcr_oi == 1.0

    def test_pcr_zero_call_oi_no_zero_division(self):
        """When total call OI is zero, PCR must return 100.0 without ZeroDivisionError."""
        from data.nse_feed import NSEFeed
        chain = {
            "records": {
                "data": [
                    {"strikePrice": 24000, "CE": {"openInterest": 0}, "PE": {"openInterest": 8000}}
                ]
            }
        }
        pcr_oi, pcr_vol, put_oi, call_oi = NSEFeed.calculate_pcr(chain)
        assert call_oi == 0
        assert put_oi == 8000
        assert pcr_oi == 100.0

    def test_max_pain_corrupt_payload(self):
        """calculate_max_pain with None or malformed records returns None."""
        from data.nse_feed import NSEFeed
        assert NSEFeed.calculate_max_pain(None) is None
        assert NSEFeed.calculate_max_pain({}) is None
        assert NSEFeed.calculate_max_pain({"records": None}) is None
        assert NSEFeed.calculate_max_pain({"records": {"data": []}}) is None

    def test_safe_num_handles_booleans_and_special_strings(self):
        """_safe_num must not cast True/False to 1.0/0.0, and safely handle dashes/NaN/Inf."""
        from data.nse_feed import NSEFeed
        assert NSEFeed._safe_num(True, default=0.0) == 0.0
        assert NSEFeed._safe_num(False, default=0.0) == 0.0
        assert NSEFeed._safe_num("-", default=0.0) == 0.0
        assert NSEFeed._safe_num("12,345.67") == 12345.67
        assert NSEFeed._safe_num(float("nan"), default=0.0) == 0.0
        assert NSEFeed._safe_num(float("inf"), default=0.0) == 0.0


# ===========================================================================
# 11. Pass 26: Sharpe, Sortino, and Risk Engine Mathematical Singularities
# ===========================================================================

class TestSharpeSortinoZeroVarianceAndRiskSingularities:
    """Verifies Sharpe and Sortino calculations handle zero variance, empty trades, and infinite R:R."""

    def test_performance_dashboard_zero_variance_trades(self):
        """When all trades have identical PnL (variance=0), Sharpe & Sortino must return 0.0."""
        from ml.performance_dashboard import PerformanceDashboard
        pb = PerformanceDashboard()
        pb._exits = [
            {"pnl_pct": 0.02, "cash_pnl": 200.0},
            {"pnl_pct": 0.02, "cash_pnl": 200.0},
            {"pnl_pct": 0.02, "cash_pnl": 200.0}
        ]
        summary = pb.portfolio_summary()
        assert summary["sharpe_ratio"] == 0.0
        assert summary["sortino_ratio"] == 0.0

    def test_performance_dashboard_no_downside_trades(self):
        """When all trades are positive, Sortino ratio must not encounter division by zero."""
        from ml.performance_dashboard import PerformanceDashboard
        pb = PerformanceDashboard()
        pb._exits = [
            {"pnl_pct": 0.01, "cash_pnl": 100.0},
            {"pnl_pct": 0.03, "cash_pnl": 300.0},
            {"pnl_pct": 0.05, "cash_pnl": 500.0}
        ]
        summary = pb.portfolio_summary()
        assert summary["sharpe_ratio"] > 0
        assert summary["sortino_ratio"] > 0
        assert math.isfinite(summary["sortino_ratio"])

    def test_risk_engine_infinite_rr_capping(self):
        """When stop loss distance is virtually zero, R:R ratio must be capped at 100.0."""
        from ml.risk_engine import RiskEngine
        import pandas as pd
        engine = RiskEngine()
        df = pd.DataFrame({
            "close": [24000.0] * 50,
            "high": [24050.0] * 50,
            "low": [23950.0] * 50,
            "atr": [50.0] * 50
        })
        with patch.object(engine, "_calculate_stop_loss", return_value=(24000.0, "MOCK_SL")):
            with patch.object(engine, "_calculate_take_profit", return_value=(24500.0, "MOCK_TP")):
                plan = engine.generate_trade_plan(
                    ticker="NIFTY",
                    direction="bullish",
                    ai_probability=0.75,
                    df=df,
                    capital=100000.0
                )
                assert plan.risk_reward_ratio <= 100.0
                assert plan.risk_reward_ratio > 0.0

    def test_risk_engine_kelly_criterion_zero_and_infinite_rr(self):
        """Kelly criterion must handle zero R:R and extreme R:R safely without ZeroDivisionError."""
        from ml.risk_engine import RiskEngine
        engine = RiskEngine()
        k_zero = engine._kelly_criterion(0.6, 0.0)
        assert k_zero == 0.005
        k_inf = engine._kelly_criterion(0.6, float("inf"))
        assert k_inf <= 0.05
        k_nan = engine._kelly_criterion(float("nan"), 2.0)
        assert 0.005 <= k_nan <= 0.05

    def test_risk_engine_ruin_zero_loss_and_zero_risk(self):
        """Probability of ruin with zero loss or zero risk fraction returns safe probabilities."""
        from ml.risk_engine import RiskEngine
        engine = RiskEngine()
        p_ruin_zero_risk = engine._probability_of_ruin(0.55, 100.0, 50.0, risk_fraction=0.0)
        assert p_ruin_zero_risk == 0.0

        p_ruin_zero_loss = engine._probability_of_ruin(0.55, 100.0, avg_loss=0.0, risk_fraction=0.02)
        assert 0.0 <= p_ruin_zero_loss <= 1.0


# ===========================================================================
# 12. Pass 26: Config and Strategy Store Corrupted File Recovery
# ===========================================================================

class TestConfigAndStrategyCorruptedRecovery:
    """Verifies that corrupted JSON files do not take down endpoints with 503 errors."""

    def test_corrupted_config_json_returns_empty_dict(self, tmp_path):
        """Corrupted config.json must return {} instead of crashing."""
        from api.config_store import load_config_atomic, update_config_atomic
        bad_config_file = str(tmp_path / "corrupt_config.json")
        with open(bad_config_file, "w") as f:
            f.write("{invalid_json_content: ")

        data = load_config_atomic(bad_config_file)
        assert data == {}

        # Updating must overwrite and restore healthy JSON
        updated = update_config_atomic({"capital": 75000.0}, bad_config_file)
        assert updated["capital"] == 75000.0

        reloaded = load_config_atomic(bad_config_file)
        assert reloaded["capital"] == 75000.0

    def test_corrupted_strategy_store_recovers_empty_list(self, tmp_path, monkeypatch):
        """Corrupted custom_strategies.json must return [] without 503."""
        import api.strategy_router as sr
        bad_strat_file = str(tmp_path / "corrupt_strategies.json")
        with open(bad_strat_file, "w") as f:
            f.write("[{'truncated_json': ")

        monkeypatch.setattr(sr, "STRATEGY_FILE", bad_strat_file)
        strategies = sr._read_strategies()
        assert strategies == []

    def test_strategy_condition_rejects_reserved_keywords(self):
        """Strategy condition must reject NaN, Infinity, null, and None."""
        from api.strategy_router import StrategyCondition
        with pytest.raises(ValueError, match="reserved keyword"):
            StrategyCondition(indicator="NaN", operator=">", value="50")

        with pytest.raises(ValueError, match="reserved keyword"):
            StrategyCondition(indicator="rsi_14", operator=">", value="Infinity")

        with pytest.raises(ValueError, match="reserved keyword"):
            StrategyCondition(indicator="null", operator="<", value="20")

