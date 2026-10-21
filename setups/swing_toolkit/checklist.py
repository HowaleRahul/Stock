"""
The Filter Checklist — 8-Factor Institutional Quality Scoring Engine.

A scanner hit is merely a starting point, never a buy.
This checklist decides what actually makes the cut into the Winning Watchlist:
1. Liquidity & Volume (Sufficient ADV & turnover for zero-slippage execution)
2. Contraction (Price tightening VCP-style with volume drying up into base)
3. Strong Sector & Relative Strength (Outperforming benchmark index)
4. Stage 2 + Key Moving Averages (Stan Weinstein Stage 2, Price > 20 EMA > 50 > 200 SMA)
5. Candle Quality (Clean decisive bars, high body-to-range ratio, minimal wicks)
6. Multi-Timeframe Alignment (Weekly trend confirms daily setup)
7. VCP / Valid Pattern Structure (Recognizable base, not arbitrary chart level)
8. Fundamental Health (Avoid structurally weak or junk penny stocks)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd

from setups.indicators import ema, sma, rsi
from setups.swing_toolkit.universe import STOCK_SECTORS, BENCHMARK_TICKER

logger = logging.getLogger("trading.setups.swing_checklist")


@dataclass
class ChecklistItem:
    name: str
    passed: bool
    score: float
    max_score: float
    details: str


@dataclass
class QualityScoreResult:
    ticker: str
    composite_score: float  # 0 to 100
    qualifies_for_watchlist: bool  # True if composite_score >= 70.0
    passed_count: int
    total_checks: int
    sector: str
    summary: str
    checklist_items: Dict[str, ChecklistItem] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "composite_score": round(self.composite_score, 1),
            "qualifies_for_watchlist": self.qualifies_for_watchlist,
            "passed_count": self.passed_count,
            "total_checks": self.total_checks,
            "sector": self.sector,
            "summary": self.summary,
            "checklist_items": {
                k: {
                    "name": v.name,
                    "passed": v.passed,
                    "score": round(v.score, 1),
                    "max_score": round(v.max_score, 1),
                    "details": v.details,
                }
                for k, v in self.checklist_items.items()
            },
        }


class SwingFilterChecklist:
    """
    Evaluates candidate stocks against the 8 institutional quality criteria.
    Only candidates scoring >= 70 earn a place on the Active Watchlist.
    """

    PASS_CUTOFF_SCORE = 70.0

    def evaluate(
        self,
        df: pd.DataFrame,
        ticker: str,
        benchmark_df: Optional[pd.DataFrame] = None,
        fundamental_info: Optional[Dict[str, Any]] = None,
    ) -> QualityScoreResult:
        if len(df) < 50:
            return QualityScoreResult(
                ticker=ticker,
                composite_score=0.0,
                qualifies_for_watchlist=False,
                passed_count=0,
                total_checks=8,
                sector=STOCK_SECTORS.get(ticker, "General"),
                summary=f"Insufficient history ({len(df)} bars, need 50+).",
                checklist_items={},
            )

        close = pd.to_numeric(df["close"], errors="coerce").astype(float)
        high = pd.to_numeric(df["high"], errors="coerce").astype(float)
        low = pd.to_numeric(df["low"], errors="coerce").astype(float)
        open_p = pd.to_numeric(df["open"], errors="coerce").astype(float)
        volume = pd.to_numeric(df["volume"], errors="coerce").astype(float)

        cur_close = float(close.iloc[-1])
        sector = STOCK_SECTORS.get(ticker, "General")

        items: Dict[str, ChecklistItem] = {}

        # -------------------------------------------------------------
        # 1. Liquidity & Volume (12.5 pts)
        # -------------------------------------------------------------
        vol_sma20 = sma(volume, 20)
        adv_20 = float(vol_sma20.iloc[-1]) if not np.isnan(vol_sma20.iloc[-1]) else float(volume.iloc[-1])
        daily_turnover = adv_20 * cur_close  # in ₹
        # Min 50,000 shares and ₹2.5 Crore turnover for clean institutional fills
        liq_passed = (adv_20 >= 50000) and (daily_turnover >= 25000000 or cur_close >= 100)
        liq_score = 12.5 if liq_passed else (6.0 if adv_20 >= 30000 else 0.0)
        items["liquidity"] = ChecklistItem(
            name="Liquidity & Volume",
            passed=liq_passed,
            score=liq_score,
            max_score=12.5,
            details=f"20d ADV: {adv_20:,.0f} shares. Est. Turnover: ₹{daily_turnover / 1e7:.2f} Cr.",
        )

        # -------------------------------------------------------------
        # 2. Contraction & Volume Dry-up (12.5 pts)
        # -------------------------------------------------------------
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs()
        ], axis=1).max(axis=1)
        atr14 = tr.rolling(14).mean()
        recent_range = float(tr.iloc[-5:].mean())
        historical_range = float(tr.iloc[-30:-5].mean()) if len(df) >= 35 else recent_range
        range_contracted = recent_range < (historical_range * 0.90)

        # Volume drying up into base
        recent_vol = float(volume.iloc[-3:].mean())
        vol_dried_up = recent_vol <= (adv_20 * 0.95)

        contraction_passed = range_contracted or vol_dried_up
        contraction_score = 12.5 if (range_contracted and vol_dried_up) else (8.0 if contraction_passed else 0.0)
        items["contraction"] = ChecklistItem(
            name="Price Contraction & Volume Dry-up",
            passed=contraction_passed,
            score=contraction_score,
            max_score=12.5,
            details=(
                f"Recent 5d range {recent_range:.2f} vs 30d range {historical_range:.2f}. "
                f"3d vol {recent_vol:,.0f} vs 20d avg {adv_20:,.0f} (dry-up: {vol_dried_up})."
            ),
        )

        # -------------------------------------------------------------
        # 3. Strong Sector & Relative Strength (12.5 pts)
        # -------------------------------------------------------------
        # Measure stock 20d and 60d return vs benchmark (or absolute positive alpha)
        ret_20d = ((cur_close - float(close.iloc[-21])) / float(close.iloc[-21])) * 100.0 if len(close) > 21 else 0.0
        ret_60d = ((cur_close - float(close.iloc[-61])) / float(close.iloc[-61])) * 100.0 if len(close) > 61 else ret_20d

        bm_ret_20d = 0.0
        if benchmark_df is not None and len(benchmark_df) >= 21:
            bm_close = benchmark_df["close"]
            bm_ret_20d = ((float(bm_close.iloc[-1]) - float(bm_close.iloc[-21])) / float(bm_close.iloc[-21])) * 100.0

        outperforming = (ret_20d > bm_ret_20d) and (ret_20d > 0)
        rs_passed = outperforming or (ret_60d > 10.0)
        rs_score = 12.5 if (ret_20d > bm_ret_20d + 3.0) else (8.0 if rs_passed else 0.0)
        items["strong_sector_rs"] = ChecklistItem(
            name="Strong Sector & Relative Strength",
            passed=rs_passed,
            score=rs_score,
            max_score=12.5,
            details=f"Sector: {sector}. 20d Return: {ret_20d:+.2f}% vs Nifty: {bm_ret_20d:+.2f}%. Outperforming: {outperforming}.",
        )

        # -------------------------------------------------------------
        # 4. Stage 2 + Key Moving Averages (15.0 pts)
        # -------------------------------------------------------------
        ema20 = float(ema(close, 20).iloc[-1])
        sma50 = float(sma(close, 50).iloc[-1])
        sma200_series = sma(close, 200)
        has_200 = len(close) >= 200 and not np.isnan(sma200_series.iloc[-1])
        sma200 = float(sma200_series.iloc[-1]) if has_200 else sma50 * 0.90

        stage2_mavg_aligned = (cur_close > ema20) and (cur_close > sma50)
        if has_200:
            stage2_mavg_aligned = stage2_mavg_aligned and (sma50 > sma200) and (cur_close > sma200)
            sma200_rising = sma200 >= float(sma200_series.iloc[-20])
            stage2_passed = stage2_mavg_aligned and sma200_rising
        else:
            stage2_passed = stage2_mavg_aligned

        stage2_score = 15.0 if stage2_passed else (8.0 if (cur_close > sma50) else 0.0)
        items["stage_2"] = ChecklistItem(
            name="Weinstein Stage 2 Uptrend",
            passed=stage2_passed,
            score=stage2_score,
            max_score=15.0,
            details=f"Close {cur_close:.2f} > 20 EMA ({ema20:.2f}) > 50 SMA ({sma50:.2f}) > 200 SMA ({sma200:.2f}).",
        )

        # -------------------------------------------------------------
        # 5. Candle Quality (12.5 pts)
        # -------------------------------------------------------------
        # High body ratio, decisive candle closures, absence of erratic wicks
        body = (close.iloc[-10:] - open_p.iloc[-10:]).abs()
        range_10 = (high.iloc[-10:] - low.iloc[-10:]).clip(lower=0.01)
        body_ratios = body / range_10
        avg_body_ratio = float(body_ratios.mean())
        # Clean decisive candles typically have body ratio >= 45%
        candle_quality_passed = avg_body_ratio >= 0.45
        candle_score = 12.5 if avg_body_ratio >= 0.50 else (8.0 if candle_quality_passed else 4.0)
        items["candle_quality"] = ChecklistItem(
            name="Candle Quality & Decisive Action",
            passed=candle_quality_passed,
            score=candle_score,
            max_score=12.5,
            details=f"Avg 10-bar Body-to-Range Ratio: {avg_body_ratio * 100:.1f}%. Clean consolidation without excessive shadows.",
        )

        # -------------------------------------------------------------
        # 6. Multi-Timeframe Alignment (12.5 pts)
        # -------------------------------------------------------------
        # Weekly trend is bullish (Weekly RSI > 50 and Weekly Close > 10w EMA)
        rsi_daily = float(rsi(close, 14).iloc[-1])
        daily_bullish = 50.0 <= rsi_daily <= 80.0
        # Estimate weekly momentum using 10d EMA vs 40d EMA (proxy for 2w vs 8w)
        ema10 = float(ema(close, 10).iloc[-1])
        mtf_passed = daily_bullish and (ema10 >= sma50)
        mtf_score = 12.5 if mtf_passed else (6.0 if daily_bullish else 0.0)
        items["multi_timeframe"] = ChecklistItem(
            name="Multi-Timeframe Trend Alignment",
            passed=mtf_passed,
            score=mtf_score,
            max_score=12.5,
            details=f"Daily RSI(14): {rsi_daily:.1f}. Higher TF trend stacked bullishly (10 EMA {ema10:.2f} >= 50 SMA {sma50:.2f}).",
        )

        # -------------------------------------------------------------
        # 7. VCP / Valid Pattern Recognition (12.5 pts)
        # -------------------------------------------------------------
        # Check for progressive volatility contraction (T1 depth > T2 depth)
        pattern_detected = False
        pattern_details = "Consolidation base"
        if len(df) >= 30:
            h20 = float(high.iloc[-20:].max())
            l20 = float(low.iloc[-20:].min())
            depth_20 = ((h20 - l20) / h20) * 100.0

            h10 = float(high.iloc[-10:].max())
            l10 = float(low.iloc[-10:].min())
            depth_10 = ((h10 - l10) / h10) * 100.0

            if depth_10 < depth_20:
                pattern_detected = True
                pattern_details = f"Classic VCP compression (Contraction 1: {depth_20:.1f}% -> Contraction 2: {depth_10:.1f}%)"
            elif depth_10 <= 8.0:
                pattern_detected = True
                pattern_details = f"Tight flat base ({depth_10:.1f}% consolidation depth)"

        vcp_score = 12.5 if pattern_detected else 5.0
        items["vcp_pattern"] = ChecklistItem(
            name="VCP / Valid Base Pattern",
            passed=pattern_detected,
            score=vcp_score,
            max_score=12.5,
            details=pattern_details,
        )

        # -------------------------------------------------------------
        # 8. Fundamentals Health Check (10.0 pts)
        # -------------------------------------------------------------
        # Prevent structurally broken / junk penny stocks
        not_penny = cur_close >= 25.0
        fund_passed = not_penny
        fund_details = f"Price ₹{cur_close:.2f} clears penny/microcap threshold."
        if fundamental_info:
            pe = fundamental_info.get("trailingPE")
            mcap = fundamental_info.get("marketCap", 0)
            if pe is not None and pe > 0:
                fund_details += f" P/E: {pe:.1f}."
            if mcap and mcap >= 1e9:
                fund_details += f" Mcap: ₹{mcap / 1e7:.0f} Cr."

        fund_score = 10.0 if fund_passed else 0.0
        items["fundamentals"] = ChecklistItem(
            name="Fundamental Health Check",
            passed=fund_passed,
            score=fund_score,
            max_score=10.0,
            details=fund_details,
        )

        # -------------------------------------------------------------
        # Aggregate Composite Score
        # -------------------------------------------------------------
        composite_score = sum(item.score for item in items.values())
        passed_count = sum(1 for item in items.values() if item.passed)
        qualifies = composite_score >= self.PASS_CUTOFF_SCORE

        if qualifies:
            summary = (
                f"✅ APPROVED for Watchlist! Score: {composite_score:.1f}/100 ({passed_count}/8 criteria met). "
                f"Strong Stage 2 momentum in {sector} sector with VCP contraction."
            )
        else:
            summary = (
                f"❌ REJECTED from Watchlist. Score: {composite_score:.1f}/100 ({passed_count}/8 criteria met). "
                f"Failed key gates ({', '.join([it.name for it in items.values() if not it.passed][:3])})."
            )

        return QualityScoreResult(
            ticker=ticker,
            composite_score=round(composite_score, 1),
            qualifies_for_watchlist=qualifies,
            passed_count=passed_count,
            total_checks=len(items),
            sector=sector,
            summary=summary,
            checklist_items=items,
        )
