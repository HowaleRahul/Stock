"""
Pure math implementations of technical indicators.

Every function takes pandas Series / DataFrames and returns pandas Series.
No side-effects, no I/O — just math.  Each function handles edge cases
(series shorter than period, NaN propagation) gracefully.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Moving Averages
# ---------------------------------------------------------------------------

import pandas_ta as ta

def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    if period < 1 or len(series) < period:
        return pd.Series(np.nan, index=series.index)
    res = ta.sma(series, length=period)
    return res if res is not None else pd.Series(np.nan, index=series.index)


def ema(series: pd.Series, period: int, *, wilder: bool = False) -> pd.Series:
    """Exponential Moving Average."""
    if period < 1 or len(series) < period or series.isna().all():
        return pd.Series(np.nan, index=series.index)
    if wilder:
        res = ta.rma(series, length=period)
    else:
        res = ta.ema(series, length=period)
    return res if res is not None else pd.Series(np.nan, index=series.index)


# ---------------------------------------------------------------------------
# Relative Strength Index
# ---------------------------------------------------------------------------

def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index."""
    if period < 1 or len(close) < period + 1 or close.isna().all():
        return pd.Series(np.nan, index=close.index)
    res = ta.rsi(close, length=period)
    return res if res is not None else pd.Series(np.nan, index=close.index)


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------

def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Moving Average Convergence Divergence."""
    nan_s = pd.Series(np.nan, index=close.index)
    if len(close) < slow + signal_period:
        return nan_s.copy(), nan_s.copy(), nan_s.copy()
        
    df = ta.macd(close, fast=fast, slow=slow, signal=signal_period)
    if df is None or df.empty:
        return nan_s.copy(), nan_s.copy(), nan_s.copy()
        
    macd_line = df.iloc[:, 0]
    histogram = df.iloc[:, 1]
    signal_line = df.iloc[:, 2]
    return macd_line, signal_line, histogram


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------

def bollinger_bands(
    close: pd.Series,
    period: int = 20,
    std_dev: float = 2.0,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Bollinger Bands."""
    nan_s = pd.Series(np.nan, index=close.index)
    if period < 1 or len(close) < period:
        return nan_s.copy(), nan_s.copy(), nan_s.copy()
        
    df = ta.bbands(close, length=period, std=std_dev)
    if df is None or df.empty:
        return nan_s.copy(), nan_s.copy(), nan_s.copy()
        
    lower = df.iloc[:, 0]
    middle = df.iloc[:, 1]
    upper = df.iloc[:, 2]
    return upper, middle, lower


# ---------------------------------------------------------------------------
# Support / Resistance Detection
# ---------------------------------------------------------------------------

def find_support_resistance(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    lookback: int = 50,
    num_levels: int = 3,
    tolerance_pct: float = 0.5,
) -> Dict[str, List[float]]:
    """Find support and resistance levels using pivot highs/lows.

    Scans the most recent ``lookback`` bars for local pivot points, then
    clusters nearby levels (within ``tolerance_pct`` %) and ranks them by
    how many touches they received.

    Returns:
        ``{"support": [...], "resistance": [...]}`` — lists of price levels
        sorted by strength (most touches first), capped at ``num_levels``.
    """
    if len(close) < 5 or close.isna().all() or tolerance_pct < 0:
        return {"support": [], "resistance": []}

    # Work on the tail
    n = min(lookback, len(close))
    h = high.iloc[-n:].values.astype(float)
    l = low.iloc[-n:].values.astype(float)
    c = close.iloc[-n:].values.astype(float)
    current_price = float(c[-1])

    if np.isnan(current_price) or current_price <= 0:
        return {"support": [], "resistance": []}

    # Find local pivots (a pivot needs at least 2 bars on each side)
    pivot_highs: list[float] = []
    pivot_lows: list[float] = []

    for i in range(2, n - 2):
        if any(np.isnan([h[i], h[i-1], h[i-2], h[i+1], h[i+2], l[i], l[i-1], l[i-2], l[i+1], l[i+2]])):
            continue
        # Pivot high
        if h[i] >= h[i - 1] and h[i] >= h[i - 2] and h[i] >= h[i + 1] and h[i] >= h[i + 2]:
            pivot_highs.append(float(h[i]))
        # Pivot low
        if l[i] <= l[i - 1] and l[i] <= l[i - 2] and l[i] <= l[i + 1] and l[i] <= l[i + 2]:
            pivot_lows.append(float(l[i]))

    def cluster_levels(levels: list[float], max_count: int) -> list[float]:
        """Cluster nearby price levels and return the strongest."""
        clean_levels = [x for x in levels if not np.isnan(x)]
        if not clean_levels:
            return []
        levels_sorted = sorted(clean_levels)
        clusters: list[list[float]] = [[levels_sorted[0]]]
        tol = current_price * (tolerance_pct / 100.0)

        for lev in levels_sorted[1:]:
            if abs(lev - clusters[-1][-1]) <= tol:
                clusters[-1].append(lev)
            else:
                clusters.append([lev])

        # Sort clusters by number of touches (descending), take top N
        clusters.sort(key=len, reverse=True)
        result = [float(np.mean(cluster)) for cluster in clusters[:max_count]]
        return [r for r in result if not np.isnan(r) and not np.isinf(r)]

    # Support = pivot lows below current price; Resistance = pivot highs above
    support_candidates = [p for p in pivot_lows if p <= current_price]
    resistance_candidates = [p for p in pivot_highs if p >= current_price]

    return {
        "support": cluster_levels(support_candidates, num_levels),
        "resistance": cluster_levels(resistance_candidates, num_levels),
    }
