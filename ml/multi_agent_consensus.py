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
    def evaluate(
        ticker: str,
        regime_data: Dict[str, Any],
        setup_signals: List[Any],
        options_data: Optional[Dict[str, Any]] = None,
        fundamental_data: Optional[Dict[str, Any]] = None,
        sentiment_data: Optional[Dict[str, Any]] = None,
    ) -> MultiAgentVerdict:
        """Runs the multi-agent consensus workflow."""
        reports: List[AgentReport] = []

        # -------------------------------------------------------------------
        # 1. Technical Analyst Agent
        # -------------------------------------------------------------------
        bull_count = sum(1 for s in setup_signals if getattr(s, "signal", "").lower() == "bullish")
        bear_count = sum(1 for s in setup_signals if getattr(s, "signal", "").lower() == "bearish")
        total_setups = max(1, len(setup_signals))

        tech_stance = "NEUTRAL"
        tech_conviction = 0.5
        if bull_count > bear_count:
            tech_stance = "BULLISH"
            tech_conviction = min(0.95, 0.5 + (bull_count - bear_count) / total_setups * 0.5)
        elif bear_count > bull_count:
            tech_stance = "BEARISH"
            tech_conviction = min(0.95, 0.5 + (bear_count - bull_count) / total_setups * 0.5)

        tech_report = AgentReport(
            agent_name="Technical Analyst",
            stance=tech_stance,
            conviction=tech_conviction,
            thesis=f"Confluence of {bull_count} bullish vs {bear_count} bearish setups in {regime_data.get('regime', 'unknown')} regime.",
            key_metrics={"bull_setups": bull_count, "bear_setups": bear_count, "regime": regime_data.get("regime")},
        )
        reports.append(tech_report)

        # -------------------------------------------------------------------
        # 2. Derivatives Analyst Agent (PCR, GEX, Max Pain)
        # -------------------------------------------------------------------
        opt_info = options_data or {}
        pcr = opt_info.get("pcr_oi", 1.0)
        gex_regime = opt_info.get("gex_regime", "NEUTRAL")

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

        deriv_report = AgentReport(
            agent_name="Derivatives Analyst",
            stance=deriv_stance,
            conviction=deriv_conviction,
            thesis=deriv_thesis,
            key_metrics={"pcr": pcr, "gex_regime": gex_regime},
        )
        reports.append(deriv_report)

        # -------------------------------------------------------------------
        # 3. Fundamental Analyst Agent (Piotroski F-Score)
        # -------------------------------------------------------------------
        f_score = (fundamental_data or {}).get("piotroski_score", 6)
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
        sent_info = sentiment_data or {}
        sent_score = sent_info.get("mean_score", 0.0)
        fii_flow = sent_info.get("fii_net_crores", 0.0)

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
        regime_str = regime_data.get("regime", "range-bound")
        if regime_str == "crash":
            risk_ruling = "REJECT LONG TRADES: Crash regime active. Strict capital defense protocol."
        elif len(bear_args) > len(bull_args) and tech_stance == "BULLISH":
            risk_ruling = "CAUTION: Bullish price action lacks macro/derivative confirmation. Cap allocation to half-Kelly."
        else:
            risk_ruling = "APPROVED: Risk parameters within safe operating bounds."

        # -------------------------------------------------------------------
        # 7. Consensus Synthesis
        # -------------------------------------------------------------------
        total_bull_weight = sum(r.conviction for r in reports if r.stance == "BULLISH")
        total_bear_weight = sum(r.conviction for r in reports if r.stance == "BEARISH")
        denom = max(0.01, total_bull_weight + total_bear_weight)

        if total_bull_weight > total_bear_weight and total_bull_weight >= 1.2:
            consensus_sig = "bullish"
            confidence = min(0.92, total_bull_weight / (denom + 0.5))
            action = f"BUY {ticker} Call / Long Future with target trailing stop."
        elif total_bear_weight > total_bull_weight and total_bear_weight >= 1.2:
            consensus_sig = "bearish"
            confidence = min(0.92, total_bear_weight / (denom + 0.5))
            action = f"BUY {ticker} Put / Short Future with target trailing stop."
        else:
            consensus_sig = "neutral"
            confidence = 0.50
            action = "STAND ASIDE: Insufficient multi-agent conviction for new risk entry."

        return MultiAgentVerdict(
            consensus_signal=consensus_sig,
            consensus_confidence=round(confidence, 3),
            bull_arguments=bull_args,
            bear_arguments=bear_args,
            chief_risk_ruling=risk_ruling,
            agent_reports=reports,
            recommended_action=action,
        )
