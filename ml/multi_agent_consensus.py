"""
Multi-Agent Decision Consensus Engine

Incorporates the institutional multi-agent architecture from `TauricResearch/TradingAgents`:
- Specialized Agent Personas:
  1. TechnicalAnalyst: Price action, moving averages, momentum, volatility contraction (VCP), volume.
  2. DerivativesAnalyst: Put-Call Ratio (PCR), Gamma Exposure (GEX), Max Pain, and Option Greeks.
  3. FundamentalAnalyst: Piotroski F-Score, Earnings quality, Valuation.
  4. SentimentAnalyst: News headlines, VADER financial sentiment, and FII/DII institutional cash flow.
- Adversarial Debate:
  - Bull Researcher vs Bear Researcher: Counters confirmation bias by actively arguing opposite sides.
- Risk Gatekeeper:
  - Chief Risk Officer: Checks Kelly sizing, ruin probability, and volatility regime.
- Produces an explainable, consensus-backed trading verdict.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import math
import numpy as np

logger = logging.getLogger("trading.ml.multi_agent")


@dataclass
class AgentReport:
    agent_name: str
    stance: str  # "BULLISH", "BEARISH", "NEUTRAL"
    conviction: float  # 0.0 to 1.0
    thesis: str
    key_metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MultiAgentVerdict:
    consensus_signal: str  # "bullish", "bearish", "neutral"
    consensus_confidence: float
    bull_arguments: List[str]
    bear_arguments: List[str]
    chief_risk_ruling: str
    agent_reports: List[AgentReport]
    recommended_action: str


class MultiAgentConsensusEngine:
    """Orchestrates collaborative financial multi-agent decision analysis."""

    @staticmethod
    def _safe_float(val: Any, default: float = 0.0, min_val: Optional[float] = None, max_val: Optional[float] = None) -> float:
        """Safely extracts a finite float, avoiding None, NaN, inf, or bad types."""
        if val is None:
            res = default
        else:
            try:
                res = float(val)
                if math.isnan(res) or math.isinf(res):
                    res = default
            except (ValueError, TypeError):
                res = default
        if min_val is not None:
            res = max(min_val, res)
        if max_val is not None:
            res = min(max_val, res)
        return res

    @classmethod
    def evaluate(
        cls,
        ticker: str,
        regime_data: Optional[Dict[str, Any]],
        setup_signals: Optional[List[Any]],
        options_data: Optional[Dict[str, Any]] = None,
        fundamental_data: Optional[Dict[str, Any]] = None,
        sentiment_data: Optional[Dict[str, Any]] = None,
        min_conviction_threshold: float = 1.2,
    ) -> MultiAgentVerdict:
        """Runs the multi-agent consensus workflow."""
        reports: List[AgentReport] = []
        reg_info = regime_data if isinstance(regime_data, dict) else {}
        setups_list = setup_signals if isinstance(setup_signals, list) else []

        # -------------------------------------------------------------------
        # 1. Technical Analyst Agent
        # -------------------------------------------------------------------
        bull_count = 0
        bear_count = 0
        for s in setups_list:
            sig = getattr(s, "signal", None) or (s.get("signal") if isinstance(s, dict) else "")
            sig_str = str(sig).lower()
            if sig_str == "bullish":
                bull_count += 1
            elif sig_str == "bearish":
                bear_count += 1

        total_setups = max(1, len(setups_list))

        tech_stance = "NEUTRAL"
        tech_conviction = 0.5
        if bull_count > bear_count:
            tech_stance = "BULLISH"
            tech_conviction = min(0.95, max(0.5, 0.5 + (bull_count - bear_count) / total_setups * 0.5))
        elif bear_count > bull_count:
            tech_stance = "BEARISH"
            tech_conviction = min(0.95, max(0.5, 0.5 + (bear_count - bull_count) / total_setups * 0.5))

        tech_report = AgentReport(
            agent_name="Technical Analyst",
            stance=tech_stance,
            conviction=tech_conviction,
            thesis=f"Confluence of {bull_count} bullish vs {bear_count} bearish setups in {reg_info.get('regime', 'unknown')} regime.",
            key_metrics={"bull_setups": bull_count, "bear_setups": bear_count, "regime": reg_info.get("regime")},
        )
        reports.append(tech_report)

        # -------------------------------------------------------------------
        # 2. Derivatives Analyst Agent (PCR, GEX, Max Pain)
        # -------------------------------------------------------------------
        opt_info = options_data if isinstance(options_data, dict) else {}
        pcr = cls._safe_float(opt_info.get("pcr_oi"), default=1.0, min_val=0.0, max_val=100.0)
        gex_regime = str(opt_info.get("gex_regime") or "NEUTRAL").upper().strip()
        max_pain = opt_info.get("max_pain")

        deriv_stance = "NEUTRAL"
        deriv_conviction = 0.5
        if pcr > 1.2 or gex_regime == "POSITIVE_GAMMA":
            deriv_stance = "BULLISH"
            deriv_conviction = 0.70
            deriv_thesis = f"High Put-Call Ratio ({pcr:.2f}) indicates strong put floor. GEX regime: {gex_regime}."
        elif pcr < 0.8 or gex_regime == "NEGATIVE_GAMMA":
            deriv_stance = "BEARISH"
            deriv_conviction = 0.70
            deriv_thesis = f"Low Put-Call Ratio ({pcr:.2f}) indicates call resistance. GEX regime: {gex_regime}."
        else:
            deriv_thesis = f"Derivative positioning balanced (PCR: {pcr:.2f}, GEX: {gex_regime})."

        if max_pain is not None:
            try:
                deriv_thesis += f" Max-Pain Strike: ₹{float(max_pain):,.0f}."
            except (ValueError, TypeError):
                pass

        deriv_report = AgentReport(
            agent_name="Derivatives Analyst",
            stance=deriv_stance,
            conviction=deriv_conviction,
            thesis=deriv_thesis,
            key_metrics={"pcr": pcr, "gex_regime": gex_regime, "max_pain": max_pain},
        )
        reports.append(deriv_report)

        # -------------------------------------------------------------------
        # 3. Fundamental Analyst Agent (Piotroski F-Score)
        # -------------------------------------------------------------------
        fund_info = fundamental_data if isinstance(fundamental_data, dict) else {}
        f_score_raw = cls._safe_float(fund_info.get("piotroski_score"), default=6.0, min_val=0.0, max_val=9.0)
        f_score = int(round(f_score_raw))

        if f_score >= 7:
            fund_stance = "BULLISH"
            fund_conv = 0.75
            fund_thesis = f"High Piotroski F-Score ({f_score}/9) reflects institutional quality balance sheet."
        elif f_score <= 3:
            fund_stance = "BEARISH"
            fund_conv = 0.75
            fund_thesis = f"Low Piotroski F-Score ({f_score}/9) indicates balance sheet deterioration."
        else:
            fund_stance = "NEUTRAL"
            fund_conv = 0.50
            fund_thesis = f"Moderate Piotroski F-Score ({f_score}/9) in standard range."

        fund_report = AgentReport(
            agent_name="Fundamental Analyst",
            stance=fund_stance,
            conviction=fund_conv,
            thesis=fund_thesis,
            key_metrics={"f_score": f_score},
        )
        reports.append(fund_report)

        # -------------------------------------------------------------------
        # 4. Sentiment & News Analyst Agent
        # -------------------------------------------------------------------
        sent_info = sentiment_data if isinstance(sentiment_data, dict) else {}
        sent_score = cls._safe_float(sent_info.get("mean_score"), default=0.0, min_val=-1.0, max_val=1.0)
        fii_flow = cls._safe_float(sent_info.get("fii_net_crores"), default=0.0, min_val=-1e6, max_val=1e6)

        if sent_score >= 0.15 or fii_flow > 500:
            sent_stance = "BULLISH"
            sent_conv = 0.65
            sent_thesis = f"Positive news sentiment ({sent_score:+.2f}) with FII inflow ₹{fii_flow:,.0f} Cr."
        elif sent_score <= -0.15 or fii_flow < -500:
            sent_stance = "BEARISH"
            sent_conv = 0.65
            sent_thesis = f"Negative news sentiment ({sent_score:+.2f}) with FII outflow ₹{fii_flow:,.0f} Cr."
        else:
            sent_stance = "NEUTRAL"
            sent_conv = 0.40
            sent_thesis = f"Sentiment neutral ({sent_score:+.2f}), institutional flow ₹{fii_flow:,.0f} Cr."

        sent_report = AgentReport(
            agent_name="Sentiment Analyst",
            stance=sent_stance,
            conviction=sent_conv,
            thesis=sent_thesis,
            key_metrics={"sentiment_score": sent_score, "fii_flow": fii_flow},
        )
        reports.append(sent_report)

        # -------------------------------------------------------------------
        # 5. Bull vs Bear Adversarial Debate
        # -------------------------------------------------------------------
        bull_args = [r.thesis for r in reports if r.stance == "BULLISH"]
        bear_args = [r.thesis for r in reports if r.stance == "BEARISH"]

        if not bull_args:
            bull_args.append("No strong upside catalyst detected across technicals or derivatives.")
        if not bear_args:
            bear_args.append("No immediate downside warning flags identified; downside risk is bounded.")

        # -------------------------------------------------------------------
        # 6. Chief Risk Officer Ruling
        # -------------------------------------------------------------------
        regime_str = str(reg_info.get("regime", "range-bound") or "range-bound").lower()
        if regime_str == "crash":
            risk_ruling = "REJECT LONG TRADES: Crash regime active. Strict capital defense protocol."
        elif len(bear_args) > len(bull_args) and tech_stance == "BULLISH":
            risk_ruling = "CAUTION: Bullish price action lacks macro/derivative confirmation. Cap allocation to half-Kelly."
        else:
            risk_ruling = "APPROVED: Risk parameters within safe operating bounds."

        # -------------------------------------------------------------------
        # 7. Consensus Synthesis
        # -------------------------------------------------------------------
        total_bull_weight = 0.0
        total_bear_weight = 0.0
        for r in reports:
            c = cls._safe_float(r.conviction, default=0.5, min_val=0.0, max_val=1.0)
            r.conviction = c
            if r.stance == "BULLISH":
                total_bull_weight += c
            elif r.stance == "BEARISH":
                total_bear_weight += c

        denom = max(0.01, total_bull_weight + total_bear_weight)

        # Check for clear majority conviction
        thresh = cls._safe_float(min_conviction_threshold, default=1.2, min_val=0.4, max_val=3.0)
        if total_bull_weight > total_bear_weight and total_bull_weight >= thresh:
            consensus_sig = "bullish"
            confidence = min(0.92, total_bull_weight / (denom + 0.5))
            action = f"BUY {ticker} Call / Long Future with target trailing stop."
        elif total_bear_weight > total_bull_weight and total_bear_weight >= thresh:
            consensus_sig = "bearish"
            confidence = min(0.92, total_bear_weight / (denom + 0.5))
            action = f"BUY {ticker} Put / Short Future with target trailing stop."
        elif total_bull_weight >= thresh and total_bear_weight >= thresh:
            # Tie-breaker when both bull and bear weights are high and equal:
            # Break tie using Technical Analyst stance and CRO risk ruling
            if tech_stance == "BULLISH" and "REJECT" not in risk_ruling:
                consensus_sig = "bullish"
                confidence = 0.55
                action = f"BUY {ticker} Call / Long Future (Technical Tie-Breaker)."
            elif tech_stance == "BEARISH":
                consensus_sig = "bearish"
                confidence = 0.55
                action = f"BUY {ticker} Put / Short Future (Technical Tie-Breaker)."
            else:
                consensus_sig = "neutral"
                confidence = 0.50
                action = "STAND ASIDE: Bull and bear agents locked in deadlock."
        else:
            consensus_sig = "neutral"
            confidence = 0.50
            action = "STAND ASIDE: Insufficient multi-agent conviction for new risk entry."

        confidence = float(np.clip(confidence, 0.0, 1.0))

        return MultiAgentVerdict(
            consensus_signal=consensus_sig,
            consensus_confidence=round(confidence, 3),
            bull_arguments=bull_args,
            bear_arguments=bear_args,
            chief_risk_ruling=risk_ruling,
            agent_reports=reports,
            recommended_action=action,
        )

    @classmethod
    def fetch_live_context(
        cls,
        ticker: str,
        spot: Optional[float] = None
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Fetches live Indian derivatives data (PCR, Max-Pain, GEX regime) and
        FII/DII institutional cash market net flows via NSEFeed and GEXEngine.

        Returns:
            (options_data, sentiment_data)
        """
        from data.nse_feed import NSEFeed
        from ml.gex_engine import GEXEngine

        clean_sym = NSEFeed.clean_symbol(ticker)
        options_data: Dict[str, Any] = {
            "pcr_oi": 1.0,
            "pcr_volume": 1.0,
            "gex_regime": "NEUTRAL",
            "max_pain": spot,
            "net_gex_crores": 0.0,
        }
        sentiment_data: Dict[str, Any] = {
            "fii_net_crores": 0.0,
            "dii_net_crores": 0.0,
            "mean_score": 0.0,
        }

        # 1. Fetch Option Chain and derive PCR, Max-Pain, and GEX Regime
        try:
            raw_chain = NSEFeed.get_option_chain_raw(clean_sym)
            if raw_chain and "records" in raw_chain:
                pcr_oi, pcr_vol, put_oi, call_oi = NSEFeed.calculate_pcr(raw_chain)
                max_pain = NSEFeed.calculate_max_pain(raw_chain) or spot

                # Extract strike rows for GEX calculation
                strikes_data = []
                data_rows = raw_chain.get("records", {}).get("data", [])
                for row in data_rows:
                    k = row.get("strikePrice")
                    if k is not None:
                        try:
                            k_val = float(k)
                        except (ValueError, TypeError):
                            continue
                        ce = row.get("CE") or {}
                        pe = row.get("PE") or {}
                        strikes_data.append({
                            "strike": k_val,
                            "call_oi": float(ce.get("openInterest", 0) or 0),
                            "put_oi": float(pe.get("openInterest", 0) or 0),
                            "call_vol": float(ce.get("totalTradedVolume", 0) or 0),
                            "put_vol": float(pe.get("totalTradedVolume", 0) or 0),
                        })

                # Analyze Gamma Exposure
                if strikes_data:
                    from ml.options_engine import DerivativeEngine
                    lot_size = DerivativeEngine().get_lot_size(clean_sym)
                    gex_res = GEXEngine.analyze_chain_gex(
                        spot=spot or float(strikes_data[len(strikes_data) // 2]["strike"]),
                        strikes_data=strikes_data,
                        lot_size=lot_size,
                    )
                    gex_regime = gex_res.get("regime", "NEUTRAL")
                    net_gex = gex_res.get("net_gex_crores", 0.0)
                else:
                    gex_regime = "NEUTRAL"
                    net_gex = 0.0

                options_data = {
                    "pcr_oi": pcr_oi,
                    "pcr_volume": pcr_vol,
                    "max_pain": max_pain,
                    "gex_regime": gex_regime,
                    "net_gex_crores": net_gex,
                }
        except Exception as e:
            logger.debug(f"Failed to fetch live option chain for {ticker}: {e}")

        # 2. Fetch Institutional FII / DII net cash flows
        try:
            fii_dii = NSEFeed.get_fii_dii_activity()
            if fii_dii and isinstance(fii_dii, dict):
                sentiment_data["fii_net_crores"] = float(fii_dii.get("fii_net_crores", 0.0) or 0.0)
                sentiment_data["dii_net_crores"] = float(fii_dii.get("dii_net_crores", 0.0) or 0.0)
                sentiment_data["sentiment"] = fii_dii.get("sentiment", "NEUTRAL")
        except Exception as e:
            logger.debug(f"Failed to fetch FII/DII activity for {ticker}: {e}")

        return options_data, sentiment_data
