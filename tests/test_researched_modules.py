"""
Unit & Integration Tests for Upgraded Trading Modules

Validates functionality adopted from the 15 researched repositories:
- NSE Live Feed & PCR/Max-Pain math (from nsepython & Bharat-SM-Data)
- Minervini Volatility Contraction Pattern (from claude-trading-skills)
- Piotroski F-Score fundamental quality evaluation (from staskh/trading_skills)
- Gamma Exposure (GEX) & Dealer Positioning Engine (from staskh/trading_skills)
- Unified Multi-Broker Paper Matching Engine (from TheHardeep/fenix)
- Multi-Agent Decision Consensus Engine (from TauricResearch/TradingAgents)
"""

import pytest
import pandas as pd
import numpy as np

from data.nse_feed import NSEFeed
from setups.vcp_setup import VCPSetup
from setups.piotroski_setup import PiotroskiSetup, calculate_piotroski_score
from setups.options_setup import OptionsSetup
from setups.engine import SetupEngine
from ml.gex_engine import GEXEngine
from api.broker_adapter import UnifiedBrokerAdapter, PaperMatchingEngine, NormalizedOrder
from ml.multi_agent_consensus import MultiAgentConsensusEngine


# ===========================================================================
# 1. Tests for NSE Feed & Derivatives Math
# ===========================================================================

def test_nse_feed_clean_symbol():
    assert NSEFeed.clean_symbol("^NSEI") == "NIFTY"
    assert NSEFeed.clean_symbol("^NSEBANK") == "BANKNIFTY"
    assert NSEFeed.clean_symbol("^BSESN") == "SENSEX"
    assert NSEFeed.clean_symbol("RELIANCE.NS") == "RELIANCE.NS"


def test_nse_feed_pcr_calculation():
    # Mock option chain with calls and puts
    mock_chain = {
        "records": {
            "data": [
                {"strikePrice": 22000, "CE": {"openInterest": 1000, "totalTradedVolume": 500}, "PE": {"openInterest": 1500, "totalTradedVolume": 750}},
                {"strikePrice": 22100, "CE": {"openInterest": 2000, "totalTradedVolume": 1000}, "PE": {"openInterest": 2500, "totalTradedVolume": 1250}},
            ]
        }
    }
    pcr_oi, pcr_vol, put_oi, call_oi = NSEFeed.calculate_pcr(mock_chain)
    assert call_oi == 3000
    assert put_oi == 4000
    assert pcr_oi == round(4000 / 3000, 3)
    assert pcr_vol == round(2000 / 1500, 3)


def test_nse_feed_max_pain():
    mock_chain = {
        "records": {
            "data": [
                {"strikePrice": 22000, "CE": {"openInterest": 5000}, "PE": {"openInterest": 500}},
                {"strikePrice": 22100, "CE": {"openInterest": 3000}, "PE": {"openInterest": 3000}},
                {"strikePrice": 22200, "CE": {"openInterest": 500}, "PE": {"openInterest": 5000}},
            ]
        }
    }
    max_pain = NSEFeed.calculate_max_pain(mock_chain)
    assert max_pain == 22100.0


# ===========================================================================
# 2. Tests for VCP Setup (Mark Minervini)
# ===========================================================================

def test_vcp_setup_insufficient_bars():
    setup = VCPSetup()
    df = pd.DataFrame({"close": [100.0] * 20})
    signal = setup.evaluate(df)
    assert signal.signal == "neutral"
    assert signal.confidence == 0.0
    assert "Insufficient bars" in signal.reasoning


def test_vcp_setup_contraction_detection():
    setup = VCPSetup()
    # Create 60 bars of synthetic data with contracting waves
    # Earlier swing: high 120, low 100 (20 pt spread)
    # Middle swing: high 115, low 105 (10 pt spread)
    # Late swing: high 112, low 109 (3 pt spread, tight pivot)
    n = 60
    base = np.linspace(100, 110, n)
    # Add contraction pattern
    prices = list(base)
    for i in range(15, 35):
        prices[i] = 100.0 + 20.0 * np.sin((i - 15) * np.pi / 20)
    for i in range(35, 50):
        prices[i] = 105.0 + 10.0 * np.sin((i - 35) * np.pi / 15)
    for i in range(50, 60):
        prices[i] = 109.0 + 3.0 * np.sin((i - 50) * np.pi / 10)

    df = pd.DataFrame({
        "close": prices,
        "high": [p * 1.01 for p in prices],
        "low": [p * 0.99 for p in prices],
        "volume": [100000 - i * 500 for i in range(n)] # drying volume
    })

    signal = setup.evaluate(df, ticker="TATAMOTORS")
    assert signal.name == "Volatility Contraction (VCP)"
    assert signal.signal in ("bullish", "neutral")
    assert "w1_depth_pct" in signal.indicator_values


# ===========================================================================
# 3. Tests for Piotroski F-Score Setup
# ===========================================================================

def test_piotroski_setup_index_bypass():
    setup = PiotroskiSetup()
    df = pd.DataFrame({"close": [22000.0] * 10})
    signal = setup.evaluate(df, ticker="^NSEI")
    assert signal.signal == "neutral"
    assert "broad market index" in signal.reasoning


# ===========================================================================
# 4. Tests for GEX (Gamma Exposure) Engine
# ===========================================================================

def test_gex_engine_analysis():
    spot = 22000.0
    strikes_data = [
        {"strike": 21800.0, "call_oi": 10000, "put_oi": 50000},
        {"strike": 22000.0, "call_oi": 30000, "put_oi": 30000},
        {"strike": 22200.0, "call_oi": 60000, "put_oi": 10000},
    ]
    res = GEXEngine.analyze_chain_gex(spot, strikes_data, lot_size=25, iv=0.15, days_to_expiry=3.0)

    assert "net_gex_crores" in res
    assert "regime" in res
    assert "call_wall" in res
    assert "put_wall" in res
    assert res["call_wall"] == 22200.0  # highest call OI
    assert res["put_wall"] == 21800.0   # highest put OI


# ===========================================================================
# 5. Tests for Unified Broker Adapter & Paper Matching Engine
# ===========================================================================

def test_paper_matching_engine_market_order():
    engine = PaperMatchingEngine(slippage_pct=0.001)
    order = NormalizedOrder(
        order_id="TEST_001",
        symbol="NIFTY22000CE",
        direction="BUY",
        quantity=50,
        order_type="MARKET",
        price=100.0,
    )
    res = engine.submit_order(order, current_ltp=100.0)
    assert res.status == "FILLED"
    assert res.fill_price > 100.0  # buy slippage
    assert engine.positions["NIFTY22000CE"]["quantity"] == 50


def test_paper_matching_engine_sl_trigger_then_convert():
    engine = PaperMatchingEngine(slippage_pct=0.0)
    # Buy first to establish position
    buy_order = NormalizedOrder(
        order_id="BUY_001",
        symbol="NIFTY",
        direction="BUY",
        quantity=25,
        order_type="MARKET",
    )
    engine.submit_order(buy_order, current_ltp=22000.0)

    # Place Stop Loss Market order below at 21900
    sl_order = NormalizedOrder(
        order_id="SL_001",
        symbol="NIFTY",
        direction="SELL",
        quantity=25,
        order_type="SL-M",
        trigger_price=21900.0,
    )
    engine.submit_order(sl_order, current_ltp=22000.0)
    assert "SL_001" in engine.resting_orders

    # Tick at 21950: should NOT trigger
    fills = engine.on_tick("NIFTY", ltp=21950.0)
    assert len(fills) == 0
    assert "SL_001" in engine.resting_orders

    # Tick drops to 21890: should trigger and fill!
    fills = engine.on_tick("NIFTY", ltp=21890.0)
    assert len(fills) == 1
    assert fills[0].status == "FILLED"
    assert fills[0].fill_price == 21900.0
    assert "SL_001" not in engine.resting_orders
    assert engine.positions["NIFTY"]["quantity"] == 0  # position closed!


def test_unified_broker_adapter_connection_and_order():
    adapter = UnifiedBrokerAdapter(broker_name="paper")
    assert adapter.connect() is True

    order_id = adapter.place_order(
        symbol="BANKNIFTY",
        quantity=15,
        direction="BUY",
        order_type="MARKET",
        current_ltp=48000.0,
    )
    assert order_id.startswith("ORD_PAP_")
    assert adapter.get_balance() > 0


# ===========================================================================
# 6. Tests for Multi-Agent Consensus Engine
# ===========================================================================

def test_multi_agent_consensus_bullish():
    from setups.base import SetupSignal
    signals = [
        SetupSignal("MA Crossover", "bullish", 0.8, "Golden cross"),
        SetupSignal("RSI", "bullish", 0.7, "Bouncing from oversold"),
        SetupSignal("Breakout", "bullish", 0.75, "20-day high broken"),
    ]
    regime = {"regime": "trending", "adx": 30.0}
    opt_data = {"pcr_oi": 1.35, "gex_regime": "POSITIVE_GAMMA"}
    fund_data = {"piotroski_score": 8}
    sent_data = {"mean_score": 0.40, "fii_net_crores": 1200.0}

    verdict = MultiAgentConsensusEngine.evaluate(
        ticker="NIFTY",
        regime_data=regime,
        setup_signals=signals,
        options_data=opt_data,
        fundamental_data=fund_data,
        sentiment_data=sent_data,
    )

    assert verdict.consensus_signal == "bullish"
    assert verdict.consensus_confidence >= 0.70
    assert len(verdict.bull_arguments) >= 3
    assert "APPROVED" in verdict.chief_risk_ruling
    assert len(verdict.agent_reports) == 4


def test_setup_engine_include_advanced():
    engine_core = SetupEngine(include_advanced=False)
    assert len(engine_core.setups) == 6

    engine_adv = SetupEngine(include_advanced=True)
    assert len(engine_adv.setups) == 9
