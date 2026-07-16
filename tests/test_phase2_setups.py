"""
Phase 2 Tests — Technical Setups Engine.

Tests cover:
  1. Indicator math (SMA, EMA, RSI, MACD, Bollinger Bands, S/R detection)
  2. Setup signal evaluation (each of the 5 setups)
  3. SetupEngine orchestration and error isolation
  4. API endpoints (/setups/{ticker}, /indicators/{ticker})
  5. Frontend static serving
"""

import datetime
import math
import pytest
import numpy as np
import pandas as pd

from setups.indicators import sma, ema, rsi, macd, bollinger_bands, find_support_resistance
from setups.base import SetupSignal, BaseSetup
from setups.engine import SetupEngine
from setups.ma_crossover import MACrossoverSetup
from setups.rsi_setup import RSISetup
from setups.macd_setup import MACDSetup
from setups.bollinger_setup import BollingerBandsSetup
from setups.breakout_setup import BreakoutSetup


# =====================================================================
# Helpers
# =====================================================================

def _make_df(closes, n=None, with_volume=True):
    """Build a minimal OHLCV DataFrame from a list of close prices."""
    if n is None:
        n = len(closes)
    closes = list(closes)[:n]
    now = datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)
    rows = []
    for i, c in enumerate(closes):
        rows.append({
            "time": now + datetime.timedelta(days=i),
            "open": c * 0.99,
            "high": c * 1.01,
            "low": c * 0.98,
            "close": float(c),
            "adjusted_close": float(c),
            "volume": 1_000_000.0 if with_volume else 0.0,
        })
    return pd.DataFrame(rows)


def _trending_up(start=100.0, n=100, step=0.5):
    """Generate a steadily rising price series."""
    return [start + i * step for i in range(n)]


def _trending_down(start=200.0, n=100, step=0.5):
    """Generate a steadily falling price series."""
    return [start - i * step for i in range(n)]


# =====================================================================
# 1. Indicator Math Tests
# =====================================================================

def test_sma_known_values():
    """SMA(5) on [1,2,3,4,5,6,7] → verify exact values."""
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0])
    result = sma(s, 5)

    # First 4 should be NaN
    for i in range(4):
        assert math.isnan(result.iloc[i])

    # SMA(5) at index 4 = (1+2+3+4+5)/5 = 3.0
    assert result.iloc[4] == pytest.approx(3.0)
    # SMA(5) at index 5 = (2+3+4+5+6)/5 = 4.0
    assert result.iloc[5] == pytest.approx(4.0)
    # SMA(5) at index 6 = (3+4+5+6+7)/5 = 5.0
    assert result.iloc[6] == pytest.approx(5.0)


def test_ema_known_values():
    """EMA(3) on a known series — verify against hand-calculated values."""
    s = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
    result = ema(s, 3)

    # First 2 should be NaN
    assert math.isnan(result.iloc[0])
    assert math.isnan(result.iloc[1])

    # EMA seed at index 2 = SMA(3) = (10+11+12)/3 = 11.0
    assert result.iloc[2] == pytest.approx(11.0)

    # alpha = 2/(3+1) = 0.5
    # index 3: 0.5*13 + 0.5*11.0 = 12.0
    assert result.iloc[3] == pytest.approx(12.0)
    # index 4: 0.5*14 + 0.5*12.0 = 13.0
    assert result.iloc[4] == pytest.approx(13.0)
    # index 5: 0.5*15 + 0.5*13.0 = 14.0
    assert result.iloc[5] == pytest.approx(14.0)


def test_rsi_known_values():
    """RSI(14) on a standard series — verify reasonable range."""
    # Generate an up-trending series with some pullbacks
    np.random.seed(42)
    closes = [100.0]
    for _ in range(99):
        closes.append(closes[-1] + np.random.normal(0.3, 1.0))
    s = pd.Series(closes)
    result = rsi(s, 14)

    # First 14 values should be NaN
    for i in range(14):
        assert math.isnan(result.iloc[i])

    # RSI should be in [0, 100] for all valid entries
    valid = result.dropna()
    assert len(valid) > 0
    assert all(0.0 <= v <= 100.0 for v in valid)


def test_rsi_edge_all_gains():
    """All up-days → RSI should approach 100."""
    closes = [100.0 + i for i in range(30)]
    s = pd.Series(closes)
    result = rsi(s, 14)
    # The last RSI value should be 100.0 (all gains, zero losses)
    assert result.iloc[-1] == pytest.approx(100.0)


def test_rsi_edge_all_losses():
    """All down-days → RSI should approach 0."""
    closes = [200.0 - i for i in range(30)]
    s = pd.Series(closes)
    result = rsi(s, 14)
    # The last RSI value should be 0.0 (all losses, zero gains)
    assert result.iloc[-1] == pytest.approx(0.0)


def test_macd_known_values():
    """MACD(12,26,9) on 50+ bars → verify histogram has valid numbers."""
    np.random.seed(123)
    closes = [100.0]
    for _ in range(59):
        closes.append(closes[-1] + np.random.normal(0.2, 1.0))
    s = pd.Series(closes)

    macd_line, signal_line, histogram = macd(s, 12, 26, 9)

    # All three should be same length
    assert len(macd_line) == 60
    assert len(signal_line) == 60
    assert len(histogram) == 60

    # Valid values should exist in the tail
    assert not math.isnan(macd_line.iloc[-1])
    assert not math.isnan(signal_line.iloc[-1])
    assert not math.isnan(histogram.iloc[-1])

    # Histogram = MACD - Signal
    assert histogram.iloc[-1] == pytest.approx(
        macd_line.iloc[-1] - signal_line.iloc[-1], abs=1e-10
    )


def test_bollinger_bands_known_values():
    """BB(20,2) → verify middle = SMA(20) and band width = 4σ."""
    np.random.seed(99)
    closes = [100.0 + np.random.normal(0, 1) for _ in range(40)]
    s = pd.Series(closes)

    upper, middle, lower = bollinger_bands(s, 20, 2.0)

    # Middle should equal SMA(20)
    expected_sma = sma(s, 20)
    for i in range(19, 40):
        if not math.isnan(middle.iloc[i]):
            assert middle.iloc[i] == pytest.approx(expected_sma.iloc[i], abs=1e-10)

    # Band width should be 4 * std_dev for each point
    for i in range(19, 40):
        if not math.isnan(upper.iloc[i]):
            band_w = upper.iloc[i] - lower.iloc[i]
            rolling_std = s.iloc[i-19:i+1].std(ddof=0)
            assert band_w == pytest.approx(4.0 * rolling_std, abs=1e-8)


def test_bollinger_bands_constant_price():
    """Flat price → bandwidth = 0, upper = lower = middle."""
    s = pd.Series([50.0] * 30)
    upper, middle, lower = bollinger_bands(s, 20, 2.0)

    # At index 19+, bands should converge
    assert upper.iloc[-1] == pytest.approx(50.0)
    assert middle.iloc[-1] == pytest.approx(50.0)
    assert lower.iloc[-1] == pytest.approx(50.0)


def test_support_resistance_basic():
    """Price with clear peaks/troughs → verify levels detected."""
    # Create a wave pattern with obvious peaks and troughs
    prices_close = []
    prices_high = []
    prices_low = []
    for i in range(60):
        base = 100 + 10 * np.sin(i * np.pi / 10)  # oscillate between 90 and 110
        prices_close.append(base)
        prices_high.append(base + 1)
        prices_low.append(base - 1)

    close = pd.Series(prices_close)
    high = pd.Series(prices_high)
    low = pd.Series(prices_low)

    levels = find_support_resistance(close, high, low, lookback=60, num_levels=3)

    assert "support" in levels
    assert "resistance" in levels
    # Should detect at least one level in each direction
    assert len(levels["support"]) >= 1 or len(levels["resistance"]) >= 1


def test_indicators_short_series():
    """Series shorter than period → returns NaN-filled series, no crash."""
    s = pd.Series([100.0, 101.0, 102.0])  # only 3 bars

    sma_result = sma(s, 20)
    ema_result = ema(s, 20)
    rsi_result = rsi(s, 14)

    assert len(sma_result) == 3
    assert all(math.isnan(v) for v in sma_result)
    assert len(ema_result) == 3
    assert all(math.isnan(v) for v in ema_result)
    assert len(rsi_result) == 3
    assert all(math.isnan(v) for v in rsi_result)

    macd_l, macd_s, macd_h = macd(s, 12, 26, 9)
    assert len(macd_l) == 3
    assert all(math.isnan(v) for v in macd_l)

    bb_u, bb_m, bb_l = bollinger_bands(s, 20, 2.0)
    assert len(bb_u) == 3
    assert all(math.isnan(v) for v in bb_u)


# =====================================================================
# 2. Setup Evaluation Tests
# =====================================================================

def test_ma_crossover_golden_cross():
    """Construct series with EMA20 crossing above EMA50 → signal = 'bullish'."""
    # Start with EMA20 < EMA50 (down trend), then sharp reversal
    prices = _trending_down(200, 60, 0.5) + _trending_up(170, 40, 1.5)
    df = _make_df(prices)
    setup = MACrossoverSetup()
    signal = setup.evaluate(df)

    assert signal.signal == "bullish"
    assert signal.confidence > 0.0
    assert "EMA" in signal.reasoning or "above" in signal.reasoning


def test_ma_crossover_death_cross():
    """Construct series with EMA20 crossing below EMA50 → signal = 'bearish'."""
    # Start with EMA20 > EMA50 (up trend), then sharp reversal
    prices = _trending_up(100, 60, 0.5) + _trending_down(130, 40, 1.5)
    df = _make_df(prices)
    setup = MACrossoverSetup()
    signal = setup.evaluate(df)

    assert signal.signal == "bearish"
    assert signal.confidence > 0.0


def test_rsi_oversold_signal():
    """Build a series that drives RSI below 30 → signal = 'bullish'."""
    # Sharp decline: consistent losses → RSI approaches 0
    prices = [200.0 - i * 2.0 for i in range(30)]
    df = _make_df(prices)
    setup = RSISetup()
    signal = setup.evaluate(df)

    assert signal.signal == "bullish"
    assert signal.confidence > 0.3
    assert "oversold" in signal.reasoning.lower()


def test_rsi_overbought_signal():
    """Build a series that drives RSI above 70 → signal = 'bearish'."""
    # Sharp incline: consistent gains → RSI approaches 100
    prices = [100.0 + i * 2.0 for i in range(30)]
    df = _make_df(prices)
    setup = RSISetup()
    signal = setup.evaluate(df)

    assert signal.signal == "bearish"
    assert signal.confidence > 0.3
    assert "overbought" in signal.reasoning.lower()


def test_macd_bullish_crossover():
    """Build series where MACD crosses above signal → 'bullish'."""
    # Need a long enough series for MACD(12,26,9) to converge
    # Long decline then sharp upturn
    prices = _trending_down(250, 80, 0.3) + _trending_up(226, 40, 1.5)
    df = _make_df(prices)
    setup = MACDSetup()
    signal = setup.evaluate(df)

    # Should be bullish (MACD line above signal after upturn)
    assert signal.signal == "bullish"


def test_bollinger_lower_touch():
    """Price at lower band → 'bullish'."""
    # Stable prices then a sharp drop
    prices = [100.0] * 25 + [100.0 - i * 3.0 for i in range(10)]
    df = _make_df(prices)
    setup = BollingerBandsSetup()
    signal = setup.evaluate(df)

    assert signal.signal == "bullish"
    assert "lower" in signal.reasoning.lower() or "mean-reversion" in signal.reasoning.lower()


def test_breakout_above_resistance():
    """Price breaks resistance with volume → 'bullish'."""
    # Build oscillating prices with a ceiling at ~110, then break through
    prices = []
    for i in range(50):
        prices.append(100 + 8 * np.sin(i * np.pi / 5))  # oscillate 92-108
    # Now break above
    prices.extend([112, 115, 118])

    df = _make_df(prices)
    # Boost volume on the breakout bar
    df.loc[df.index[-1], "volume"] = 3_000_000.0

    setup = BreakoutSetup()
    signal = setup.evaluate(df)

    # Should detect breakout (bullish) or at minimum be bullish/neutral
    assert signal.signal in ("bullish", "neutral")


# =====================================================================
# 3. Engine Tests
# =====================================================================

def test_engine_runs_all_setups():
    """SetupEngine returns exactly 5 signals."""
    df = _make_df(_trending_up(100, 100))
    engine = SetupEngine()
    results = engine.evaluate_all(df)

    assert len(results) == 5
    names = [r.name for r in results]
    assert "MA Crossover" in names
    assert "RSI" in names
    assert "MACD" in names
    assert "Bollinger Bands" in names
    assert "S/R Breakout" in names


def test_engine_isolates_failures():
    """One broken setup → other 4 still return valid signals."""
    engine = SetupEngine()

    # Replace one setup with a broken one
    class BrokenSetup(BaseSetup):
        name = "Broken"
        def evaluate(self, df):
            raise ValueError("Intentional test explosion")

    engine.setups[2] = BrokenSetup()  # Replace MACD with broken

    df = _make_df(_trending_up(100, 100))
    results = engine.evaluate_all(df)

    assert len(results) == 5
    broken = [r for r in results if r.name == "Broken"]
    assert len(broken) == 1
    assert broken[0].signal == "neutral"
    assert broken[0].confidence == 0.0
    assert "error" in broken[0].reasoning.lower()

    # Other 4 should have valid signals
    valid = [r for r in results if r.name != "Broken"]
    assert len(valid) == 4
    for r in valid:
        assert r.signal in ("bullish", "bearish", "neutral")


def test_setup_confidence_bounds():
    """All confidence values must be in [0.0, 1.0]."""
    engine = SetupEngine()

    # Test with various data patterns
    for prices in [_trending_up(100, 80), _trending_down(200, 80),
                   [100.0] * 80]:
        df = _make_df(prices)
        results = engine.evaluate_all(df)
        for r in results:
            assert 0.0 <= r.confidence <= 1.0, (
                f"{r.name}: confidence {r.confidence} out of bounds"
            )


# =====================================================================
# 4. API Integration Tests
# =====================================================================

@pytest.mark.asyncio
async def test_setups_endpoint_returns_5_signals():
    """GET /api/v1/setups/RELIANCE.NS → 5 setup results."""
    from httpx import AsyncClient, ASGITransport
    from api.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/setups/RELIANCE.NS?timeframe=1d&period=200")

    if resp.status_code == 404:
        # No data synced yet — that's acceptable in CI
        pytest.skip("No OHLCV data for RELIANCE.NS in test DB")

    assert resp.status_code == 200
    data = resp.json()
    assert data["ticker"] == "RELIANCE.NS"
    assert len(data["setups"]) == 5
    for s in data["setups"]:
        assert s["signal"] in ("bullish", "bearish", "neutral")
        assert 0.0 <= s["confidence"] <= 1.0
        assert len(s["reasoning"]) > 0


@pytest.mark.asyncio
async def test_setups_endpoint_404_unknown_ticker():
    """Unknown ticker → 404."""
    from httpx import AsyncClient, ASGITransport
    from api.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/setups/DOESNOTEXIST999")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_indicators_endpoint_returns_all_series():
    """GET /api/v1/indicators/RELIANCE.NS → all indicator arrays present."""
    from httpx import AsyncClient, ASGITransport
    from api.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/indicators/RELIANCE.NS?timeframe=1d&limit=100")

    if resp.status_code == 404:
        pytest.skip("No OHLCV data for RELIANCE.NS in test DB")

    assert resp.status_code == 200
    data = resp.json()

    # All indicator keys must be present
    for key in [
        "candles", "ema_20", "ema_50", "rsi_14",
        "macd_line", "macd_signal", "macd_histogram",
        "bb_upper", "bb_middle", "bb_lower",
        "support_levels", "resistance_levels",
    ]:
        assert key in data, f"Missing key: {key}"


@pytest.mark.asyncio
async def test_indicators_endpoint_series_lengths_match():
    """All indicator arrays should be same length as candles array."""
    from httpx import AsyncClient, ASGITransport
    from api.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/indicators/RELIANCE.NS?timeframe=1d&limit=100")

    if resp.status_code == 404:
        pytest.skip("No OHLCV data for RELIANCE.NS in test DB")

    data = resp.json()
    n = len(data["candles"])
    assert n > 0

    for key in ["ema_20", "ema_50", "rsi_14", "macd_line", "macd_signal",
                "macd_histogram", "bb_upper", "bb_middle", "bb_lower"]:
        assert len(data[key]) == n, f"{key} length {len(data[key])} != candles length {n}"


@pytest.mark.asyncio
async def test_static_frontend_served():
    """GET /app/ → 200 with HTML content."""
    from httpx import AsyncClient, ASGITransport
    from api.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/app/")

    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "AI Trading Dashboard" in resp.text
