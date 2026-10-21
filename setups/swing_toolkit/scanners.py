"""
Momentum Masters — 3 Institutional Swing Scanners.

Implements the three core scanning strategies:
1. Momentum Scanner (Rising RVol, coiling at or breaking 20d/50d pivot high)
2. Daily & Weekly Inside Bar (DWIB) Scanner (Multi-timeframe squeeze: weekly inside bar + daily contraction)
3. All-Time-High (ATH) Scanner (Near ATH / 52W high, contracting along 10 and 20 EMAs)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd

from setups.indicators import ema, sma

logger = logging.getLogger("trading.setups.swing_scanners")


@dataclass
class ScannerMatch:
    scanner_name: str
    ticker: str
    matched: bool
    confidence: float  # 0.0 to 1.0
    reason: str
    metrics: Dict[str, Any] = field(default_factory=dict)


class MomentumScanner:
    """
    Scanner 1: Momentum Scanner
    Finds stocks in strong momentum backed by above-average volume,
    that have either just broken out of a pivot or are coiling tightly right at resistance.
    """
    name = "Momentum & Breakout"

    def __init__(
        self,
        lookback_pivot: int = 20,
        vol_avg_period: int = 20,
        min_rvol: float = 1.20,
        coiling_threshold_pct: float = 2.0,
    ) -> None:
        self.lookback_pivot = lookback_pivot
        self.vol_avg_period = vol_avg_period
        self.min_rvol = min_rvol
        self.coiling_threshold_pct = coiling_threshold_pct

    def scan(self, df: pd.DataFrame, ticker: str = "") -> ScannerMatch:
        min_bars = max(self.lookback_pivot, self.vol_avg_period, 50) + 5
        if len(df) < min_bars:
            return ScannerMatch(
                scanner_name=self.name,
                ticker=ticker,
                matched=False,
                confidence=0.0,
                reason=f"Insufficient history ({len(df)} bars, need {min_bars}).",
            )

        close = pd.to_numeric(df["close"], errors="coerce").astype(float)
        high = pd.to_numeric(df["high"], errors="coerce").astype(float)
        low = pd.to_numeric(df["low"], errors="coerce").astype(float)
        volume = pd.to_numeric(df["volume"], errors="coerce").astype(float)

        cur_close = float(close.iloc[-1])
        cur_vol = float(volume.iloc[-1])
        vol_sma = sma(volume, self.vol_avg_period)
        avg_vol = float(vol_sma.iloc[-1]) if not np.isnan(vol_sma.iloc[-1]) else 1.0
        rvol = cur_vol / max(avg_vol, 1.0)

        # 20-day high before today's bar
        pivot_high = float(high.iloc[-(self.lookback_pivot + 1):-1].max())
        ema20 = float(ema(close, 20).iloc[-1])
        sma50 = float(sma(close, 50).iloc[-1])

        # Trend filter: Close > 20 EMA and 50 SMA
        in_uptrend = (cur_close > ema20) and (cur_close > sma50)

        # Breakout or Coiling check
        is_breakout = cur_close >= pivot_high
        dist_to_pivot_pct = ((pivot_high - cur_close) / pivot_high) * 100.0
        is_coiling = (0.0 <= dist_to_pivot_pct <= self.coiling_threshold_pct)

        # Volume condition: RVol >= min_rvol or expanding volume trend
        prev_vol = float(volume.iloc[-2])
        vol_expanding = (cur_vol > prev_vol) and (rvol >= 1.0)
        has_volume = (rvol >= self.min_rvol) or vol_expanding

        matched = in_uptrend and (is_breakout or is_coiling) and has_volume

        # Compute confidence
        confidence = 0.0
        status = "None"
        if matched:
            status = "Broken Out" if is_breakout else "Coiling at Pivot"
            # Base confidence 0.70, boosted by higher RVol up to 0.95
            rvol_boost = min(max((rvol - 1.0) * 0.15, 0.0), 0.25)
            confidence = min(0.70 + rvol_boost, 0.98)
            reason = (
                f"Strong momentum in {ticker}. Status: {status} ({dist_to_pivot_pct:+.2f}% to 20d pivot {pivot_high:.2f}). "
                f"RVol: {rvol:.2f}x (Vol: {cur_vol:,.0f} vs 20d avg {avg_vol:,.0f}). Above 20 EMA and 50 SMA."
            )
        else:
            reasons = []
            if not in_uptrend:
                reasons.append("Below 20 EMA or 50 SMA")
            if not (is_breakout or is_coiling):
                reasons.append(f"Not at pivot (distance {dist_to_pivot_pct:.1f}%)")
            if not has_volume:
                reasons.append(f"Subdued volume (RVol {rvol:.2f}x)")
            reason = f"No momentum trigger: {', '.join(reasons)}."

        return ScannerMatch(
            scanner_name=self.name,
            ticker=ticker,
            matched=matched,
            confidence=round(confidence, 3),
            reason=reason,
            metrics={
                "rvol": round(rvol, 2),
                "pivot_high": round(pivot_high, 2),
                "cur_close": round(cur_close, 2),
                "dist_to_pivot_pct": round(dist_to_pivot_pct, 2),
                "status": status,
                "ema20": round(ema20, 2),
                "sma50": round(sma50, 2),
            },
        )


class DWIBScanner:
    """
    Scanner 2: Daily & Weekly Inside Bar (DWIB) Screener
    Finds stocks forming an inside bar on the weekly chart while also showing
    volatility contraction on the daily chart (the classic multi-timeframe pre-breakout squeeze).
    """
    name = "Daily & Weekly Inside Bar (DWIB)"

    def __init__(self, atr_period: int = 14, max_dist_to_high_pct: float = 12.0) -> None:
        self.atr_period = atr_period
        self.max_dist_to_high_pct = max_dist_to_high_pct

    def scan(self, df: pd.DataFrame, ticker: str = "") -> ScannerMatch:
        if len(df) < 60:
            return ScannerMatch(
                scanner_name=self.name,
                ticker=ticker,
                matched=False,
                confidence=0.0,
                reason=f"Insufficient history ({len(df)} daily bars, need 60+).",
            )

        close = pd.to_numeric(df["close"], errors="coerce").astype(float)
        high = pd.to_numeric(df["high"], errors="coerce").astype(float)
        low = pd.to_numeric(df["low"], errors="coerce").astype(float)
        volume = pd.to_numeric(df["volume"], errors="coerce").astype(float)

        cur_close = float(close.iloc[-1])
        cur_high = float(high.iloc[-1])
        cur_low = float(low.iloc[-1])
        prev_high = float(high.iloc[-2])
        prev_low = float(low.iloc[-2])

        # 1. Daily Contraction Check:
        # A) Strict daily inside bar: High <= Prev High and Low >= Prev Low
        is_daily_inside = (cur_high <= prev_high * 1.002) and (cur_low >= prev_low * 0.998)

        # B) ATR range contraction: True range of today <= 0.75 * 14-day ATR
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs()
        ], axis=1).max(axis=1)
        atr_series = tr.rolling(self.atr_period).mean()
        cur_atr = float(atr_series.iloc[-1]) if not np.isnan(atr_series.iloc[-1]) else (cur_high - cur_low)
        today_range = cur_high - cur_low
        is_range_contracting = today_range < (0.80 * max(cur_atr, 0.01))

        daily_contraction = is_daily_inside or is_range_contracting

        # 2. Weekly Inside Bar Check:
        # Build weekly bars from the daily series
        weekly_df = self._build_weekly_bars(df)
        if len(weekly_df) < 3:
            return ScannerMatch(
                scanner_name=self.name,
                ticker=ticker,
                matched=False,
                confidence=0.0,
                reason="Not enough weekly candles.",
            )

        w_high_cur = float(weekly_df["high"].iloc[-1])
        w_low_cur = float(weekly_df["low"].iloc[-1])
        w_high_prev = float(weekly_df["high"].iloc[-2])
        w_low_prev = float(weekly_df["low"].iloc[-2])

        # Weekly inside bar with small 0.5% tolerance buffer
        weekly_inside_bar = (w_high_cur <= w_high_prev * 1.005) and (w_low_cur >= w_low_prev * 0.995)

        # 3. Base / Trend Filter:
        # Near prior 50-day highs (not in deep downtrend) and above 50 SMA
        sma50 = float(sma(close, 50).iloc[-1])
        high_50 = float(high.iloc[-50:].max())
        dist_to_50h_pct = ((high_50 - cur_close) / high_50) * 100.0

        near_base_or_high = dist_to_50h_pct <= self.max_dist_to_high_pct
        above_sma50 = cur_close >= (sma50 * 0.98)

        matched = weekly_inside_bar and daily_contraction and near_base_or_high and above_sma50

        confidence = 0.0
        if matched:
            confidence = 0.85 if is_daily_inside else 0.75
            reason = (
                f"Multi-timeframe squeeze in {ticker}! Weekly Inside Bar (W-Range: [{w_low_cur:.2f} - {w_high_cur:.2f}] "
                f"inside [{w_low_prev:.2f} - {w_high_prev:.2f}]) with Daily Contraction (Daily range: {today_range:.2f} vs ATR {cur_atr:.2f}). "
                f"Consolidating within {dist_to_50h_pct:.1f}% of 50-day high."
            )
        else:
            reasons = []
            if not weekly_inside_bar:
                reasons.append("No weekly inside bar")
            if not daily_contraction:
                reasons.append("No daily range contraction")
            if not near_base_or_high:
                reasons.append(f"Too far from high ({dist_to_50h_pct:.1f}%)")
            reason = f"No DWIB squeeze: {', '.join(reasons)}."

        return ScannerMatch(
            scanner_name=self.name,
            ticker=ticker,
            matched=matched,
            confidence=round(confidence, 3),
            reason=reason,
            metrics={
                "weekly_inside_bar": bool(weekly_inside_bar),
                "daily_inside_bar": bool(is_daily_inside),
                "daily_range_contraction": bool(is_range_contracting),
                "dist_to_50d_high_pct": round(dist_to_50h_pct, 2),
                "today_range": round(today_range, 2),
                "atr14": round(cur_atr, 2),
            },
        )

    def _build_weekly_bars(self, df: pd.DataFrame) -> pd.DataFrame:
        """Helper to resample daily bars into weekly bars safely."""
        copy_df = df.copy()
        if isinstance(copy_df.index, pd.DatetimeIndex):
            return copy_df.resample("W-FRI").agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum"
            }).dropna()

        # If index is not datetime, check 'time' or 'date' column
        date_col = next((c for c in ["time", "date", "timestamp"] if c in copy_df.columns), None)
        if date_col is not None:
            copy_df[date_col] = pd.to_datetime(copy_df[date_col], errors="coerce")
            copy_df = copy_df.dropna(subset=[date_col]).set_index(date_col)
            return copy_df.resample("W-FRI").agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum"
            }).dropna()

        # Fallback: slice consecutive 5-bar chunks as weekly approximations
        chunks = []
        n = len(df)
        for i in range(0, n, 5):
            sub = df.iloc[i:i + 5]
            if len(sub) >= 2:
                chunks.append({
                    "open": sub["open"].iloc[0],
                    "high": sub["high"].max(),
                    "low": sub["low"].min(),
                    "close": sub["close"].iloc[-1],
                    "volume": sub["volume"].sum(),
                })
        return pd.DataFrame(chunks)


class ATHScanner:
    """
    Scanner 3: All-Time-High (ATH) / 52-Week High Contraction Scanner
    Finds market leaders trading at or within 3-5% of All-Time Highs (zero overhead supply)
    that are showing tight contraction along the 10 and 20 EMAs.
    """
    name = "All-Time-High (ATH) Contraction"

    def __init__(
        self,
        max_dist_from_ath_pct: float = 3.5,
        ema_band_tolerance_pct: float = 2.0,
        rolling_high_window: int = 250,
    ) -> None:
        self.max_dist_from_ath_pct = max_dist_from_ath_pct
        self.ema_band_tolerance_pct = ema_band_tolerance_pct
        self.rolling_high_window = rolling_high_window

    def scan(self, df: pd.DataFrame, ticker: str = "") -> ScannerMatch:
        min_bars = 60
        if len(df) < min_bars:
            return ScannerMatch(
                scanner_name=self.name,
                ticker=ticker,
                matched=False,
                confidence=0.0,
                reason=f"Insufficient history ({len(df)} bars, need 60+).",
            )

        close = pd.to_numeric(df["close"], errors="coerce").astype(float)
        high = pd.to_numeric(df["high"], errors="coerce").astype(float)
        low = pd.to_numeric(df["low"], errors="coerce").astype(float)
        volume = pd.to_numeric(df["volume"], errors="coerce").astype(float)

        cur_close = float(close.iloc[-1])
        window = min(len(df), self.rolling_high_window)
        ath_high = float(high.iloc[-window:].max())

        # Distance from ATH (or 52W High)
        dist_to_ath_pct = ((ath_high - cur_close) / ath_high) * 100.0
        near_ath = (0.0 <= dist_to_ath_pct <= self.max_dist_from_ath_pct) or (cur_close >= ath_high)

        # 10 EMA and 20 EMA calculation
        ema10 = float(ema(close, 10).iloc[-1])
        ema20 = float(ema(close, 20).iloc[-1])

        # Trend alignment: 10 EMA >= 20 EMA and price >= 20 EMA
        ema_aligned = (ema10 >= ema20 * 0.995) and (cur_close >= ema20 * 0.99)

        # Contraction along EMAs: price is riding near the 10/20 EMA band (within tolerance)
        dist_to_ema10_pct = (abs(cur_close - ema10) / ema10) * 100.0
        dist_to_ema20_pct = (abs(cur_close - ema20) / ema20) * 100.0
        riding_emas = (dist_to_ema10_pct <= self.ema_band_tolerance_pct) or (dist_to_ema20_pct <= self.ema_band_tolerance_pct)

        # Volume drying up check: recent volume <= 20-day average volume (absorption phase)
        vol_sma = sma(volume, 20)
        cur_vol = float(volume.iloc[-1])
        avg_vol = float(vol_sma.iloc[-1]) if not np.isnan(vol_sma.iloc[-1]) else cur_vol
        vol_dry_up = cur_vol <= (avg_vol * 1.15)  # Supply absorption before breakout

        matched = near_ath and ema_aligned and riding_emas

        confidence = 0.0
        if matched:
            confidence = 0.90 if vol_dry_up else 0.80
            reason = (
                f"Pristine ATH setup in {ticker}! Trading within {dist_to_ath_pct:.2f}% of ATH ({ath_high:.2f}). "
                f"Contraction hugging 10 EMA ({ema10:.2f}) and 20 EMA ({ema20:.2f}). "
                f"Zero overhead resistance. Volume dry-up: {cur_vol:,.0f} vs avg {avg_vol:,.0f}."
            )
        else:
            reasons = []
            if not near_ath:
                reasons.append(f"Far from ATH ({dist_to_ath_pct:.1f}% away)")
            if not ema_aligned:
                reasons.append("10/20 EMA not stacked bullishly")
            if not riding_emas:
                reasons.append("Extended away from 10/20 EMA band")
            reason = f"No ATH setup: {', '.join(reasons)}."

        return ScannerMatch(
            scanner_name=self.name,
            ticker=ticker,
            matched=matched,
            confidence=round(confidence, 3),
            reason=reason,
            metrics={
                "ath_high": round(ath_high, 2),
                "cur_close": round(cur_close, 2),
                "dist_to_ath_pct": round(dist_to_ath_pct, 2),
                "ema10": round(ema10, 2),
                "ema20": round(ema20, 2),
                "dist_to_ema10_pct": round(dist_to_ema10_pct, 2),
                "volume_dry_up": bool(vol_dry_up),
            },
        )


class SwingScannerSuite:
    """
    Orchestrates the 3 Momentum Masters Scanners across a candidate universe.
    Aggregates hits and identifies high-conviction confluence (candidates triggering multiple scanners).
    """

    def __init__(self) -> None:
        self.momentum_scanner = MomentumScanner()
        self.dwib_scanner = DWIBScanner()
        self.ath_scanner = ATHScanner()

    def scan_symbol(self, df: pd.DataFrame, ticker: str) -> Dict[str, Any]:
        """Runs all 3 scanners on a single ticker's daily OHLCV DataFrame."""
        m_res = self.momentum_scanner.scan(df, ticker)
        d_res = self.dwib_scanner.scan(df, ticker)
        a_res = self.ath_scanner.scan(df, ticker)

        matched_scanners = []
        if m_res.matched:
            matched_scanners.append("Momentum")
        if d_res.matched:
            matched_scanners.append("DWIB Inside Bar")
        if a_res.matched:
            matched_scanners.append("ATH Contraction")

        is_hit = len(matched_scanners) > 0
        overall_confidence = max([m_res.confidence, d_res.confidence, a_res.confidence], default=0.0)

        # Confluence bonus: stocks matching multiple scanners get higher conviction
        if len(matched_scanners) >= 2:
            overall_confidence = min(overall_confidence + 0.10, 0.99)

        return {
            "ticker": ticker,
            "is_hit": is_hit,
            "matched_scanners": matched_scanners,
            "confluence_count": len(matched_scanners),
            "overall_confidence": round(overall_confidence, 3),
            "results": {
                "momentum": m_res,
                "dwib": d_res,
                "ath": a_res,
            },
        }
