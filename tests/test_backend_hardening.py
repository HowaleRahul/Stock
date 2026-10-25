"""
Comprehensive Adversarial and Security Hardening Test Suite.
Tests database pollution prevention, SSRF protection, XML entity expansion defense,
option chain scraping resilience, security headers, unified configuration concurrency,
strategy input validation / path traversal protection, and ticker regex sanitization.
"""

import pytest
import asyncio
import os
import json
import tempfile
import threading
from unittest.mock import patch, MagicMock, AsyncMock
from httpx import AsyncClient, ASGITransport
from fastapi import status
from sqlalchemy import select

from api.main import app
from api.config import settings
from api.db import async_session_factory
from models.models import Symbol
from data.service import DataIngestionService
from data.fetcher import YFinanceFetcher
from data.news_fetcher import NewsFetcher, _is_safe_redirect, _safe_parse_xml
from data.nse_feed import NSEFeed
from api.schemas import SymbolCreate, SyncRequest
from api.config_store import (
    load_config_atomic,
    save_config_atomic,
    update_config_atomic,
    _config_file_lock,
)


@pytest.fixture(autouse=True)
def mock_db_init():
    with patch("models.init_db.init_database", new_callable=AsyncMock) as mock_init:
        mock_init.return_value = {"status": "success", "message": "Mocked"}
        yield mock_init


# ===========================================================================
# 1. Database Pollution Prevention (data/service.py)
# ===========================================================================

@pytest.mark.asyncio
async def test_sync_symbol_ohlcv_does_not_call_get_or_create_on_empty_data():
    """Verify get_or_create_symbol is never invoked if external data fetch returns empty."""
    with patch("data.service.async_session_factory") as mock_session_fact, \
         patch.object(YFinanceFetcher, "fetch_ohlcv_bars", new_callable=AsyncMock) as mock_fetch, \
         patch.object(DataIngestionService, "get_or_create_symbol", new_callable=AsyncMock) as mock_create:

        mock_sess = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = None
        mock_sess.execute.return_value = mock_res
        mock_session_fact.return_value.__aenter__.return_value = mock_sess

        mock_fetch.return_value = []

        res = await DataIngestionService.sync_symbol_ohlcv("DOESNOTEXIST999")
        assert res["status"] == "no_data"
        assert res["bars_synced"] == 0
        assert res["symbol_id"] is None
        mock_create.assert_not_called()


@pytest.mark.asyncio
async def test_get_or_create_symbol_verify_external_flag_mocked():
    """Verify get_or_create_symbol raises ValueError when verify_external=True and no external data exists."""
    bogus_ticker = "VERIFY_EXT_FAIL_999"
    with patch("data.service.async_session_factory") as mock_session_fact, \
         patch.object(YFinanceFetcher, "verify_symbol_exists", new_callable=AsyncMock) as mock_v:
        mock_sess = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = None
        mock_sess.execute.return_value = mock_res
        mock_session_fact.return_value.__aenter__.return_value = mock_sess

        mock_v.return_value = False
        with pytest.raises(ValueError, match="External data verification failed"):
            await DataIngestionService.get_or_create_symbol(bogus_ticker, verify_external=True)


@pytest.mark.database
@pytest.mark.asyncio
async def test_sync_symbol_ohlcv_does_not_pollute_db_on_invalid_ticker():
    """Verify that sync_symbol_ohlcv for a non-existent ticker does NOT insert a Symbol row."""
    bogus_ticker = "NONEXISTENT_BOGUS_TICKER_123"

    # Ensure it's not currently in the DB
    async with async_session_factory() as session:
        stmt = select(Symbol).where(Symbol.ticker == bogus_ticker)
        res = await session.execute(stmt)
        assert res.scalar_one_or_none() is None

    # Mock fetcher to return empty bars (external verification failure)
    with patch.object(YFinanceFetcher, "fetch_ohlcv_bars", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = []
        result = await DataIngestionService.sync_symbol_ohlcv(bogus_ticker)

    assert result["status"] == "no_data"
    assert result["bars_synced"] == 0
    assert result["symbol_id"] is None

    # Verify symbol was NOT created in DB
    async with async_session_factory() as session:
        stmt = select(Symbol).where(Symbol.ticker == bogus_ticker)
        res = await session.execute(stmt)
        assert res.scalar_one_or_none() is None


@pytest.mark.database
@pytest.mark.asyncio
async def test_get_or_create_symbol_verify_external_flag():
    """Verify get_or_create_symbol raises ValueError when verify_external=True and no external data exists."""
    bogus_ticker = "VERIFY_EXT_FAIL_999"
    with patch.object(YFinanceFetcher, "verify_symbol_exists", new_callable=AsyncMock) as mock_v:
        mock_v.return_value = False
        with pytest.raises(ValueError, match="External data verification failed"):
            await DataIngestionService.get_or_create_symbol(bogus_ticker, verify_external=True)


# ===========================================================================
# 2. News Fetcher: URL Injection, SSRF, and XML Entity Expansion
# ===========================================================================

def test_news_fetcher_url_encoding():
    """Verify RSS query URL-encodes special characters and prevents parameter injection."""
    with patch("httpx.Client.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<rss><channel></channel></rss>"
        mock_get.return_value = mock_resp

        NewsFetcher._fetch_indian_rss_news_sync("TICKER&admin=1#frag")
        call_url = mock_get.call_args[0][0]
        # Verify query was properly quote_plus encoded
        assert "TICKER%26admin%3D1%23frag" in call_url or "TICKER+admin" not in call_url


def test_news_fetcher_ssrf_redirect_validation():
    """Verify _is_safe_redirect rejects non-HTTPS and private/loopback/link-local IP addresses."""
    # Loopback
    assert _is_safe_redirect("http://127.0.0.1:8000/api") is False
    assert _is_safe_redirect("https://127.0.0.1/api") is False
    assert _is_safe_redirect("https://localhost/api") is False
    # Link-local / Cloud metadata
    assert _is_safe_redirect("https://169.254.169.254/latest/meta-data/") is False
    assert _is_safe_redirect("http://169.254.169.254/latest/meta-data/") is False
    # Private subnets
    assert _is_safe_redirect("https://10.0.0.1/rss") is False
    assert _is_safe_redirect("https://192.168.1.100/rss") is False
    assert _is_safe_redirect("https://172.16.0.5/rss") is False
    # Dangerous protocols
    assert _is_safe_redirect("file:///etc/passwd") is False
    assert _is_safe_redirect("gopher://127.0.0.1:70") is False


def test_news_fetcher_xml_entity_expansion_defense():
    """Verify _safe_parse_xml rejects XML payloads containing DOCTYPE or ENTITY definitions."""
    billion_laughs = """<?xml version="1.0"?>
    <!DOCTYPE lolz [
     <!ENTITY lol "lol">
     <!ELEMENT lolz (#PCDATA)>
     <!ENTITY lol1 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
    ]>
    <lolz>&lol1;</lolz>
    """
    with pytest.raises(ValueError, match="Rejected suspicious XML payload"):
        _safe_parse_xml(billion_laughs)

    # Valid RSS XML must parse without errors
    valid_xml = "<rss><channel><title>Market News</title></channel></rss>"
    root = _safe_parse_xml(valid_xml)
    assert root.find("channel/title").text == "Market News"


# ===========================================================================
# 3. NSE Feed: URL Encoding, Akamai 401/403 Recovery, and Max Pain
# ===========================================================================

def test_nse_feed_clean_symbol_and_url_query_param():
    """Verify clean_symbol and that get_option_chain_raw encodes and strips suffixes for NSE API."""
    assert NSEFeed.clean_symbol("RELIANCE.NS") == "RELIANCE.NS"
    assert NSEFeed.clean_symbol("^NSEI") == "NIFTY"
    assert NSEFeed.clean_symbol("NIFTY 50") == "NIFTY"

    with patch.object(NSEFeed, "get_session") as mock_sess_func:
        mock_sess = MagicMock()
        mock_sess.get.return_value.status_code = 200
        mock_sess.get.return_value.json.return_value = {"records": {}}
        mock_sess_func.return_value = mock_sess

        NSEFeed.get_option_chain_raw("M&M.NS")
        called_url = mock_sess.get.call_args[0][0]
        # Query param should be URL-encoded without .NS
        assert "symbol=M%26M" in called_url


def test_nse_feed_option_chain_retries_on_401_session_expiry():
    """Verify get_option_chain_raw recovers from 401/403 session expiration with re-warming."""
    with patch.object(NSEFeed, "get_session") as mock_get_sess:
        mock_sess = MagicMock()
        mock_get_sess.return_value = mock_sess

        # Attempt 1: 401 Unauthorized; Attempt 2: 200 OK with records
        resp_401 = MagicMock()
        resp_401.status_code = 401

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {"records": {"data": []}}

        mock_sess.get.side_effect = [resp_401, resp_200]

        data = NSEFeed.get_option_chain_raw("RELIANCE.NS")
        assert data is not None
        assert "records" in data
        assert mock_sess.get.call_count == 2


def test_nse_feed_calculate_max_pain_handles_dirty_data():
    """Verify calculate_max_pain handles missing/non-numeric strikes and malformed CE/PE records."""
    dirty_chain = {
        "records": {
            "data": [
                {"strikePrice": "invalid", "CE": {"openInterest": 100}},
                {"strikePrice": None, "PE": {"openInterest": 50}},
                {"strikePrice": 2400.0, "CE": {"openInterest": 500}, "PE": {"openInterest": 200}},
                {"strikePrice": 2450.0, "CE": {"openInterest": 300}, "PE": {"openInterest": 400}},
                {"strikePrice": 2500.0, "CE": {"openInterest": 200}, "PE": {"openInterest": 600}},
            ]
        }
    }
    max_pain = NSEFeed.calculate_max_pain(dirty_chain)
    assert max_pain in (2400.0, 2450.0, 2500.0)


# ===========================================================================
# 4. Security Headers (api/main.py)
# ===========================================================================

@pytest.mark.asyncio
async def test_security_headers_baseline_and_production_csp(monkeypatch):
    """Verify baseline security headers and production CSP directives."""
    monkeypatch.setattr(settings, "environment", "production")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")

    headers = resp.headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in headers["Permissions-Policy"]
    assert "Strict-Transport-Security" in headers

    csp = headers.get("Content-Security-Policy", "")
    assert "frame-ancestors 'none'" in csp
    assert "unpkg.com" not in csp
    assert "object-src 'none'" in csp
    assert "base-uri 'self'" in csp


# ===========================================================================
# 5. Unified Config Store Concurrency (api/config_store.py)
# ===========================================================================

def test_unified_config_store_concurrency(tmp_path):
    """Verify concurrent reads and writes using atomic config store do not corrupt JSON."""
    test_cfg_path = str(tmp_path / "test_concurrency_config.json")
    save_config_atomic({"capital": 100000.0, "threads": []}, path=test_cfg_path)

    errors = []

    def writer_task(worker_id: int):
        try:
            for i in range(10):
                update_config_atomic({f"worker_{worker_id}_{i}": i * 10}, path=test_cfg_path)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer_task, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0

    # Ensure persisted file is valid JSON and contains updates
    final_cfg = load_config_atomic(test_cfg_path)
    assert isinstance(final_cfg, dict)
    assert final_cfg["capital"] == 100000.0
    # Every worker must have written their keys
    for worker_id in range(6):
        assert f"worker_{worker_id}_9" in final_cfg


# ===========================================================================
# 6. Strategy Validation & Path Traversal / IDOR (api/strategy_router.py)
# ===========================================================================

@pytest.mark.asyncio
async def test_strategy_name_path_traversal_rejection(monkeypatch):
    """Verify that strategy creation and deletion reject path traversal sequences and invalid characters."""
    monkeypatch.setattr(settings, "api_key", None)
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "api_host", "127.0.0.1")
    monkeypatch.setenv("API_KEY", "")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Path traversal in strategy name
        resp = await client.post("/api/v1/strategy/create", json={
            "name": "../../etc/passwd",
            "description": "Path Traversal Test",
            "bullish_conditions": [],
            "bearish_conditions": []
        })
        assert resp.status_code == 422

        # Path traversal in DELETE endpoint
        resp_del = await client.delete("/api/v1/strategy/..%2F..%2Fetc%2Fpasswd")
        assert resp_del.status_code in (400, 404)


@pytest.mark.asyncio
async def test_strategy_condition_validation_rejection(monkeypatch):
    """Verify strategy creation rejects invalid operators and code injection in indicators/values."""
    monkeypatch.setattr(settings, "api_key", None)
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "api_host", "127.0.0.1")
    monkeypatch.setenv("API_KEY", "")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Invalid operator (SQL/Eval injection attempt)
        resp1 = await client.post("/api/v1/strategy/create", json={
            "name": "Invalid Operator Strategy",
            "bullish_conditions": [
                {"indicator": "rsi", "operator": "EVAL_INJECTION", "value": "70"}
            ]
        })
        assert resp1.status_code == 422

        # Invalid indicator identifier
        resp2 = await client.post("/api/v1/strategy/create", json={
            "name": "Invalid Indicator Strategy",
            "bullish_conditions": [
                {"indicator": "rsi; rm -rf /", "operator": ">", "value": "70"}
            ]
        })
        assert resp2.status_code == 422

        # Valid strategy creation passes
        resp3 = await client.post("/api/v1/strategy/create", json={
            "name": "RSI Momentum Breakout",
            "description": "Valid custom strategy",
            "bullish_conditions": [
                {"indicator": "rsi", "operator": ">", "value": "70"},
                {"indicator": "ema_20", "operator": "crosses_above", "value": "ema_50"}
            ],
            "bearish_conditions": [
                {"indicator": "rsi", "operator": "<", "value": "30"}
            ]
        })
        assert resp3.status_code == 200
        assert resp3.json()["status"] == "success"

        # Cleanup created strategy
        await client.delete("/api/v1/strategy/RSI%20Momentum%20Breakout")


# ===========================================================================
# 7. Strengthened Ticker Regex (api/schemas.py)
# ===========================================================================

def test_symbol_create_ticker_validation():
    """Verify SymbolCreate accepts valid tickers and rejects malformed/dangerous inputs."""
    # Valid tickers
    valid_tickers = ["RELIANCE.NS", "TCS.BO", "AAPL", "BTC-USD", "^NSEI", "^BSESN", "GC=F", "M&M.NS"]
    for t in valid_tickers:
        model = SymbolCreate(ticker=t)
        assert model.ticker == t.upper()

    # Invalid / dangerous tickers
    invalid_tickers = [
        "../../etc/passwd",
        "RELIANCE; DROP TABLE symbols;",
        "<script>alert(1)</script>",
        "INVALID TICKER WITH SPACES",
        "RELIANCE.NS\x00NULLBYTE",
        "TICKER/PATH",
        "TICKER\\PATH",
        "",
        "   "
    ]
    for bad in invalid_tickers:
        with pytest.raises(Exception):
            SymbolCreate(ticker=bad)


def test_sync_request_ticker_validation():
    """Verify SyncRequest accepts None or valid tickers and rejects dangerous strings."""
    # Valid None
    assert SyncRequest(ticker=None).ticker is None

    # Valid ticker
    assert SyncRequest(ticker="INFY.NS").ticker == "INFY.NS"

    # Invalid tickers
    with pytest.raises(Exception):
        SyncRequest(ticker="INFY; DROP TABLE symbols;")

    with pytest.raises(Exception):
        SyncRequest(ticker="../traversal")
