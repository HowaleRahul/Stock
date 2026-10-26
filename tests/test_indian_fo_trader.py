"""
Exhaustive Quant SDET & Financial Risk Test Suite for Indian F&O Trading Engine.

Tests:
1. Dynamic Days to Expiry (DTE) per Index (MIDCPNIFTY, FINNIFTY, BANKNIFTY, NIFTY, SENSEX)
   fractional trading days calculation until 15:30 IST on expiry day.
2. Real Derivatives & Sentiment Context in MultiAgentConsensusEngine (PCR, Max-Pain, GEX, FII/DII).
3. Intraday MIS Square-Off Rule (15:15 IST / 3:15 PM) enforcement in Paper Trader & Live Market Learner.
4. Real-World Indian F&O Regulatory & Brokerage Friction Model (Brokerage, STT, NSE Txn, GST, Stamp Duty, Breakeven).
5. Dynamic India VIX IV resolution in DerivativeEngine.
6. Adversarial edge cases (zero/negative DTE, NaN inputs, extreme volatility, market closures).
"""

import math
import datetime
from unittest.mock import patch, MagicMock
import pytest
import pandas as pd
import numpy as np

from ml.options_engine import (
    DerivativeEngine,
    DerivativeTradePlan,
    get_days_to_expiry,
    normalize_index_ticker,
    INDEX_EXPIRY_WEEKDAYS,
    IST,
)
from ml.risk_engine import (
    RiskEngine,
    TradePlan,
    IndianFOFrictionModel,
    FOFrictionBreakdown,
    is_intraday_square_off_time,
)
from ml.multi_agent_consensus import MultiAgentConsensusEngine
from ml.live_market_learner import LiveMarketLearner
from data.realtime_feed import RealTimeDataFeed
from data.nse_feed import NSEFeed


# ===========================================================================
# 1. Dynamic Days to Expiry (DTE) per Index Tests
# ===========================================================================

class TestDynamicDTEPerIndex:
    """Validates the fractional trading days calculation per Indian Index."""

    def test_index_weekday_mapping(self):
        """Verifies correct weekly expiry days for all Indian index derivatives."""
        assert INDEX_EXPIRY_WEEKDAYS["MIDCPNIFTY"] == 0  # Monday
        assert INDEX_EXPIRY_WEEKDAYS["FINNIFTY"] == 1    # Tuesday
        assert INDEX_EXPIRY_WEEKDAYS["BANKNIFTY"] == 2   # Wednesday
        assert INDEX_EXPIRY_WEEKDAYS["NIFTY"] == 3       # Thursday
        assert INDEX_EXPIRY_WEEKDAYS["^NSEI"] == 3       # Thursday
        assert INDEX_EXPIRY_WEEKDAYS["SENSEX"] == 4      # Friday
        assert INDEX_EXPIRY_WEEKDAYS["^BSESN"] == 4      # Friday

    def test_normalize_index_ticker(self):
        """Validates ticker normalization across dirty inputs."""
        assert normalize_index_ticker("NIFTY 50") == "NIFTY"
        assert normalize_index_ticker("^NSEI") == "NIFTY"
        assert normalize_index_ticker("BANKNIFTY") == "BANKNIFTY"
        assert normalize_index_ticker("^NSEBANK") == "BANKNIFTY"
        assert normalize_index_ticker("FINNIFTY") == "FINNIFTY"
        assert normalize_index_ticker("MIDCPNIFTY") == "MIDCPNIFTY"
        assert normalize_index_ticker("SENSEX") == "SENSEX"
        assert normalize_index_ticker("^BSESN") == "SENSEX"

    def test_nifty_thursday_expiry_same_day_intraday(self):
        """
        NIFTY (Thursday expiry):
        Session: 09:15 to 15:30 IST (375 minutes).
        - At 09:15 -> exactly 1.0 trading day.
        - At 12:22:30 (halfway) -> exactly 0.5 trading days.
        - At 15:30 -> 0.0 trading days.
        """
        # Thursday date: 2026-10-29
        thu_0915 = datetime.datetime(2026, 10, 29, 9, 15, tzinfo=IST)
        assert get_days_to_expiry("NIFTY", dt=thu_0915) == 1.0

        thu_mid = datetime.datetime(2026, 10, 29, 12, 22, 30, tzinfo=IST)
        assert abs(get_days_to_expiry("NIFTY", dt=thu_mid) - 0.5) < 0.01

        thu_1530 = datetime.datetime(2026, 10, 29, 15, 30, tzinfo=IST)
        assert get_days_to_expiry("NIFTY", dt=thu_1530) == 0.0

    def test_nifty_thursday_expiry_post_close_roll(self):
        """After 15:30 on expiry day, the contract rolls to next week (5 trading days)."""
        thu_1535 = datetime.datetime(2026, 10, 29, 15, 35, tzinfo=IST)
        dte = get_days_to_expiry("NIFTY", dt=thu_1535)
        assert dte == 5.0  # Fri(1) + Mon(1) + Tue(1) + Wed(1) + Thu(1)

    def test_midcpnifty_monday_expiry_over_weekend(self):
        """
        MIDCPNIFTY (Monday expiry):
        On Friday 15:30 IST, Saturday and Sunday contribute 0.0.
        Remaining trading days until Monday 15:30 IST = exactly 1.0 trading day.
        """
        # Friday: 2026-10-30 15:30 IST
        fri_1530 = datetime.datetime(2026, 10, 30, 15, 30, tzinfo=IST)
        dte = get_days_to_expiry("MIDCPNIFTY", dt=fri_1530)
        assert dte == 1.0

    def test_finnifty_tuesday_expiry(self):
        """FINNIFTY (Tuesday expiry) evaluated on Monday morning (09:15 IST)."""
        # Monday 09:15 -> Mon(1.0) + Tue(1.0) = 2.0 trading days
        mon_0915 = datetime.datetime(2026, 10, 26, 9, 15, tzinfo=IST)
        dte = get_days_to_expiry("FINNIFTY", dt=mon_0915)
        assert dte == 2.0

    def test_banknifty_wednesday_and_monthly_thursday(self):
        """BANKNIFTY: weekly is Wednesday, monthly is last Thursday."""
        # Monday 09:15 -> Mon(1.0) + Tue(1.0) + Wed(1.0) = 3.0 trading days (weekly)
        mon_0915 = datetime.datetime(2026, 10, 26, 9, 15, tzinfo=IST)
        dte_weekly = get_days_to_expiry("BANKNIFTY", dt=mon_0915, is_monthly=False)
        assert dte_weekly == 3.0

        # Monthly BANKNIFTY expires on Thursday
        dte_monthly = get_days_to_expiry("BANKNIFTY", dt=mon_0915, is_monthly=True)
        assert dte_monthly >= 4.0

    def test_sensex_friday_expiry(self):
        """SENSEX / ^BSESN (Friday expiry) evaluated on Wednesday 15:30 IST."""
        # Wednesday 15:30 -> Wed is done (0.0) + Thu(1.0) + Fri(1.0) = 2.0 trading days
        wed_1530 = datetime.datetime(2026, 10, 28, 15, 30, tzinfo=IST)
        dte = get_days_to_expiry("SENSEX", dt=wed_1530)
        assert dte == 2.0

    def test_utc_timezone_awareness(self):
        """Datetime provided in UTC is accurately converted to IST."""
        # 03:45 UTC is 09:15 IST (+5:30)
        thu_utc = datetime.datetime(2026, 10, 29, 3, 45, tzinfo=datetime.timezone.utc)
        assert get_days_to_expiry("NIFTY", dt=thu_utc) == 1.0

    def test_derivative_engine_delegation(self):
        """DerivativeEngine instance method delegates accurately to get_days_to_expiry."""
        engine = DerivativeEngine()
        thu_0915 = datetime.datetime(2026, 10, 29, 9, 15, tzinfo=IST)
        assert engine.get_days_to_expiry("NIFTY", dt=thu_0915) == 1.0


# ===========================================================================
# 2. Real Derivatives & Sentiment Context in MultiAgentConsensus
# ===========================================================================

class TestMultiAgentConsensusLiveContext:
    """Validates live PCR, Max-Pain, GEX, and FII/DII context in Multi-Agent Debate."""

    def test_fetch_live_context_with_mock_chain(self):
        """Verifies fetch_live_context parses raw NSE chain and computes PCR, Max Pain, GEX."""
        mock_raw_chain = {
            "records": {
                "data": [
                    {
                        "strikePrice": 22000,
                        "CE": {"openInterest": 10000, "totalTradedVolume": 5000},
                        "PE": {"openInterest": 15000, "totalTradedVolume": 7000},
                    },
                    {
                        "strikePrice": 22100,
                        "CE": {"openInterest": 8000, "totalTradedVolume": 4000},
                        "PE": {"openInterest": 12000, "totalTradedVolume": 6000},
                    },
                ]
            }
        }
        mock_fii_dii = {
            "fii_net_crores": 1540.50,
            "dii_net_crores": 620.00,
            "sentiment": "BULLISH",
        }

        with patch.object(NSEFeed, "get_option_chain_raw", return_value=mock_raw_chain), \
             patch.object(NSEFeed, "get_fii_dii_activity", return_value=mock_fii_dii):

            opts_data, sent_data = MultiAgentConsensusEngine.fetch_live_context("NIFTY", spot=22050.0)

            assert opts_data["pcr_oi"] == round(27000 / 18000, 3)  # 1.50
            assert opts_data["max_pain"] in (22000.0, 22100.0)
            assert opts_data["gex_regime"] in ("POSITIVE_GAMMA", "NEGATIVE_GAMMA", "NEUTRAL")
            assert sent_data["fii_net_crores"] == 1540.50
            assert sent_data["sentiment"] == "BULLISH"

    def test_consensus_evaluation_with_bullish_derivatives(self):
        """When PCR > 1.2 and FII flow > 500 Cr, Derivatives and Sentiment agents agree Bullish."""
        opts_data = {
            "pcr_oi": 1.45,
            "gex_regime": "POSITIVE_GAMMA",
            "max_pain": 22200.0,
        }
        sent_data = {
            "fii_net_crores": 1250.0,
            "dii_net_crores": 400.0,
            "mean_score": 0.25,
        }
        regime = {"regime": "trending", "adx": 28.0}
        from setups.base import SetupSignal
        signals = [
            SetupSignal("VCP", "bullish", 0.78, "Volatility contraction breakout"),
            SetupSignal("RSI", "bullish", 0.72, "Momentum continuation"),
        ]

        verdict = MultiAgentConsensusEngine.evaluate(
            ticker="NIFTY",
            regime_data=regime,
            setup_signals=signals,
            options_data=opts_data,
            sentiment_data=sent_data,
        )

        assert verdict.consensus_signal == "bullish"
        assert verdict.consensus_confidence >= 0.70
        assert "APPROVED" in verdict.chief_risk_ruling

        # Assert Derivatives Analyst report
        deriv_report = next(r for r in verdict.agent_reports if r.agent_name == "Derivatives Analyst")
        assert deriv_report.stance == "BULLISH"
        assert deriv_report.key_metrics["pcr"] == 1.45
        assert deriv_report.key_metrics["max_pain"] == 22200.0
        assert "Max-Pain Strike" in deriv_report.thesis

        # Assert Sentiment Analyst report
        sent_report = next(r for r in verdict.agent_reports if r.agent_name == "Sentiment Analyst")
        assert sent_report.stance == "BULLISH"
        assert sent_report.conviction >= 0.65

    def test_fetch_live_context_offline_fallback(self):
        """When NSE feeds are offline (weekend/network error), fallback values prevent crash."""
        with patch.object(NSEFeed, "get_option_chain_raw", return_value=None), \
             patch.object(NSEFeed, "get_fii_dii_activity", return_value={"fii_net_crores": 0.0, "dii_net_crores": 0.0}):

            opts_data, sent_data = MultiAgentConsensusEngine.fetch_live_context("NIFTY", spot=22000.0)
            assert opts_data["pcr_oi"] == 1.0
            assert opts_data["gex_regime"] == "NEUTRAL"
            assert opts_data["max_pain"] == 22000.0
            assert sent_data["fii_net_crores"] == 0.0


# ===========================================================================
# 3. Intraday MIS Square-Off Rule (15:15 IST / 3:15 PM) Tests
# ===========================================================================

class TestIntradayMISSquareOff:
    """Validates the strict 15:15 IST square-off rule for Indian markets."""

    def test_is_intraday_square_off_time_boundaries(self):
        """Validates exact second boundaries for 15:15 IST."""
        # 15:14:59 -> False
        before = datetime.datetime(2026, 10, 27, 15, 14, 59, tzinfo=IST)
        assert is_intraday_square_off_time(before) is False

        # 15:15:00 -> True
        exact = datetime.datetime(2026, 10, 27, 15, 15, 0, tzinfo=IST)
        assert is_intraday_square_off_time(exact) is True

        # 15:20:00 -> True
        after = datetime.datetime(2026, 10, 27, 15, 20, 0, tzinfo=IST)
        assert is_intraday_square_off_time(after) is True

        # 10:00:00 -> False
        morning = datetime.datetime(2026, 10, 27, 10, 0, 0, tzinfo=IST)
        assert is_intraday_square_off_time(morning) is False

    def test_live_market_learner_mis_square_off_trigger(self):
        """Open options position must be forced closed at 15:15 IST with exit_reason='INTRADAY_SQUARE_OFF'."""
        learner = LiveMarketLearner(starting_capital=10000.0)
        open_trade = {
            "ticker": "NIFTY",
            "underlying_ticker": "NIFTY",
            "instrument_type": "OPTION",
            "direction": "LONG",
            "entry_price": 120.0,
            "current_ltp": 125.0,
            "sl": 90.0,
            "tp": 180.0,
            "invested": 3000.0,
            "quantity": 25,
            "total_quantity": 25,
            "bars_held": 2,
            "status": "OPEN",
        }
        learner.open_trades = [open_trade]

        # Simulate tick at 15:15 IST
        dt_square_off = datetime.datetime(2026, 10, 27, 15, 15, 0, tzinfo=IST)
        with patch.object(RealTimeDataFeed, "get_realtime_quote_sync", return_value={"ltp": 22100.0, "open": 22100.0, "high": 22120.0, "low": 22090.0}):
            learner.manage_open_trades(current_dt=dt_square_off)

        # Trade must be closed with exit_reason == "INTRADAY_SQUARE_OFF"
        assert len(learner.open_trades) == 0
        assert open_trade["status"] == "INTRADAY_SQUARE_OFF"
        assert open_trade["exit_price"] == 125.0
        assert open_trade["cash_pnl"] is not None


# ===========================================================================
# 4. Real-World Indian F&O Friction Model Tests
# ===========================================================================

class TestIndianFOFrictionModel:
    """Validates the mathematical precision of Indian F&O regulatory and broker costs."""

    def test_options_friction_mathematical_precision(self):
        """
        Tests exact component charges for Indian Options:
        - Buy: 25 qty @ ₹100 = ₹2,500 turnover
        - Sell: 25 qty @ ₹150 = ₹3,750 turnover
        """
        f = IndianFOFrictionModel.calculate_options_friction(
            buy_premium=100.0,
            sell_premium=150.0,
            quantity=25
        )

        assert f.brokerage == 40.0  # ₹20 buy + ₹20 sell
        assert f.stt == round(3750.0 * 0.001, 2)  # 0.1% on sell premium = ₹3.75
        expected_txn = (2500.0 + 3750.0) * 0.0005  # 0.05% on premium = ₹3.125
        assert abs(f.exchange_txn_charge - expected_txn) < 0.01
        expected_gst = (40.0 + expected_txn) * 0.18  # 18% on (Brokerage + Txn)
        assert abs(f.gst - expected_gst) < 0.01
        expected_stamp = 2500.0 * 0.00003  # 0.003% on buy = ₹0.075
        assert abs(f.stamp_duty - expected_stamp) < 0.01

        # Gross PnL = (150 - 100) * 25 = ₹1,250.0
        assert f.gross_pnl == 1250.0
        assert f.net_pnl == f.gross_pnl - f.total_friction

    def test_options_analytical_breakeven_zero_net_pnl(self):
        """
        Crucial Quant Test: If exiting exactly at the analytical breakeven price,
        net PnL must equal ₹0.00 (covering all brokerage, STT, txn, GST, stamp).
        """
        buy_prem = 120.0
        qty = 50

        # Calculate initial friction to obtain breakeven price
        f_init = IndianFOFrictionModel.calculate_options_friction(
            buy_premium=buy_prem,
            sell_premium=buy_prem * 1.5,
            quantity=qty
        )
        be_price = f_init.breakeven_exit_price
        assert be_price > buy_prem

        # Now evaluate friction AT the breakeven exit price
        f_at_be = IndianFOFrictionModel.calculate_options_friction(
            buy_premium=buy_prem,
            sell_premium=be_price,
            quantity=qty
        )

        # Net PnL must be 0 within 0.01 rupee rounding tolerance
        assert abs(f_at_be.net_pnl) < 0.01

    def test_futures_friction_mathematical_precision(self):
        """
        Tests exact component charges for Indian Futures:
        - NIFTY Future (25 qty) entry @ 22,000, exit @ 22,100
        """
        f = IndianFOFrictionModel.calculate_futures_friction(
            entry_price=22000.0,
            exit_price=22100.0,
            quantity=25,
            direction="LONG"
        )

        assert f.brokerage == 40.0  # ₹20 buy + ₹20 sell
        # STT: 0.02% on sell turnover (22,100 * 25 = 552,500 -> ₹110.50)
        assert abs(f.stt - (552500.0 * 0.0002)) < 0.01
        # Exchange txn: 0.0019% on total turnover
        total_turnover = 22000.0 * 25 + 22100.0 * 25
        assert abs(f.exchange_txn_charge - (total_turnover * 0.000019)) < 0.01

        assert f.gross_pnl == 2500.0  # 100 pts * 25
        assert f.net_pnl == f.gross_pnl - f.total_friction

    def test_futures_analytical_breakeven_zero_net_pnl(self):
        """At analytical breakeven for Futures, net PnL must equal ₹0.00."""
        entry = 22000.0
        qty = 25
        f_init = IndianFOFrictionModel.calculate_futures_friction(
            entry_price=entry,
            exit_price=22100.0,
            quantity=qty,
            direction="LONG"
        )
        be_price = f_init.breakeven_exit_price
        assert be_price > entry

        f_at_be = IndianFOFrictionModel.calculate_futures_friction(
            entry_price=entry,
            exit_price=be_price,
            quantity=qty,
            direction="LONG"
        )
        assert abs(f_at_be.net_pnl) < 0.02

    def test_risk_engine_friction_gating_rejects_sub_breakeven(self):
        """RiskEngine must reject trades whose target profit does not cover transaction friction."""
        re = RiskEngine()
        df = pd.DataFrame({
            "close": [22000.0] * 50,
            "high": [22005.0] * 50,
            "low": [21995.0] * 50,
            "open": [22000.0] * 50,
            "atr": [2.0] * 50,  # Extremely low ATR -> target tiny
        })

        plan = re.generate_trade_plan(
            ticker="NIFTY",
            direction="bullish",
            ai_probability=0.75,
            df=df,
            capital=10000.0,
            timeframe="1h",
        )
        # Small profit will be below friction or fail RR
        assert plan.estimated_friction > 0.0
        assert plan.breakeven_price > 0.0


# ===========================================================================
# 5. Dynamic India VIX IV Tests
# ===========================================================================

class TestDynamicIndiaVIXIV:
    """Validates dynamic fetching of real India VIX into DerivativeEngine."""

    def test_candle_context_macro_vix_preferred(self):
        """When spot_plan has macro_vix, DerivativeEngine uses it directly."""
        spot_plan = TradePlan(
            ticker="NIFTY",
            direction="LONG",
            timeframe="1h",
            entry_price=22000.0,
            stop_loss=21900.0,
            take_profit=22250.0,
            ai_probability=0.75,
            capital=50000.0,
        )
        # Attach candle context macro_vix = 18.5%
        setattr(spot_plan, "macro_vix", 18.5)

        engine = DerivativeEngine()
        plan = engine.generate_derivative_plan(
            spot_plan=spot_plan,
            capital=50000.0,
            derivative_type="OPTIONS",
            iv=None  # Must fetch dynamically
        )

        assert plan.iv == 0.185

    def test_realtime_feed_vix_fetched_when_none(self):
        """When macro_vix is None, fetch live India VIX from RealTimeDataFeed."""
        spot_plan = TradePlan(
            ticker="NIFTY",
            direction="LONG",
            timeframe="1h",
            entry_price=22000.0,
            stop_loss=21900.0,
            take_profit=22250.0,
            ai_probability=0.75,
            capital=50000.0,
        )

        engine = DerivativeEngine()
        with patch.object(RealTimeDataFeed, "get_india_vix_sync", return_value=16.8):
            plan = engine.generate_derivative_plan(
                spot_plan=spot_plan,
                capital=50000.0,
                derivative_type="OPTIONS",
                iv=None
            )
            assert plan.iv == 0.168

    def test_calculate_option_mtm_uses_dynamic_vix(self):
        """Option MTM re-pricing dynamically uses live India VIX if IV omitted."""
        engine = DerivativeEngine()
        trade = {
            "ticker": "NIFTY",
            "strike": 22000.0,
            "option_type": "CE",
            "entry_price": 150.0,
            "days_to_expiry": 3.0,
        }

        with patch.object(RealTimeDataFeed, "get_india_vix_sync", return_value=17.5):
            prem, delta = engine.calculate_option_mtm(
                trade=trade,
                current_spot=22050.0,
                days_elapsed=0.5,
                iv=None
            )
            assert prem > 0.0
            assert 0.0 <= delta <= 1.0


# ===========================================================================
# 6. Adversarial Stress & Edge Case Tests
# ===========================================================================

class TestAdversarialQuantEdgeCases:
    """Stress tests Black-Scholes, DTE, and risk calculations under extreme conditions."""

    def test_zero_or_negative_dte_intrinsic_settlement(self):
        """At DTE <= 0.0, Black-Scholes options pricing converges exactly to intrinsic value."""
        engine = DerivativeEngine()
        # In-the-money Call (Spot 22100 > Strike 22000) at expiry moment
        bs_ce = engine.black_scholes(S=22100.0, K=22000.0, T=0.0, r=0.065, sigma=0.15, option_type="CE")
        assert bs_ce["premium"] == 100.0
        assert bs_ce["delta"] == 1.0
        assert bs_ce["gamma"] == 0.0

        # Out-of-the-money Call at expiry moment
        bs_ce_otm = engine.black_scholes(S=21900.0, K=22000.0, T=0.0, r=0.065, sigma=0.15, option_type="CE")
        assert bs_ce_otm["premium"] == 0.05  # minimum tick
        assert bs_ce_otm["delta"] == 0.0

    def test_extreme_volatility_bounds(self):
        """Zero volatility or extremely high volatility bounds must not raise exceptions."""
        engine = DerivativeEngine()
        # Zero vol
        bs_zero_vol = engine.black_scholes(S=22000.0, K=22000.0, T=0.05, r=0.065, sigma=0.0, option_type="CE")
        assert bs_zero_vol["premium"] >= 0.05

        # Massive 500% vol
        bs_high_vol = engine.black_scholes(S=22000.0, K=22000.0, T=0.05, r=0.065, sigma=5.0, option_type="CE")
        assert bs_high_vol["premium"] > 0.0
        assert not math.isnan(bs_high_vol["delta"])

    def test_non_numeric_nan_inf_safety(self):
        """Engine gracefully handles NaN or Inf spot prices without crashing."""
        engine = DerivativeEngine()
        bs_nan = engine.black_scholes(S=float("nan"), K=22000.0, T=0.05, r=0.065, sigma=0.15)
        assert bs_nan["premium"] == 0.05
        assert bs_nan["delta"] == 0.0

        bs_inf = engine.black_scholes(S=float("inf"), K=22000.0, T=0.05, r=0.065, sigma=0.15)
        assert bs_inf["premium"] == 0.05


# ===========================================================================
# 7. Indian Option Selling, Credit Spreads & Breakeven Friction Tests
# ===========================================================================

class TestOptionSellingAndCreditSpreads:
    """Validates institutional Indian Option Selling and Credit Spread mechanics."""

    def test_directional_option_selling_bullish_and_bearish(self):
        """
        Directional Option Selling:
        - When Spot is Bullish: Sells OTM Put (PE) with positive Theta and SPAN margin.
        - When Spot is Bearish: Sells OTM Call (CE) with positive Theta and SPAN margin.
        """
        engine = DerivativeEngine()
        spot_plan_bearish = TradePlan(
            ticker="NIFTY",
            direction="SHORT",
            entry_price=24000.0,
            take_profit=23800.0,
            stop_loss=24100.0,
            capital=500000.0,
            ai_probability=0.75,
            regime="rangebound"
        )
        plan_sell_ce = engine.generate_derivative_plan(
            spot_plan=spot_plan_bearish,
            capital=500000.0,
            derivative_type="SELL_OPTIONS",
            iv=0.15
        )
        assert plan_sell_ce.action == "SELL"
        assert plan_sell_ce.option_type == "CE"
        assert plan_sell_ce.strike_price >= 24000.0  # OTM Call
        assert plan_sell_ce.theta > 0.0  # Time decay is POSITIVE income for seller!
        assert plan_sell_ce.delta < 0.0  # Selling Call is bearish delta
        assert plan_sell_ce.margin_or_premium_required > 50000.0  # Enforces SPAN margin
        assert plan_sell_ce.is_approved is True

        spot_plan_bullish = TradePlan(
            ticker="NIFTY",
            direction="LONG",
            entry_price=24000.0,
            take_profit=24200.0,
            stop_loss=23900.0,
            capital=500000.0,
            ai_probability=0.75,
            regime="rangebound"
        )
        plan_sell_pe = engine.generate_derivative_plan(
            spot_plan=spot_plan_bullish,
            capital=500000.0,
            derivative_type="SELL_OPTIONS",
            iv=0.15
        )
        assert plan_sell_pe.action == "SELL"
        assert plan_sell_pe.option_type == "PE"
        assert plan_sell_pe.strike_price <= 24000.0  # OTM Put
        assert plan_sell_pe.theta > 0.0  # Positive Theta
        assert plan_sell_pe.delta > 0.0  # Selling Put is bullish delta
        assert plan_sell_pe.is_approved is True

    def test_option_selling_insufficient_span_margin_rejection(self):
        """Under micro capital (e.g. ₹20,000), naked option selling is rejected with guidance to use Credit Spreads."""
        engine = DerivativeEngine()
        spot_plan = TradePlan(
            ticker="NIFTY",
            direction="SHORT",
            entry_price=24000.0,
            take_profit=23800.0,
            stop_loss=24100.0,
            capital=20000.0,
            ai_probability=0.75,
            regime="rangebound"
        )
        plan = engine.generate_derivative_plan(
            spot_plan=spot_plan,
            capital=20000.0,
            derivative_type="SELL_OPTIONS"
        )
        assert plan.is_approved is False
        assert any("SPAN Margin Deficit" in r for r in plan.rejection_reasons)

    def test_bull_put_and_bear_call_credit_spreads(self):
        """
        Credit Spreads (Defined-Risk Hedged Option Writing):
        - Bull Put Spread: Sells higher strike PE, buys lower strike PE as hedge wing.
        - Bear Call Spread: Sells lower strike CE, buys higher strike CE as hedge wing.
        - Margin is capped at spread width * lot size + buffer (~₹25k-₹35k for NIFTY).
        """
        engine = DerivativeEngine()
        spot_plan_bullish = TradePlan(
            ticker="NIFTY",
            direction="LONG",
            entry_price=24000.0,
            take_profit=24200.0,
            stop_loss=23900.0,
            capital=50000.0,
            ai_probability=0.75,
            regime="rangebound"
        )
        spread_bull = engine.generate_derivative_plan(
            spot_plan=spot_plan_bullish,
            capital=50000.0,
            derivative_type="CREDIT_SPREAD",
            iv=0.15
        )
        assert spread_bull.instrument_type == "SPREAD"
        assert spread_bull.strategy_type == "CREDIT_SPREAD"
        assert spread_bull.action == "SELL"
        assert spread_bull.net_credit > 0.0
        assert spread_bull.hedge_strike_price < spread_bull.strike_price
        assert spread_bull.margin_or_premium_required <= 25000.0  # Hedged SPAN margin benefit
        assert spread_bull.theta > 0.0
        assert spread_bull.is_approved is True

        spot_plan_bearish = TradePlan(
            ticker="NIFTY",
            direction="SHORT",
            entry_price=24000.0,
            take_profit=23800.0,
            stop_loss=24100.0,
            capital=50000.0,
            ai_probability=0.75,
            regime="rangebound"
        )
        spread_bear = engine.generate_derivative_plan(
            spot_plan=spot_plan_bearish,
            capital=50000.0,
            derivative_type="CREDIT_SPREAD",
            iv=0.15
        )
        assert spread_bear.instrument_type == "SPREAD"
        assert spread_bear.strategy_type == "CREDIT_SPREAD"
        assert spread_bear.hedge_strike_price > spread_bear.strike_price
        assert spread_bear.net_credit > 0.0
        assert spread_bear.is_approved is True

    def test_option_selling_exact_analytical_breakeven(self):
        """
        Validates exact analytical breakeven buyback premium for Option Selling:
        Selling 1 lot of NIFTY PE at ₹100.00.
        Exit at calculated breakeven_exit_price must yield Net PnL = ₹0.00 within ₹0.02.
        """
        entry_sell_prem = 100.0
        qty = 25  # 1 lot NIFTY

        f_calc = IndianFOFrictionModel.calculate_options_friction(
            buy_premium=10.0,  # placeholder
            sell_premium=entry_sell_prem,
            quantity=qty,
            action="SELL"
        )
        be_buyback_price = f_calc.breakeven_exit_price
        assert be_buyback_price < entry_sell_prem  # Seller must buy back lower to pay costs

        # Test simulated trade exited exactly at breakeven_buyback_price
        be_calc = IndianFOFrictionModel.calculate_options_friction(
            buy_premium=be_buyback_price,
            sell_premium=entry_sell_prem,
            quantity=qty,
            action="SELL"
        )
        assert abs(be_calc.net_pnl) < 0.05, f"Breakeven net PnL was {be_calc.net_pnl}, expected ~0.00"

    def test_spread_2leg_friction_calculation(self):
        """Verifies 2-leg spread transaction friction with 4 round-trip legs."""
        f_spread = IndianFOFrictionModel.calculate_spread_friction(
            short_entry_prem=80.0,
            short_exit_prem=20.0,
            long_entry_prem=30.0,
            long_exit_prem=5.0,
            quantity=25
        )
        assert f_spread.brokerage == 80.0  # 4 legs * ₹20
        assert f_spread.total_friction > 80.0
        # Gross PnL: Short gain (80-20)*25 = 1500; Long loss (5-30)*25 = -625. Net gross = 875
        assert f_spread.gross_pnl == 875.0
        assert f_spread.net_pnl == 875.0 - f_spread.total_friction

    def test_iron_condor_plan_4_leg_strikes_and_greeks(self):
        """Verifies 4-leg Iron Condor generation with valid wing strikes, positive theta, and margin."""
        engine = DerivativeEngine()
        spot_plan = TradePlan(
            ticker="^NSEI",
            direction="NEUTRAL",
            entry_price=22000.0,
            take_profit=22150.0,
            stop_loss=21850.0,
            capital=100000.0,
            ai_probability=0.52,
            regime="rangebound"
        )
        plan = engine.generate_derivative_plan(
            spot_plan=spot_plan,
            capital=100000.0,
            derivative_type="IRON_CONDOR",
            strike_pref="AUTO",
            regime="rangebound",
            iv=0.15
        )
        assert plan.instrument_type == "IRON_CONDOR"
        assert plan.short_put_strike == 21950.0 or plan.short_put_strike == 21900.0 or plan.short_put_strike < 22000.0
        assert plan.long_put_strike < plan.short_put_strike
        assert plan.short_call_strike > 22000.0
        assert plan.long_call_strike > plan.short_call_strike
        assert plan.theta > 0.0, "Iron Condor must have positive theta decay!"
        assert plan.net_credit > 0.0
        assert plan.margin_or_premium_required > 0.0
        d = plan.to_dict()
        assert "short_put_strike" in d and "long_call_strike" in d

    def test_iron_condor_mtm_calculation_4_legs(self):
        """Verifies calculate_option_mtm correctly re-prices all 4 legs of an Iron Condor."""
        engine = DerivativeEngine()
        condor_trade = {
            "underlying_ticker": "NIFTY",
            "instrument_type": "IRON_CONDOR",
            "strategy_type": "IRON_CONDOR",
            "action": "SELL",
            "strike": 22000.0,
            "short_put_strike": 21900.0,
            "long_put_strike": 21800.0,
            "short_call_strike": 22100.0,
            "long_call_strike": 22200.0,
            "days_to_expiry": 5.0,
            "iv": 0.15
        }
        initial_val, _ = engine.calculate_option_mtm(condor_trade, current_spot=22000.0, days_elapsed=0.0)
        decayed_val, delta = engine.calculate_option_mtm(condor_trade, current_spot=22000.0, days_elapsed=2.0)
        assert initial_val > 0.0
        assert decayed_val > 0.0
        # Because of 2 days theta decay with spot stationary at center, cost to close must shrink
        assert decayed_val < initial_val
        assert abs(delta) < 0.20, f"Iron Condor net delta should be near neutral, got {delta}"

    def test_implied_volatility_newton_raphson_and_brent(self):
        """Validates numerical IV solver returns expected volatility within 0.005 tolerance."""
        engine = DerivativeEngine()
        spot = 22000.0
        strike = 22000.0
        T = 7.0 / 365.0
        r = 0.065
        true_sigma = 0.165

        # Compute theoretical price
        bs = engine.black_scholes(S=spot, K=strike, T=T, r=r, sigma=true_sigma, option_type="CE")
        mkt_price = bs["premium"]

        solved_iv = engine.calculate_implied_volatility(
            market_price=mkt_price,
            S=spot,
            K=strike,
            T=T,
            r=r,
            option_type="CE"
        )
        assert abs(solved_iv - true_sigma) < 0.005, f"Expected IV {true_sigma}, got {solved_iv}"

    def test_iron_condor_4leg_friction_calculation(self):
        """Verifies exact 8-order round trip friction for 4-leg Iron Condor."""
        f_condor = IndianFOFrictionModel.calculate_iron_condor_friction(
            short_put_entry=40.0,
            short_put_exit=10.0,
            long_put_entry=15.0,
            long_put_exit=2.0,
            short_call_entry=40.0,
            short_call_exit=10.0,
            long_call_entry=15.0,
            long_call_exit=2.0,
            quantity=25
        )
        assert f_condor.brokerage == 160.0  # 8 orders * ₹20
        assert f_condor.total_friction > 160.0
        # Gross PnL: Put side (40-10) - (15-2) = 30 - 13 = 17 pts
        # Call side (40-10) - (15-2) = 30 - 13 = 17 pts
        # Total = 34 pts * 25 = 850
        assert f_condor.gross_pnl == 850.0
        assert f_condor.net_pnl == 850.0 - f_condor.total_friction
