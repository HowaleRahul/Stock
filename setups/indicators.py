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
    """Simple Moving Average.

    Returns a Series of the same length with NaN for the first (period - 1)
    entries.
    """
    if period < 1 or len(series) < period:
        return pd.Series(np.nan, index=series.index)
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int, *, wilder: bool = False) -> pd.Series:
    """Exponential Moving Average.

    Args:
        series: Price series.
        period: Look-back window.
        wilder: If True, use Wilder's smoothing factor ``1/period`` instead
                of the standard ``2/(period+1)``.

    Returns:
        EMA series (same length, leading NaNs).
    """
    if period < 1 or len(series) < period or series.isna().all():
        return pd.Series(np.nan, index=series.index)

    alpha = 1.0 / period if wilder else 2.0 / (period + 1)
    result = np.full(len(series), np.nan)

    # Find first valid index to avoid seeding with NaN
    first_idx = series.first_valid_index()
    if first_idx is None:
        return pd.Series(np.nan, index=series.index)
    start_pos = series.index.get_loc(first_idx)

    if len(series) - start_pos < period:
        return pd.Series(np.nan, index=series.index)

    # Seed with SMA of first `period` valid values starting from start_pos
    seed_val = series.iloc[start_pos : start_pos + period].mean()
    if pd.isna(seed_val):
        return pd.Series(np.nan, index=series.index)

    result[start_pos + period - 1] = seed_val
    vals = series.values.astype(float)

    for i in range(start_pos + period, len(vals)):
        if np.isnan(vals[i]):
            result[i] = result[i - 1]
        else:
            prev = result[i - 1]
            if np.isnan(prev):
                result[i] = vals[i]
            else:
                result[i] = alpha * vals[i] + (1.0 - alpha) * prev

    return pd.Series(result, index=series.index)


# ---------------------------------------------------------------------------
# Relative Strength Index
# ---------------------------------------------------------------------------

def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder's smoothing).

    Returns values in [0, 100].  The first ``period`` entries are NaN.
    """
    if period < 1 or len(close) < period + 1 or close.isna().all():
        return pd.Series(np.nan, index=close.index)

    delta = close.diff()
    gains = delta.clip(lower=0.0)
    losses = (-delta).clip(lower=0.0)

    # Find first valid diff
    first_idx = delta.first_valid_index()
    if first_idx is None:
        return pd.Series(np.nan, index=close.index)
    start_pos = close.index.get_loc(first_idx)

    if len(close) - start_pos < period:
        return pd.Series(np.nan, index=close.index)

    avg_gain = gains.iloc[start_pos : start_pos + period].mean()
    avg_loss = losses.iloc[start_pos : start_pos + period].mean()

    rsi_values = np.full(len(close), np.nan)

    if pd.isna(avg_gain) or pd.isna(avg_loss):
        return pd.Series(np.nan, index=close.index)

    if avg_loss == 0:
        rsi_values[start_pos + period - 1] = 50.0 if avg_gain == 0 else 100.0
    else:
        rs = avg_gain / avg_loss
        rsi_values[start_pos + period - 1] = 100.0 - 100.0 / (1.0 + rs)

    gain_vals = gains.values.astype(float)
    loss_vals = losses.values.astype(float)

    for i in range(start_pos + period, len(close)):
        g_i = gain_vals[i]
        l_i = loss_vals[i]
        if np.isnan(g_i) or np.isnan(l_i):
            rsi_values[i] = rsi_values[i - 1]
            continue
        avg_gain = (avg_gain * (period - 1) + g_i) / period
        avg_loss = (avg_loss * (period - 1) + l_i) / period
        if avg_loss == 0:
            rsi_values[i] = 50.0 if avg_gain == 0 else 100.0
        else:
            rs = avg_gain / avg_loss
            rsi_values[i] = 100.0 - 100.0 / (1.0 + rs)

    return pd.Series(rsi_values, index=close.index)


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------

def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Moving Average Convergence Divergence.

    Returns:
        (macd_line, signal_line, histogram) — three Series.
    """
    if len(close) < slow + signal_period:
        nan_s = pd.Series(np.nan, index=close.index)
        return nan_s.copy(), nan_s.copy(), nan_s.copy()

    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    macd_line = ema_fast - ema_slow

    # Signal line is EMA of MACD line — but MACD has NaN prefix, so we
    # compute the EMA only on the valid (non-NaN) tail, then map back.
    valid_mask = macd_line.notna()
    macd_valid = macd_line[valid_mask].reset_index(drop=True)

    if len(macd_valid) < signal_period:
        signal_line = pd.Series(np.nan, index=close.index)
    else:
        signal_valid = ema(macd_valid, signal_period)
        # Place back into full-length series
        signal_line = pd.Series(np.nan, index=close.index)
        valid_indices = macd_line.index[valid_mask]
        signal_line.iloc[valid_indices] = signal_valid.values

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
    """Bollinger Bands.

    Returns:
        (upper_band, middle_band, lower_band).
    """
    if period < 1 or len(close) < period:
        nan_s = pd.Series(np.nan, index=close.index)
        return nan_s.copy(), nan_s.copy(), nan_s.copy()

    middle = sma(close, period)
    rolling_std = close.rolling(window=period, min_periods=period).std(ddof=0)

    upper = middle + std_dev * rolling_std
    lower = middle - std_dev * rolling_std

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
