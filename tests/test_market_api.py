"""
Tests for Market API and Training Router Live Execution Endpoints.
"""

import pytest
from starlette.testclient import TestClient
from api.main import app

client = TestClient(app)


def test_market_status_endpoint():
    response = client.get("/api/v1/market/status")
    assert response.status_code == 200
    data = response.json()
    assert data["exchange"] == "NSE"
    assert "is_open" in data
    assert "session" in data
    assert "seconds_until_open" in data


def test_market_watchlist_endpoint():
    response = client.get("/api/v1/market/watchlist")
    assert response.status_code == 200
    data = response.json()
    assert "market_status" in data
    assert "watchlist" in data
    assert len(data["watchlist"]) > 0
    first = data["watchlist"][0]
    assert "ticker" in first
    assert "ltp" in first
    assert "recommendation" in first


def test_market_quote_endpoint():
    response = client.get("/api/v1/market/quote/NIFTY")
    assert response.status_code == 200
    data = response.json()
    assert data["ticker"] == "NIFTY"
    assert "ltp" in data
    assert data["exchange"] == "NSE"


def test_training_status_with_telemetry():
    response = client.get("/api/v1/training/status")
    assert response.status_code == 200
    data = response.json()
    assert "is_training" in data
    assert "mode" in data
    assert "market_status" in data
    assert "logs" in data


def test_training_live_portfolio_endpoint():
    response = client.get("/api/v1/training/live-portfolio")
    assert response.status_code == 200
    data = response.json()
    assert "market_status" in data
    assert "mode" in data


def test_market_option_chart_nifty_call():
    response = client.get("/api/v1/market/option-chart", params={
        "underlying": "NIFTY",
        "strike": 22800,
        "option_type": "CE",
        "timeframe": "1h",
        "limit": 30
    })
    assert response.status_code == 200
    data = response.json()
    assert data["underlying"] == "NIFTY"
    assert data["strike"] == 22800
    assert data["option_type"] == "CE"
    assert data["lot_size"] == 25
    assert "greeks" in data
    assert "delta" in data["greeks"]
    assert "theta" in data["greeks"]
    assert "gamma" in data["greeks"]
    assert "vega" in data["greeks"]
    assert "iv" in data["greeks"]
    assert "indicators" in data
    assert "vwap" in data["indicators"]
    assert "candles" in data
    assert len(data["candles"]) > 0
    first_candle = data["candles"][0]
    assert "open" in first_candle
    assert "high" in first_candle
    assert "low" in first_candle
    assert "close" in first_candle
    assert "volume" in first_candle
    assert "vwap" in first_candle
    assert first_candle["high"] >= first_candle["low"]


def test_market_option_chart_banknifty_put():
    response = client.get("/api/v1/market/option-chart", params={
        "underlying": "BANKNIFTY",
        "strike": 48500,
        "option_type": "PE",
        "timeframe": "1h",
        "limit": 20
    })
    assert response.status_code == 200
    data = response.json()
    assert data["underlying"] == "BANKNIFTY"
    assert data["strike"] == 48500
    assert data["option_type"] == "PE"
    assert data["lot_size"] == 15
    assert "greeks" in data
    # PE delta is negative
    assert data["greeks"]["delta"] <= 0


def test_market_live_tick_endpoint():
    response = client.get("/api/v1/market/live-tick/NIFTY")
    assert response.status_code == 200
    data = response.json()
    assert data["ticker"] == "NIFTY"
    assert "ltp" in data
    assert "bid" in data
    assert "ask" in data
    assert "candle" in data
    assert "is_market_open" in data
    assert "session" in data
    assert "market_phase" in data
    c = data["candle"]
    assert "open" in c
    assert "high" in c
    assert "low" in c
    assert "close" in c


def test_market_option_tick_endpoint():
    response = client.get("/api/v1/market/option-tick", params={
        "underlying": "NIFTY",
        "strike": 22800,
        "option_type": "CE"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["underlying"] == "NIFTY"
    assert data["strike"] == 22800
    assert data["option_type"] == "CE"
    assert "premium" in data
    assert "delta" in data
    assert "theta" in data
    assert "gamma" in data
    assert "candle" in data
    assert data["delta"] > 0


def test_market_status_session_phase():
    response = client.get("/api/v1/market/status")
    assert response.status_code == 200
    data = response.json()
    assert "market_phase" in data
    assert "session_phase" in data
    assert 0.0 <= data["session_phase"] <= 1.0


