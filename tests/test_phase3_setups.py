import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock

from setups.options_setup import OptionsSetup
from setups.sentiment_setup import SentimentSetup
from setups.pattern_setup import PatternSetup

def test_options_setup_graceful_degradation():
    setup = OptionsSetup()
    # Mock yfinance to raise an exception
    with patch("setups.options_setup.yf.Ticker") as mock_ticker:
        mock_ticker.side_effect = Exception("Yahoo Finance API Down")
        
        # We don't actually need real data for this test, just a dummy DataFrame
        df = pd.DataFrame() 
        signal = setup.evaluate(df, ticker="RELIANCE.NS")
        
        assert signal.signal == "neutral"
        assert signal.confidence == 0.0
        assert "Error analyzing options" in signal.reasoning
        assert "Yahoo Finance API Down" in signal.reasoning

def test_options_setup_empty_data():
    setup = OptionsSetup()
    # Mock yfinance to return empty options
    with patch("setups.options_setup.yf.Ticker") as mock_ticker:
        instance = mock_ticker.return_value
        instance.options = () # No expirations
        
        df = pd.DataFrame() 
        signal = setup.evaluate(df, ticker="RELIANCE.NS")
        
        assert signal.signal == "neutral"
        assert signal.confidence == 0.0
        assert "No options data available" in signal.reasoning

def test_sentiment_setup_graceful_degradation():
    setup = SentimentSetup()
    with patch("setups.sentiment_setup.yf.Ticker") as mock_ticker:
        mock_ticker.side_effect = Exception("Network Timeout")
        
        df = pd.DataFrame()
        signal = setup.evaluate(df, ticker="TCS.NS")
        
        assert signal.signal == "neutral"
        assert signal.confidence == 0.0
        assert "Error processing sentiment" in signal.reasoning
        assert "Network Timeout" in signal.reasoning

def test_pattern_setup_double_top():
    setup = PatternSetup()
    
    # Generate synthetic Double Top data
    # Requires > 30 bars.
    # Pattern: rally to 100, drop to 90, rally to 100, drop to 80.
    
    prices = [50, 60, 70, 80, 90, 100, 95, 90, 85, 90, 95, 100, 95, 90, 85, 80]
    # Pad to 35 bars to meet the > 30 requirement
    pad = [50] * (35 - len(prices))
    full_prices = pad + prices
    
    df = pd.DataFrame({'close': full_prices})
    
    signal = setup.evaluate(df)
    
    # The last price is 80. The two peaks are 100.
    # It should detect a double top.
    assert signal.signal == "bearish"
    assert signal.confidence >= 0.8
    assert "Double Top" in signal.reasoning
