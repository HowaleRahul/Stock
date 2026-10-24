"""
Unit & Integration Tests for Public APIs:
1. Frankfurter Currency API (ECB Live & Historical USD/INR)
2. Indian Market News & Financial Sentiment Engine (RSS + Tuned VADER)
3. Angel One SmartAPI Broker (Indices F&O, TOTP, SEBI Algo ID)
"""
import pytest
import datetime
from unittest.mock import patch, MagicMock
import pandas as pd

from data.fx_fetcher import FrankfurterFXFetcher
from data.news_fetcher import NewsFetcher
from api.broker import SmartAPIBroker, BrokerAPI


# ==========================================
# 1. Frankfurter Currency API Tests
# ==========================================

def test_frankfurter_fx_fetcher_live():
    """Verify live/cached USD/INR rate retrieval."""
    rate = FrankfurterFXFetcher.get_latest_usdinr_sync()
    assert isinstance(rate, float)
    assert rate > 50.0  # USD/INR is well above 50 INR per USD


def test_frankfurter_fx_fetcher_historical():
    """Verify historical USD/INR series retrieval."""
    series = FrankfurterFXFetcher.get_historical_usdinr_series_sync(days=10)
    assert series is not None
    assert isinstance(series, pd.Series)
    assert not series.empty
    assert (series > 50.0).all()


def test_frankfurter_fx_fetcher_network_fallback():
    """Verify graceful handling if remote Frankfurter API is unreachable."""
    with patch("httpx.Client.get", side_effect=Exception("Connection timed out")):
        rate = FrankfurterFXFetcher.get_latest_usdinr_sync()
        assert rate is None  # Gracefully returns None without crashing


# ==========================================
# 2. Indian Market News & Sentiment Engine
# ==========================================

def test_news_sentiment_vader_financial_tuning():
    """Verify financial lexicon tuning for market-specific terms."""
    bullish_sent = NewsFetcher.calculate_sentiment("Nifty surges to all-time high with massive rally in IT and banking")
    assert bullish_sent["compound"] > 0.05
    assert bullish_sent["label"] == "BULLISH"

    bearish_sent = NewsFetcher.calculate_sentiment("Sensex crashes 800 points in sudden market slump and panic selloff")
    assert bearish_sent["compound"] < -0.05
    assert bearish_sent["label"] == "BEARISH"

    neutral_sent = NewsFetcher.calculate_sentiment("Reserve Bank of India monetary policy committee meeting scheduled for Friday")
    assert neutral_sent["label"] == "NEUTRAL"


@pytest.mark.asyncio
async def test_news_sentiment_summary_structure():
    """Verify sentiment summary endpoint returns complete expected structure."""
    summary = await NewsFetcher.get_sentiment_summary("NIFTY")
    assert "ticker" in summary
    assert "total_headlines" in summary
    assert "bullish_count" in summary
    assert "bearish_count" in summary
    assert "neutral_count" in summary
    assert "overall_sentiment" in summary
    assert summary["overall_sentiment"] in ("BULLISH", "BEARISH", "NEUTRAL")
    assert "mean_score" in summary
    assert "headlines" in summary
    assert isinstance(summary["headlines"], list)


# ==========================================
# 3. Angel One SmartAPI Broker Integration
# ==========================================

def test_smartapi_totp_generation():
    """Verify RFC 6238 TOTP generation algorithm produces valid 6-digit string."""
    code = SmartAPIBroker._generate_totp("JBSWY3DPEHPK3PXP")
    assert isinstance(code, str)
    assert len(code) == 6
    assert code.isdigit()


def test_smartapi_fail_closed_without_live_mode():
    """SEBI compliance: SmartAPIBroker MUST refuse connection if BROKER_MODE is not 'live'."""
    broker = SmartAPIBroker(
        api_key="TEST_KEY",
        client_code="CLIENT_01",
        password="test_password",
        totp_secret="JBSWY3DPEHPK3PXP",
    )
    with patch.object(broker, "_verify_static_ip", return_value=True):
        # broker_mode defaults to 'disabled'
        broker.broker_mode = "disabled"
        connected = broker.connect()
        assert connected is False


def test_smartapi_place_order_mocked():
    """Verify order execution with SEBI Algo-ID tagging and payload structure."""
    broker = SmartAPIBroker(
        api_key="TEST_KEY",
        client_code="CLIENT_01",
        password="test_password",
        totp_secret="JBSWY3DPEHPK3PXP",
    )
    broker.is_connected = True
    broker.jwt_token = "MOCK_JWT_TOKEN"
    broker.algo_id = "SEBI_ALGO_INDEX_01"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": True,
        "data": {"orderid": "241023000987654"}
    }

    with patch("requests.post", return_value=mock_resp) as mock_post:
        order_id = broker.place_order(
            ticker="NIFTY26OCT25000CE",
            quantity=50,
            direction="BUY",
            order_type="LIMIT",
            price=125.50,
            exchange="NFO",
            symbol_token="998877",
        )
        assert order_id == "241023000987654"

        # Verify POST payload
        call_kwargs = mock_post.call_args.kwargs
        json_body = call_kwargs["json"]
        assert json_body["variety"] == "NORMAL"
        assert json_body["tradingsymbol"] == "NIFTY26OCT25000CE"
        assert json_body["symboltoken"] == "998877"
        assert json_body["transactiontype"] == "BUY"
        assert json_body["exchange"] == "NFO"
        assert json_body["ordertype"] == "LIMIT"
        assert json_body["price"] == "125.5"
        assert json_body["quantity"] == "50"
        assert json_body["tag"] == "SEBI_ALGO_INDEX_01"
