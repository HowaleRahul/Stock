"""
Exhaustive Unit & Integration Tests for Momentum Masters Swing Toolkit.

Tests:
1. Momentum Scanner (RVol surge, 20d pivot breakout / coiling)
2. DWIB Scanner (Weekly inside bar + Daily range contraction)
3. ATH Scanner (Near ATH / 52W high, contracting along 10 & 20 EMAs)
4. 8-Factor Quality Filter Checklist & Scoring Engine
5. 15-Minute ORB Breakout Engine & Early 5m/15m Volume Gates
6. MomentumMastersSetup BaseSetup contract compliance
7. Swing Toolkit API endpoints (Universe, Watchlist, Add/Delete)
"""

import pytest
import numpy as np
import pandas as pd
from starlette.testclient import TestClient

from setups.swing_toolkit.scanners import (
    MomentumScanner,
    DWIBScanner,
    ATHScanner,
    SwingScannerSuite,
)
from setups.swing_toolkit.checklist import SwingFilterChecklist
from setups.swing_toolkit.orb_entry import ORBBreakoutEngine
from setups.swing_toolkit_setup import MomentumMastersSetup
from setups.base import SetupSignal
from api.main import app


def _generate_synthetic_ohlcv(
    bars: int = 100,
    base_price: float = 1000.0,
    trend: float = 2.0,
    vol_base: float = 100000.0,
) -> pd.DataFrame:
    """Generates deterministic synthetic OHLCV bars."""
    dates = pd.date_range("2026-01-01", periods=bars, freq="B")
    prices = [base_price]
    for i in range(1, bars):
        step = trend + (np.sin(i / 5.0) * 1.5)
        prices.append(prices[-1] + step)

    prices = np.array(prices)
    highs = prices + 5.0
    lows = prices - 5.0
    opens = prices - 1.0
    closes = prices + 1.0
    volumes = np.full(bars, vol_base)

    df = pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    }, index=dates)
    return df


def test_momentum_scanner_breakout():
    """Test momentum scanner triggers when breaking out with above-average RVol."""
    df = _generate_synthetic_ohlcv(bars=80, trend=2.5, vol_base=100000)
    # Make the last bar an explosive breakout with 2.5x volume
    df.iloc[-1, df.columns.get_loc("close")] = df["high"].iloc[:-1].max() + 10.0
    df.iloc[-1, df.columns.get_loc("high")] = df["close"].iloc[-1] + 2.0
    df.iloc[-1, df.columns.get_loc("volume")] = 250000.0  # 2.5x RVol

    scanner = MomentumScanner()
    res = scanner.scan(df, ticker="TEST_MOMENTUM")

    assert res.matched is True
    assert res.confidence >= 0.70
    assert res.metrics["rvol"] >= 2.0
    assert "Broken Out" in res.metrics["status"]


def test_momentum_scanner_rejects_low_volume():
    """Test momentum scanner rejects breakout when volume is dry (no institutional confirmation)."""
    df = _generate_synthetic_ohlcv(bars=80, trend=2.0, vol_base=100000)
    # Breakout price, but low volume
    df.iloc[-1, df.columns.get_loc("close")] = df["high"].iloc[:-1].max() + 5.0
    df.iloc[-1, df.columns.get_loc("volume")] = 30000.0  # Low 0.3x RVol

    scanner = MomentumScanner()
    res = scanner.scan(df, ticker="TEST_LOW_VOL")

    assert res.matched is False


def test_dwib_scanner_weekly_inside_bar_and_contraction():
    """Test DWIB scanner matches weekly inside bar with daily compression."""
    df = _generate_synthetic_ohlcv(bars=120, trend=1.0, vol_base=100000)
    # Create weekly inside bar: contain last 5 days within previous 5 days range
    prev_w_high = df["high"].iloc[-10:-5].max()
    prev_w_low = df["low"].iloc[-10:-5].min()

    # Set last 5 days inside prev week range
    for i in range(-5, 0):
        df.iloc[i, df.columns.get_loc("high")] = prev_w_high - 1.0
        df.iloc[i, df.columns.get_loc("low")] = prev_w_low + 1.0
        df.iloc[i, df.columns.get_loc("close")] = (prev_w_high + prev_w_low) / 2.0

    # Ensure last bar has daily contraction (tight range)
    df.iloc[-1, df.columns.get_loc("high")] = df["close"].iloc[-1] + 0.5
    df.iloc[-1, df.columns.get_loc("low")] = df["close"].iloc[-1] - 0.5

    scanner = DWIBScanner()
    res = scanner.scan(df, ticker="TEST_DWIB")

    assert res.metrics["weekly_inside_bar"] is True
    assert res.metrics["daily_range_contraction"] is True or res.metrics["daily_inside_bar"] is True
    assert res.matched is True


def test_ath_scanner_contraction():
    """Test ATH scanner matches when price is within 2% of ATH hugging 10/20 EMAs."""
    df = _generate_synthetic_ohlcv(bars=260, trend=3.0, vol_base=100000)
    ath = df["high"].max()

    # Price right at 0.5% below ATH, tight close to 10 EMA
    df.iloc[-1, df.columns.get_loc("close")] = ath - 2.0
    df.iloc[-1, df.columns.get_loc("high")] = ath - 1.0
    df.iloc[-1, df.columns.get_loc("low")] = ath - 5.0
    df.iloc[-1, df.columns.get_loc("volume")] = 80000.0  # Volume dry-up

    scanner = ATHScanner()
    res = scanner.scan(df, ticker="TEST_ATH")

    assert res.matched is True
    assert res.metrics["dist_to_ath_pct"] <= 3.5
    assert res.metrics["volume_dry_up"] is True


def test_8_factor_checklist_strong_candidate():
    """Test 8-factor checklist approves strong Stage 2 candidate with high score."""
    df = _generate_synthetic_ohlcv(bars=220, trend=3.0, vol_base=150000)
    # Add VCP consolidation: tight range and volume dry-up on right side
    df.iloc[-5:, df.columns.get_loc("high")] = df["close"].iloc[-5:] + 1.0
    df.iloc[-5:, df.columns.get_loc("low")] = df["close"].iloc[-5:] - 1.0
    df.iloc[-3:, df.columns.get_loc("volume")] = 90000.0  # Volume dry-up

    # Benchmark with lower return to guarantee outperformance
    bm_df = _generate_synthetic_ohlcv(bars=220, trend=0.5, vol_base=500000)

    checklist = SwingFilterChecklist()
    res = checklist.evaluate(df, ticker="HAL", benchmark_df=bm_df)

    assert res.qualifies_for_watchlist is True
    assert res.composite_score >= 70.0
    assert res.passed_count >= 6
    assert "liquidity" in res.checklist_items
    assert "stage_2" in res.checklist_items
    assert res.checklist_items["stage_2"].passed is True


def test_8_factor_checklist_rejects_penny_or_downtrend():
    """Test checklist rejects penny stocks and downtrending charts."""
    df = _generate_synthetic_ohlcv(bars=100, trend=-2.0, base_price=15.0, vol_base=5000)

    checklist = SwingFilterChecklist()
    res = checklist.evaluate(df, ticker="PENNY_STOCK")

    assert res.qualifies_for_watchlist is False
    assert res.composite_score < 70.0
    assert res.checklist_items["fundamentals"].passed is False


def test_orb_breakout_engine_volume_gates_and_trigger():
    """Test 15m ORB triggers when price breaks above ORB High with volume gates passed."""
    daily_df = _generate_synthetic_ohlcv(bars=30, vol_base=1000000)  # ADV = 1,000,000

    # Intraday 5m bars for current day
    # Bar 0: First 5m -> volume = 85,000 (8.5% of ADV, passes >= 7% gate)
    # Bar 1: Second 5m -> volume = 60,000
    # Bar 2: Third 5m -> volume = 50,000 (15m total = 195,000 = 19.5% of ADV, passes >= 17% gate)
    # Bar 3: Fourth 5m -> breaks above 15m high!
    times = pd.date_range("2026-10-21 09:15", periods=5, freq="5min")
    intraday_df = pd.DataFrame({
        "open": [1000.0, 1002.0, 1001.0, 1006.0, 1008.0],
        "high": [1005.0, 1004.0, 1003.0, 1010.0, 1012.0],  # 15m ORB High = 1005.0
        "low": [995.0, 998.0, 997.0, 1004.0, 1006.0],       # 15m ORB Low = 995.0
        "close": [1002.0, 1001.0, 1003.0, 1008.0, 1011.0],  # Bar 3 close 1008 > 1005
        "volume": [85000.0, 60000.0, 50000.0, 70000.0, 60000.0],
    }, index=times)

    engine = ORBBreakoutEngine()
    plan = engine.evaluate_entry(
        intraday_5m_df=intraday_df,
        daily_df=daily_df,
        ticker="TRENT",
        capital=1000000.0,
        risk_per_trade_pct=0.015,
    )

    assert plan.gate_5m_passed is True
    assert plan.gate_15m_passed is True
    assert plan.volume_gate_confirmed is True
    assert plan.orb_high == 1005.0
    assert plan.orb_low == 995.0
    assert plan.is_triggered is True
    assert plan.entry_price >= 1005.0
    assert plan.stop_loss <= 995.0
    assert plan.target_2r > plan.entry_price
    assert plan.position_size > 0


def test_orb_breakout_rejects_without_volume():
    """Test 15m ORB rejects breakout if early volume gate fails (prevents bull traps)."""
    daily_df = _generate_synthetic_ohlcv(bars=30, vol_base=1000000)  # ADV = 1,000,000

    # Low volume intraday
    times = pd.date_range("2026-10-21 09:15", periods=5, freq="5min")
    intraday_df = pd.DataFrame({
        "open": [1000.0, 1002.0, 1001.0, 1006.0, 1008.0],
        "high": [1005.0, 1004.0, 1003.0, 1010.0, 1012.0],
        "low": [995.0, 998.0, 997.0, 1004.0, 1006.0],
        "close": [1002.0, 1001.0, 1003.0, 1008.0, 1011.0],
        "volume": [10000.0, 10000.0, 10000.0, 15000.0, 12000.0],  # 5m = 1%, 15m = 3%
    }, index=times)

    engine = ORBBreakoutEngine()
    plan = engine.evaluate_entry(
        intraday_5m_df=intraday_df,
        daily_df=daily_df,
        ticker="TRAP_STOCK",
    )

    assert plan.volume_gate_confirmed is False
    assert plan.is_triggered is False
    assert "rejected by Volume Gate" in plan.reasoning


def test_momentum_masters_setup_base_setup_contract():
    """Test MomentumMastersSetup properly implements BaseSetup interface."""
    setup = MomentumMastersSetup()
    assert setup.name == "Momentum Masters Swing"

    df = _generate_synthetic_ohlcv(bars=80, trend=2.0)
    sig = setup.evaluate(df, ticker="TEST_TICKER")

    assert isinstance(sig, SetupSignal)
    assert sig.signal in ("bullish", "bearish", "neutral")
    assert 0.0 <= sig.confidence <= 1.0


def test_swing_api_endpoints():
    """Test /api/v1/swing endpoints with TestClient."""
    client = TestClient(app)

    # 1. Universe
    res_uni = client.get("/api/v1/swing/universe", headers={"X-API-KEY": "trading_secret_key"})
    assert res_uni.status_code == 200
    data = res_uni.json()
    assert data["count"] > 0
    assert any(item["ticker"] == "HAL" for item in data["universe"])

    # 2. Watchlist GET
    res_wl = client.get("/api/v1/swing/watchlist", headers={"X-API-KEY": "trading_secret_key"})
    assert res_wl.status_code == 200
    wl_data = res_wl.json()
    assert "watchlist" in wl_data

    # 3. Add to Watchlist
    payload = {
        "ticker": "TEST_AUTO",
        "sector": "Auto",
        "source_scanners": ["Momentum"],
        "composite_score": 85.0,
        "vcp_detected": True,
        "stage_2": True,
        "notes": "Automated test addition",
    }
    res_add = client.post("/api/v1/swing/watchlist", json=payload, headers={"X-API-KEY": "trading_secret_key"})
    assert res_add.status_code == 200
    assert res_add.json()["success"] is True

    # 4. Delete from Watchlist
    res_del = client.delete("/api/v1/swing/watchlist/TEST_AUTO", headers={"X-API-KEY": "trading_secret_key"})
    assert res_del.status_code == 200
    assert res_del.json()["success"] is True


@pytest.mark.asyncio
async def test_yfinance_fetcher_fetch_history_and_caching(monkeypatch):
    """Test YFinanceFetcher.fetch_history returns lowercase standardized DataFrame and uses cache."""
    from data.fetcher import YFinanceFetcher, _HISTORY_CACHE, _CACHE_LOCK

    synthetic_df = _generate_synthetic_ohlcv(bars=60)
    # Give it yfinance title case columns
    synthetic_df.columns = ["Open", "High", "Low", "Close", "Volume"]

    with _CACHE_LOCK:
        _HISTORY_CACHE.clear()

    monkeypatch.setattr(YFinanceFetcher, "_fetch_history_sync", lambda *args, **kwargs: synthetic_df.copy())

    df = await YFinanceFetcher.fetch_history("TESTSYM", period="1y", interval="1d")
    assert not df.empty
    assert "close" in df.columns
    assert "open" in df.columns
    assert "high" in df.columns
    assert "low" in df.columns
    assert "volume" in df.columns
    assert "Close" not in df.columns  # Ensured normalized to lowercase


@pytest.mark.asyncio
async def test_yfinance_fetcher_direct_v8_fallback(monkeypatch):
    """Test YFinanceFetcher._fetch_history_sync seamlessly falls back to direct v8 chart when yfinance fails."""
    from data.fetcher import YFinanceFetcher, _HISTORY_CACHE, _CACHE_LOCK

    synthetic_df = _generate_synthetic_ohlcv(bars=55)
    synthetic_df.columns = ["Open", "High", "Low", "Close", "Volume"]

    with _CACHE_LOCK:
        _HISTORY_CACHE.clear()

    # Mock yfinance to fail / rate limit
    class FailingTicker:
        def history(self, *args, **kwargs):
            raise Exception("Too Many Requests. Rate limited.")

    monkeypatch.setattr("data.fetcher.yf.Ticker", lambda sym: FailingTicker())
    monkeypatch.setattr(YFinanceFetcher, "_fetch_chart_direct_sync", lambda *args, **kwargs: synthetic_df.copy())

    df = YFinanceFetcher._fetch_history_sync("TEST_FAILOVER", period="1y", interval="1d")
    assert not df.empty
    assert len(df) == 55


@pytest.mark.asyncio
async def test_swing_toolkit_run_scanners_and_filter_pipeline(monkeypatch):
    """Test SwingToolkitManager.run_scanners_and_filter executes end-to-end without AttributeError."""
    from setups.swing_toolkit.toolkit import SwingToolkitManager
    from data.fetcher import YFinanceFetcher

    # Generate synthetic breakout data
    df_breakout = _generate_synthetic_ohlcv(bars=80, trend=2.5, vol_base=100000)
    df_breakout.iloc[-1, df_breakout.columns.get_loc("close")] = df_breakout["high"].iloc[:-1].max() + 10.0
    df_breakout.iloc[-1, df_breakout.columns.get_loc("high")] = df_breakout["close"].iloc[-1] + 2.0
    df_breakout.iloc[-1, df_breakout.columns.get_loc("volume")] = 300000.0
    df_breakout.columns = [c.lower() for c in df_breakout.columns]

    async def mock_fetch_history(ticker, period="1y", interval="1d", **kwargs):
        return df_breakout.copy()

    monkeypatch.setattr(YFinanceFetcher, "fetch_history", mock_fetch_history)

    mgr = SwingToolkitManager()
    res = await mgr.run_scanners_and_filter(universe=["TEST_HAL", "TEST_TRENT"])

    assert res["total_universe_scanned"] == 2
    assert res["total_scanner_hits"] == 2
    assert len(res["candidates"]) == 2
    for cand in res["candidates"]:
        assert cand["ticker"] in ("TEST_HAL", "TEST_TRENT")
        assert len(cand["matched_scanners"]) > 0
        assert cand["composite_score"] > 0.0
        assert "checklist" in cand
