import asyncio
import datetime
import math
import os
import pytest
from unittest.mock import patch, MagicMock

from api.auth import _is_trusted_proxy, rate_limiter
from api.broker import SmartAPIBroker
from data.fx_fetcher import FrankfurterFXFetcher
from api.swing_router import AddWatchlistRequest
from papertrade.persistence import _timestamp
from api.config_store import load_config_atomic


class TestAdversarialSecurityAudit:
    """
    Adversarial test suite verifying patches for:
    - LAN/Private IP proxy rate-limiting bypass
    - SmartAPIBroker fail-closed enforcement & input validation
    - Frankfurter FX SSRF and path traversal injection
    - Watchlist NUL-byte sanitization
    - Persistence malformed timestamp handling
    """

    def test_rate_limiter_rejects_untrusted_lan_proxy_spoofing(self, monkeypatch):
        """Private LAN IPs must NOT be trusted proxies unless explicitly in TRUSTED_PROXIES."""
        monkeypatch.delenv("TRUSTED_PROXIES", raising=False)
        # Without TRUSTED_PROXIES, private IP is not trusted
        assert _is_trusted_proxy("192.168.1.100") is False
        assert _is_trusted_proxy("10.0.0.5") is False
        assert _is_trusted_proxy("172.16.0.10") is False

        # Loopback is always trusted
        assert _is_trusted_proxy("127.0.0.1") is True
        assert _is_trusted_proxy("::1") is True
        assert _is_trusted_proxy("localhost") is True
        assert _is_trusted_proxy("testclient") is True

        # When explicitly configured, proxy is trusted
        monkeypatch.setenv("TRUSTED_PROXIES", "192.168.1.0/24, 10.0.0.1")
        assert _is_trusted_proxy("192.168.1.100") is True
        assert _is_trusted_proxy("10.0.0.1") is True
        assert _is_trusted_proxy("10.0.0.2") is False

    def test_smartapi_broker_fail_closed_mode(self):
        """SmartAPIBroker must refuse order placement when broker_mode is not 'live'."""
        broker = SmartAPIBroker(
            api_key="test_key",
            client_code="CLIENT01",
            password="pass",
            totp_secret="JBSWY3DPEHPK3PXP"
        )
        broker.is_connected = True
        broker.broker_mode = "disabled"

        with pytest.raises(RuntimeError, match="Live trading disabled"):
            broker.place_order(ticker="NIFTY", quantity=25, direction="BUY")

        broker.broker_mode = "paper"
        with pytest.raises(RuntimeError, match="Live trading disabled"):
            broker.place_order(ticker="NIFTY", quantity=25, direction="BUY")

    def test_smartapi_broker_input_validation(self):
        """SmartAPIBroker must reject invalid inputs: non-positive quantity, NaN price, invalid direction."""
        broker = SmartAPIBroker(
            api_key="test_key",
            client_code="CLIENT01",
            password="pass",
            totp_secret="JBSWY3DPEHPK3PXP"
        )
        broker.is_connected = True
        broker.broker_mode = "live"

        # Invalid quantity
        with pytest.raises(ValueError, match="Quantity must be a positive integer"):
            broker.place_order(ticker="NIFTY", quantity=-10, direction="BUY")
        with pytest.raises(ValueError, match="Quantity must be a positive integer"):
            broker.place_order(ticker="NIFTY", quantity=0, direction="BUY")

        # Invalid direction
        with pytest.raises(ValueError, match="Invalid direction"):
            broker.place_order(ticker="NIFTY", quantity=25, direction="HOLD")

        # Invalid order type
        with pytest.raises(ValueError, match="Unsupported order type"):
            broker.place_order(ticker="NIFTY", quantity=25, direction="BUY", order_type="ICEBERG")

        # Invalid limit price
        with pytest.raises(ValueError, match="Limit orders require a positive finite price"):
            broker.place_order(ticker="NIFTY", quantity=25, direction="BUY", order_type="LIMIT", price=float("nan"))
        with pytest.raises(ValueError, match="Limit orders require a positive finite price"):
            broker.place_order(ticker="NIFTY", quantity=25, direction="BUY", order_type="LIMIT", price=-100.0)

        # Invalid ticker
        with pytest.raises(ValueError, match="Valid ticker is required"):
            broker.place_order(ticker="", quantity=25, direction="BUY")
        with pytest.raises(ValueError, match="Valid ticker is required"):
            broker.place_order(ticker="NIFTY\x00MALICIOUS", quantity=25, direction="BUY")

    def test_frankfurter_fx_ssrf_and_path_traversal_rejection(self):
        """FrankfurterFXFetcher must reject path traversal and malformed dates."""
        assert FrankfurterFXFetcher.get_historical_usdinr_series_sync(start_date="../../etc/passwd") is None
        assert FrankfurterFXFetcher.get_historical_usdinr_series_sync(start_date="2026-99-99") is None
        assert FrankfurterFXFetcher.get_historical_usdinr_series_sync(start_date="not-a-date") is None
        assert FrankfurterFXFetcher.get_historical_usdinr_series_sync(start_date="2026-01-01", end_date="@evil.com") is None

    def test_swing_watchlist_nul_byte_sanitization(self):
        """AddWatchlistRequest must sanitize NUL bytes from sector, scanners, and notes."""
        req = AddWatchlistRequest(
            ticker="TRENT",
            sector="Retail\x00Corrupt",
            source_scanners=["Momentum\x00Screener"],
            composite_score=85.0,
            notes="Breakout note\x00with null byte"
        )
        assert req.sector == "RetailCorrupt"
        assert "\x00" not in req.sector
        assert req.source_scanners == ["MomentumScreener"]
        assert req.notes == "Breakout notewith null byte"
        assert "\x00" not in req.notes

    def test_papertrade_timestamp_malformed_graceful_recovery(self):
        """_timestamp must recover gracefully to current UTC time if passed corrupt timestamps."""
        t1 = _timestamp(None)
        assert isinstance(t1, datetime.datetime)
        assert t1.tzinfo is not None

        t2 = _timestamp("not-a-valid-iso-date-string")
        assert isinstance(t2, datetime.datetime)
        assert t2.tzinfo is not None

        t3 = _timestamp("2026-10-26T12:00:00Z")
        assert t3.year == 2026
        assert t3.hour == 12
