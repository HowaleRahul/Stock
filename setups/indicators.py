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

def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    if period < 1 or len(series) < period:
        return pd.Series(np.nan, index=series.index)
    # Keep the implementation deterministic across pandas-ta versions and do
    # not calculate an average until a complete window is available.
    return series.astype(float).rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int, *, wilder: bool = False) -> pd.Series:
    """Exponential Moving Average."""
    if period < 1 or len(series) < period or series.isna().all():
        return pd.Series(np.nan, index=series.index)
    values = pd.to_numeric(series, errors="coerce").astype(float)
    result = pd.Series(np.nan, index=series.index, dtype=float)
    alpha = (1.0 / period) if wilder else (2.0 / (period + 1.0))
    previous: float | None = None
    valid_run: list[float] = []

    # Seed from the first complete contiguous window.  Thereafter a missing
    # source value carries the prior EMA forward instead of poisoning every
    # later point with NaN.
    for index, value in values.items():
        if pd.isna(value):
            if previous is not None:
                result.loc[index] = previous
            continue
        valid_run.append(float(value))
        if previous is None:
            if len(valid_run) < period:
                continue
            previous = float(np.mean(valid_run[-period:]))
        else:
            previous = (float(value) * alpha) + (previous * (1.0 - alpha))
        result.loc[index] = previous
    return result


# ---------------------------------------------------------------------------
# Relative Strength Index
# ---------------------------------------------------------------------------

def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index."""
    if period < 1 or len(close) < period + 1 or close.isna().all():
        return pd.Series(np.nan, index=close.index)
    values = pd.to_numeric(close, errors="coerce").astype(float)
    delta = values.diff()
    gains = delta.clip(lower=0.0)
    losses = -delta.clip(upper=0.0)
    avg_gain = ema(gains, period, wilder=True)
    avg_loss = ema(losses, period, wilder=True)
    result = pd.Series(np.nan, index=close.index, dtype=float)
    valid = avg_gain.notna() & avg_loss.notna()
    both_zero = valid & (avg_gain == 0) & (avg_loss == 0)
    no_loss = valid & (avg_loss == 0) & ~both_zero
    normal = valid & ~both_zero & ~no_loss
    result.loc[both_zero] = 50.0
    result.loc[no_loss] = 100.0
    result.loc[normal] = 100.0 - (100.0 / (1.0 + (avg_gain.loc[normal] / avg_loss.loc[normal])))
    return result


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
        
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal_period)
    histogram = macd_line - signal_line
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
        
    values = pd.to_numeric(close, errors="coerce").astype(float)
    middle = values.rolling(window=period, min_periods=period).mean()
    # Population standard deviation is the conventional Bollinger definition.
    deviation = values.rolling(window=period, min_periods=period).std(ddof=0)
    upper = middle + (std_dev * deviation)
    lower = middle - (std_dev * deviation)
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
