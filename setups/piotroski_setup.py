"""
Piotroski F-Score Fundamental Quality Setup

Incorporates the 9-point fundamental accounting framework from `staskh/trading_skills`:
Evaluates:
- Profitability: Net Income, ROA, Operating Cash Flow, Accrual quality (OCF > NI)
- Capital Structure & Liquidity: Long-Term Debt reduction, Current Ratio increase, Dilution check
- Operating Efficiency: Gross Margin expansion, Asset Turnover increase

Score 7-9: Institutional Grade Quality (Bullish confluence)
Score 4-6: Neutral Financial Health
Score 0-3: Deteriorating Balance Sheet / Distressed (Bearish confluence)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional
import pandas as pd
import yfinance as yf
from functools import lru_cache

from setups.base import BaseSetup, SetupSignal

logger = logging.getLogger("trading.setups.piotroski")


def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        import math
        return None if math.isnan(f) or math.isinf(f) else f
    except (ValueError, TypeError):
        return None


@lru_cache(maxsize=64)
def calculate_piotroski_score(symbol: str) -> Dict[str, Any]:
    """Calculates 9-point Piotroski F-score from quarterly and annual financial statements."""
    ticker = yf.Ticker(symbol)
    res: Dict[str, Any] = {"score": 0, "max_score": 9, "criteria": {}, "status": "OK"}

    try:
        financials = ticker.quarterly_financials
        cashflow = ticker.quarterly_cashflow
        annual_fin = ticker.financials
        annual_bs = ticker.balance_sheet

        if financials is None or financials.empty or cashflow is None or cashflow.empty:
            res["status"] = "INSUFFICIENT_DATA"
            return res

        # Helper to extract row safely
        def get_row_val(df, row_name, col_idx=0):
            if df is None or df.empty or col_idx >= df.shape[1]:
                return None
            for idx in df.index:
                if str(idx).lower() == row_name.lower():
                    return _safe_float(df.iloc[:, col_idx].loc[idx])
            return None

        # 1. Net Income > 0
        net_inc = get_row_val(financials, "Net Income", 0)
        c1 = net_inc is not None and net_inc > 0
        res["criteria"]["positive_net_income"] = c1
        if c1: res["score"] += 1

        # 2. Operating Cash Flow > 0
        ocf = get_row_val(cashflow, "Operating Cash Flow", 0)
        c2 = ocf is not None and ocf > 0
        res["criteria"]["positive_ocf"] = c2
        if c2: res["score"] += 1

        # 3. Cash Flow > Net Income (High earnings quality)
        c3 = ocf is not None and net_inc is not None and ocf > net_inc
        res["criteria"]["ocf_greater_than_ni"] = c3
        if c3: res["score"] += 1

        # 4. ROA > 0
        tot_assets = get_row_val(annual_bs, "Total Assets", 0) if annual_bs is not None else None
        c4 = net_inc is not None and tot_assets is not None and tot_assets > 0 and (net_inc / tot_assets) > 0
        res["criteria"]["positive_roa"] = c4
        if c4: res["score"] += 1

        # Year-over-year checks if annual data has 2 years
        if annual_bs is not None and annual_bs.shape[1] >= 2 and annual_fin is not None and annual_fin.shape[1] >= 2:
            # 5. Lower Long-Term Debt
            lt_debt_curr = get_row_val(annual_bs, "Long Term Debt", 0) or 0.0
            lt_debt_prev = get_row_val(annual_bs, "Long Term Debt", 1) or 0.0
            c5 = lt_debt_curr <= lt_debt_prev
            res["criteria"]["lower_debt"] = c5
            if c5: res["score"] += 1

            # 6. Higher Current Ratio
            ca_curr = get_row_val(annual_bs, "Current Assets", 0) or 1.0
            cl_curr = get_row_val(annual_bs, "Current Liabilities", 0) or 1.0
            ca_prev = get_row_val(annual_bs, "Current Assets", 1) or 1.0
            cl_prev = get_row_val(annual_bs, "Current Liabilities", 1) or 1.0
            cr_curr = ca_curr / cl_curr if cl_curr > 0 else 1.0
            cr_prev = ca_prev / cl_prev if cl_prev > 0 else 1.0
            c6 = cr_curr > cr_prev
            res["criteria"]["higher_current_ratio"] = c6
            if c6: res["score"] += 1

            # 7. No New Share Dilution
            sh_curr = get_row_val(annual_bs, "Share Issued", 0)
            sh_prev = get_row_val(annual_bs, "Share Issued", 1)
            c7 = sh_curr is not None and sh_prev is not None and sh_curr <= sh_prev
            res["criteria"]["no_dilution"] = c7
            if c7: res["score"] += 1

            # 8. Higher Gross Margin
            rev_curr = get_row_val(annual_fin, "Total Revenue", 0) or 1.0
            gp_curr = get_row_val(annual_fin, "Gross Profit", 0) or 0.0
            rev_prev = get_row_val(annual_fin, "Total Revenue", 1) or 1.0
            gp_prev = get_row_val(annual_fin, "Gross Profit", 1) or 0.0
            gm_curr = gp_curr / rev_curr if rev_curr > 0 else 0.0
            gm_prev = gp_prev / rev_prev if rev_prev > 0 else 0.0
            c8 = gm_curr > gm_prev
            res["criteria"]["higher_gross_margin"] = c8
            if c8: res["score"] += 1

            # 9. Higher Asset Turnover
            ta_prev = get_row_val(annual_bs, "Total Assets", 1) or 1.0
            at_curr = rev_curr / tot_assets if (tot_assets and tot_assets > 0) else 0.0
            at_prev = rev_prev / ta_prev if ta_prev > 0 else 0.0
            c9 = at_curr > at_prev
            res["criteria"]["higher_asset_turnover"] = c9
            if c9: res["score"] += 1

    except Exception as e:
        logger.debug(f"Piotroski computation error for {symbol}: {e}")
        res["status"] = "ERROR"

    return res


class PiotroskiSetup(BaseSetup):
    """Evaluates institutional fundamental health using Piotroski F-Score."""

    @property
    def name(self) -> str:
        return "Piotroski F-Score"

    def evaluate(self, df: pd.DataFrame, ticker: str = "") -> SetupSignal:
        if not ticker:
            return SetupSignal(self.name, "neutral", 0.0, "No ticker provided.")

        # Clean index symbols (^NSEI -> NIFTY is not an individual company with F-Score)
        clean = ticker.upper().replace("^", "")
        if clean in ("NSEI", "NSEBANK", "BSESN", "NIFTY", "BANKNIFTY", "SENSEX"):
            return SetupSignal(
                self.name,
                "neutral",
                0.0,
                f"{ticker} is a broad market index; Piotroski F-Score applies to constituent equities.",
            )

        try:
            score_data = calculate_piotroski_score(ticker)
            if score_data.get("status") != "OK":
                return SetupSignal(self.name, "neutral", 0.0, "Financial statement data unavailable for F-Score.")

            score = score_data["score"]
            reason = f"Piotroski F-Score: {score}/9."

            if score >= 7:
                conf = 0.50 + (score - 6) * 0.15
                return SetupSignal(
                    self.name,
                    "bullish",
                    min(0.90, conf),
                    reason + " Outstanding financial health, strong profitability & balance sheet.",
                    indicator_values=score_data,
                )
            elif score <= 3:
                conf = 0.50 + (4 - score) * 0.15
                return SetupSignal(
                    self.name,
                    "bearish",
                    min(0.90, conf),
                    reason + " Weak/deteriorating financial health; high risk of underperformance.",
                    indicator_values=score_data,
                )
            else:
                return SetupSignal(
                    self.name,
                    "neutral",
                    0.35,
                    reason + " Moderate financial health in standard range.",
                    indicator_values=score_data,
                )

        except Exception as e:
            return SetupSignal(self.name, "neutral", 0.0, f"Error computing Piotroski score: {e}")
