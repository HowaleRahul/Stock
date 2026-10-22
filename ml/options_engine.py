"""
Derivative & Options Engine — Smart F&O Recommendation and Reinforcement Learning

Translates Spot Index signals into lot-size-aware Index Futures and Options
recommendations (Buy Call / Buy Put / Long Future / Short Future) calibrated
to user capital.

Features:
- Smart Derivative Selector: Auto-routes to Options for budget preservation
  (e.g. ₹10k/₹25k) or Futures when capital safely satisfies margin requirements.
- Dynamic Strike Hunter: Evaluates ITM (high delta efficiency), ATM (gamma explosion),
  and OTM (budget-fitting lower premium) strikes.
- F&O Contextual Bandit (FOLearner): Continuously learns which strike and derivative
  type maximizes risk-adjusted returns per market regime, persisting weights to disk.
- Live Option MTM Re-pricing: Uses Black-Scholes with real-time underlying index ticks
  and elapsed time for ticking MTM PnL and Greek tracking.
"""

from __future__ import annotations

import json
import os
import math
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple

import scipy.stats as si
import numpy as np

from ml.risk_engine import TradePlan

logger = logging.getLogger("trading.options_engine")

FO_WEIGHTS_FILE = "ml/models/fo_weights.json"


# ===========================================================================
# 1. Data Structures
# ===========================================================================

@dataclass
class DerivativeTradePlan:
    """A complete derivative (Options or Futures) trade recommendation."""
    original_spot_plan: TradePlan

    instrument_type: str        # "OPTION" or "FUTURE"
    underlying_ticker: str      # "NIFTY", "BANKNIFTY", etc.
    contract_symbol: str        # e.g. "NIFTY 22800 CE", "BANKNIFTY FUT"
    direction: str              # "LONG" or "SHORT"
    option_type: str            # "CE", "PE", or "FUT"
    strike_price: float         # Strike price (0 for Futures)
    strike_type: str            # "ITM", "ATM", "OTM", or "FUT"

    lot_size: int               # NSE lot size (NIFTY: 25, BANKNIFTY: 15)
    lots_to_trade: int          # Number of lots
    total_quantity: int         # lots * lot_size

    # Pricing & Premium
    entry_price: float          # Entry option premium OR Future entry price
    target_price: float         # Option target premium OR Future target price
    stop_loss_price: float      # Option SL premium OR Future SL price

    # Margins and Capital
    margin_or_premium_required: float  # Capital deployed
    max_loss_amount: float
    max_profit_amount: float
    risk_reward_ratio: float

    # Greeks (Options only, 0 for Futures)
    delta: float = 0.0
    theta: float = 0.0
    gamma: float = 0.0
    vega: float = 0.0
    days_to_expiry: float = 7.0
    iv: float = 0.15

    is_approved: bool = True
    rejection_reasons: List[str] = field(default_factory=list)
    reasoning: str = ""

    # Backwards compatibility properties
    @property
    def option_symbol(self) -> str:
        return self.contract_symbol

    @property
    def lots_to_buy(self) -> int:
        return self.lots_to_trade

    @property
    def total_premium_invested(self) -> float:
        return self.margin_or_premium_required

    @property
    def entry_premium(self) -> float:
        return self.entry_price

    @property
    def stop_loss_premium(self) -> float:
        return self.stop_loss_price

    @property
    def target_premium(self) -> float:
        return self.target_price

    @property
    def original_plan(self) -> TradePlan:
        return self.original_spot_plan

    def to_dict(self) -> Dict[str, Any]:
        return {
            "instrument_type": self.instrument_type,
            "underlying_ticker": self.underlying_ticker,
            "contract_symbol": self.contract_symbol,
            "direction": self.direction,
            "option_type": self.option_type,
            "strike_price": round(self.strike_price, 2),
            "strike_type": self.strike_type,
            "lot_size": self.lot_size,
            "lots_to_trade": self.lots_to_trade,
            "total_quantity": self.total_quantity,
            "entry_price": round(self.entry_price, 2),
            "target_price": round(self.target_price, 2),
            "stop_loss_price": round(self.stop_loss_price, 2),
            "margin_or_premium_required": round(self.margin_or_premium_required, 2),
            "max_loss_amount": round(self.max_loss_amount, 2),
            "max_profit_amount": round(self.max_profit_amount, 2),
            "risk_reward_ratio": round(self.risk_reward_ratio, 2),
            "delta": round(self.delta, 4),
            "theta": round(self.theta, 4),
            "gamma": round(self.gamma, 6),
            "vega": round(self.vega, 4),
            "days_to_expiry": self.days_to_expiry,
            "iv": round(self.iv, 4),
            "is_approved": self.is_approved,
            "rejection_reasons": self.rejection_reasons,
            "reasoning": self.reasoning,
        }


# Backwards compatibility alias
OptionsTradePlan = DerivativeTradePlan


# ===========================================================================
# 2. F&O Contextual Bandit Reinforcement Learner (FOLearner)
# ===========================================================================

class FOLearner:
    """
    Learns optimal derivative instrument (Futures vs Options) and strike
    (ITM vs ATM vs OTM) per index and market regime from paper trading outcomes.
    """

    def __init__(self, state_file: str = FO_WEIGHTS_FILE):
        self.state_file = state_file
        self.state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load FO weights: {e}")

        # Default prior states for indices
        default_strikes = {
            "ITM": {"alpha": 4.0, "beta": 2.0, "ewma": 0.12, "n": 6},
            "ATM": {"alpha": 5.0, "beta": 2.0, "ewma": 0.15, "n": 7},
            "OTM": {"alpha": 3.0, "beta": 3.0, "ewma": 0.05, "n": 6},
            "FUTURES": {"alpha": 4.0, "beta": 2.0, "ewma": 0.10, "n": 6},
        }
        return {
            "version": 1,
            "last_update": None,
            "total_fo_trades": 0,
            "options_wins": 0,
            "options_losses": 0,
            "futures_wins": 0,
            "futures_losses": 0,
            "weights": {
                "NIFTY": {"trending": dict(default_strikes), "rangebound": dict(default_strikes)},
                "BANKNIFTY": {"trending": dict(default_strikes), "rangebound": dict(default_strikes)},
                "SENSEX": {"trending": dict(default_strikes), "rangebound": dict(default_strikes)},
                "FINNIFTY": {"trending": dict(default_strikes), "rangebound": dict(default_strikes)},
            }
        }

    def _save_state(self):
        dir_name = os.path.dirname(self.state_file) or "."
        os.makedirs(dir_name, exist_ok=True)
        tmp = f"{self.state_file}.tmp"
        try:
            import datetime
            self.state["last_update"] = datetime.datetime.now().isoformat()
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.state_file)
        except Exception as e:
            logger.error(f"Failed to save FO weights: {e}")
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except Exception:
                    pass

    def get_strike_rankings(self, index: str, regime: str = "trending") -> List[Tuple[str, float]]:
        """
        Returns ranked list of strike types [(strike_type, sampled_score)]
        using Thompson Sampling from Beta posterior.
        """
        idx_key = "SENSEX" if "SENSEX" in index.upper() or "BSESN" in index.upper() else ("BANKNIFTY" if "BANK" in index.upper() else ("FINNIFTY" if "FIN" in index.upper() else "NIFTY"))
        reg_key = "rangebound" if "range" in regime.lower() else "trending"

        idx_weights = self.state.get("weights", {}).get(idx_key, {})
        reg_weights = idx_weights.get(reg_key, {})

        rankings = []
        for strike in ["ITM", "ATM", "OTM"]:
            node = reg_weights.get(strike, {"alpha": 3.0, "beta": 2.0, "ewma": 0.10})
            a = max(1.0, float(node.get("alpha", 3.0)))
            b = max(1.0, float(node.get("beta", 2.0)))
            sample = np.random.beta(a, b)
            ewma = float(node.get("ewma", 0.0))
            score = 0.6 * sample + 0.4 * max(0.0, ewma)
            rankings.append((strike, score))

        # Sort descending by score
        rankings.sort(key=lambda x: x[1], reverse=True)
        return rankings

    def update_from_trade(self, trade: Dict[str, Any], net_pnl_pct: float):
        """Update reinforcement weights upon trade exit."""
        inst_type = trade.get("instrument_type", "OPTION")
        strike_type = trade.get("strike_type", "ATM")
        ticker = trade.get("ticker", "NIFTY")
        regime = trade.get("regime", "trending")

        idx_key = "SENSEX" if "SENSEX" in ticker.upper() or "BSESN" in ticker.upper() else ("BANKNIFTY" if "BANK" in ticker.upper() else ("FINNIFTY" if "FIN" in ticker.upper() else "NIFTY"))
        reg_key = "rangebound" if "range" in str(regime).lower() else "trending"

        if idx_key not in self.state.setdefault("weights", {}):
            self.state["weights"][idx_key] = {}
        if reg_key not in self.state["weights"][idx_key]:
            self.state["weights"][idx_key][reg_key] = {}

        target_key = "FUTURES" if inst_type == "FUTURE" else strike_type
        node = self.state["weights"][idx_key][reg_key].setdefault(target_key, {
            "alpha": 3.0, "beta": 2.0, "ewma": 0.0, "n": 0
        })

        is_win = net_pnl_pct > 0
        # Beta update
        if is_win:
            node["alpha"] = float(node.get("alpha", 3.0)) + 1.0
            if inst_type == "OPTION":
                self.state["options_wins"] = self.state.get("options_wins", 0) + 1
            else:
                self.state["futures_wins"] = self.state.get("futures_wins", 0) + 1
        else:
            node["beta"] = float(node.get("beta", 2.0)) + 1.0
            if inst_type == "OPTION":
                self.state["options_losses"] = self.state.get("options_losses", 0) + 1
            else:
                self.state["futures_losses"] = self.state.get("futures_losses", 0) + 1

        # EWMA update (decay = 0.15)
        old_ewma = float(node.get("ewma", 0.0))
        node["ewma"] = 0.85 * old_ewma + 0.15 * net_pnl_pct
        node["n"] = int(node.get("n", 0)) + 1
        self.state["total_fo_trades"] = self.state.get("total_fo_trades", 0) + 1

        self._save_state()
        logger.info(
            f"[FO LEARNING UPDATE] {idx_key} {target_key} ({reg_key}): "
            f"PnL: {net_pnl_pct*100:+.2f}% | alpha={node['alpha']:.1f}, beta={node['beta']:.1f}, ewma={node['ewma']:.3f}"
        )

    def get_summary(self) -> Dict[str, Any]:
        total_opt = self.state.get("options_wins", 0) + self.state.get("options_losses", 0)
        opt_wr = (self.state.get("options_wins", 0) / total_opt * 100) if total_opt > 0 else 0.0

        total_fut = self.state.get("futures_wins", 0) + self.state.get("futures_losses", 0)
        fut_wr = (self.state.get("futures_wins", 0) / total_fut * 100) if total_fut > 0 else 0.0

        return {
            "total_fo_trades": self.state.get("total_fo_trades", 0),
            "options_win_rate": round(opt_wr, 1),
            "options_total": total_opt,
            "futures_win_rate": round(fut_wr, 1),
            "futures_total": total_fut,
            "last_update": self.state.get("last_update")
        }


# ===========================================================================
# 3. Main Derivative Engine
# ===========================================================================

class DerivativeEngine:
    """
    Translates Index Spot signals into lot-size-aware Index Futures and Options
    trade plans, dynamically fitted to user budget and regime.
    """

    LOT_SIZES = {
        "NIFTY": 25,
        "^NSEI": 25,
        "BANKNIFTY": 15,
        "^NSEBANK": 15,
        "SENSEX": 10,
        "^BSESN": 10,
        "FINNIFTY": 25,
        "MIDCPNIFTY": 50,
    }

    STRIKE_INTERVALS = {
        "NIFTY": 50,
        "^NSEI": 50,
        "BANKNIFTY": 100,
        "^NSEBANK": 100,
        "SENSEX": 100,
        "^BSESN": 100,
        "FINNIFTY": 50,
        "MIDCPNIFTY": 25,
    }

    # Futures Span + Exposure margin requirement (~14% to 16% on NSE/BSE)
    FUTURES_MARGIN_RATES = {
        "NIFTY": 0.15,
        "^NSEI": 0.15,
        "BANKNIFTY": 0.16,
        "^NSEBANK": 0.16,
        "SENSEX": 0.15,
        "^BSESN": 0.15,
        "FINNIFTY": 0.15,
        "MIDCPNIFTY": 0.16,
    }

    DAYS_TO_EXPIRY = 7.0       # Current weekly expiry
    RISK_FREE_RATE = 0.065     # 6.5% Indian Repo Rate
    DEFAULT_IV = 0.14          # 14% India VIX proxy baseline

    def __init__(self):
        self.fo_learner = FOLearner()

    def _round_to_nearest(self, x: float, base: int) -> int:
        return int(base * round(x / base))

    def _normalize_ticker(self, ticker: str) -> str:
        t = ticker.upper().replace("^", "")
        if "BSESN" in t or "SENSEX" in t:
            return "SENSEX"
        if "NSEBANK" in t or "BANKNIFTY" in t:
            return "BANKNIFTY"
        if "NSEI" in t or "NIFTY" in t:
            return "NIFTY"
        if "FIN" in t:
            return "FINNIFTY"
        if "MID" in t:
            return "MIDCPNIFTY"
        return t

    def is_derivative_supported(self, ticker: str) -> bool:
        norm = self._normalize_ticker(ticker)
        return norm in self.LOT_SIZES

    def get_lot_size(self, ticker: str) -> int:
        norm = self._normalize_ticker(ticker)
        return self.LOT_SIZES.get(norm, 25)

    def get_strike_interval(self, ticker: str) -> int:
        norm = self._normalize_ticker(ticker)
        return self.STRIKE_INTERVALS.get(norm, 50)

    # -----------------------------------------------------------------------
    # Black-Scholes Pricing & Greeks
    # -----------------------------------------------------------------------

    def black_scholes(
        self,
        S: float,
        K: float,
        T: float,
        r: float,
        sigma: float,
        option_type: str = "CE"
    ) -> Dict[str, float]:
        """
        Calculate Theoretical Option Premium and Greeks using Black-Scholes-Merton.
        """
        if T <= 0 or S <= 0 or K <= 0 or sigma <= 0:
            return {"premium": 0.01, "delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}

        denom = sigma * np.sqrt(T)
        if denom <= 1e-9:
            return {"premium": 0.01, "delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}

        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / denom
        d2 = d1 - denom

        try:
            if option_type == "CE":
                premium = (S * si.norm.cdf(d1, 0.0, 1.0) - K * np.exp(-r * T) * si.norm.cdf(d2, 0.0, 1.0))
                delta = si.norm.cdf(d1, 0.0, 1.0)
                theta = (- (S * si.norm.pdf(d1, 0.0, 1.0) * sigma) / (2 * np.sqrt(T))
                         - r * K * np.exp(-r * T) * si.norm.cdf(d2, 0.0, 1.0))
            else:  # "PE"
                premium = (K * np.exp(-r * T) * si.norm.cdf(-d2, 0.0, 1.0) - S * si.norm.cdf(-d1, 0.0, 1.0))
                delta = -si.norm.cdf(-d1, 0.0, 1.0)
                theta = (- (S * si.norm.pdf(d1, 0.0, 1.0) * sigma) / (2 * np.sqrt(T))
                         + r * K * np.exp(-r * T) * si.norm.cdf(-d2, 0.0, 1.0))

            gamma = si.norm.pdf(d1, 0.0, 1.0) / (S * denom)
            vega = S * si.norm.pdf(d1, 0.0, 1.0) * np.sqrt(T)
            theta_per_day = theta / 365.0

            if math.isnan(premium) or math.isnan(delta):
                return {"premium": 0.01, "delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}

            return {
                "premium": max(0.05, float(premium)),
                "delta": float(delta),
                "gamma": float(gamma) if not math.isnan(gamma) else 0.0,
                "theta": float(theta_per_day) if not math.isnan(theta_per_day) else 0.0,
                "vega": float(vega / 100.0) if not math.isnan(vega) else 0.0
            }
        except Exception:
            return {"premium": 0.01, "delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}

    # Alias for private method call compatibility
    _black_scholes = black_scholes

    # Backwards compatibility alias for single options plan generation
    def generate_options_plan(
        self,
        spot_plan: TradePlan,
        capital: Optional[float] = None,
        iv: Optional[float] = None,
        strike_pref: str = "AUTO"
    ) -> DerivativeTradePlan:
        """Alias for generate_derivative_plan with derivative_type='OPTIONS'."""
        cap = capital if capital is not None else getattr(spot_plan, "capital", 50000.0)
        return self.generate_derivative_plan(
            spot_plan=spot_plan,
            capital=cap,
            derivative_type="OPTIONS",
            strike_pref=strike_pref,
            iv=iv
        )

    # -----------------------------------------------------------------------
    # Core Plan Generator: Futures or Options dynamically selected
    # -----------------------------------------------------------------------

    def generate_derivative_plan(
        self,
        spot_plan: TradePlan,
        capital: float,
        derivative_type: str = "AUTO",      # "AUTO", "OPTIONS", "FUTURES"
        strike_pref: str = "AUTO",          # "AUTO", "ITM", "ATM", "OTM"
        regime: str = "trending",
        iv: Optional[float] = None,
    ) -> DerivativeTradePlan:
        """
        Creates a lot-sized, risk-controlled Derivative trade plan.
        Selects Futures or Options and the optimal strike according to budget.
        """
        underlying = self._normalize_ticker(spot_plan.ticker)
        if not self.is_derivative_supported(underlying):
            return self._build_unsupported_plan(spot_plan, underlying)

        lot_size = self.get_lot_size(underlying)
        interval = self.get_strike_interval(underlying)
        spot_price = spot_plan.entry_price
        contract_value = spot_price * lot_size
        margin_rate = self.FUTURES_MARGIN_RATES.get(underlying, 0.15)
        futures_margin = contract_value * margin_rate

        # 1. Decide Instrument Type: FUTURES vs OPTIONS
        chosen_instrument = derivative_type.upper()
        if chosen_instrument == "AUTO":
            # If capital is insufficient for Futures margin (or margin uses > 50% of account),
            # strictly auto-route to Options!
            if capital < futures_margin or futures_margin > (capital * 0.50):
                chosen_instrument = "OPTIONS"
            else:
                # With large capital (e.g. ₹2.5L+ or ₹10L), check RL weights or trend strength
                if "trend" in regime.lower() and spot_plan.ai_probability >= 0.75:
                    chosen_instrument = "FUTURES"
                else:
                    chosen_instrument = "OPTIONS"

        # 2. Dispatch to specific plan builder
        if chosen_instrument == "FUTURES":
            return self._build_futures_plan(
                spot_plan=spot_plan,
                underlying=underlying,
                capital=capital,
                futures_margin=futures_margin,
                lot_size=lot_size,
                regime=regime
            )
        else:
            return self._build_options_plan(
                spot_plan=spot_plan,
                underlying=underlying,
                capital=capital,
                lot_size=lot_size,
                interval=interval,
                strike_pref=strike_pref,
                regime=regime,
                iv=iv or self.DEFAULT_IV
            )

    # -----------------------------------------------------------------------
    # Futures Plan Builder
    # -----------------------------------------------------------------------

    def _build_futures_plan(
        self,
        spot_plan: TradePlan,
        underlying: str,
        capital: float,
        futures_margin: float,
        lot_size: int,
        regime: str
    ) -> DerivativeTradePlan:
        direction = spot_plan.direction.upper()
        contract_symbol = f"{underlying} FUT"

        # Affordability check for 1 lot of futures
        rejections = []
        is_approved = True

        if capital < futures_margin:
            is_approved = False
            rejections.append(
                f"Futures Margin Deficit: 1 lot of {underlying} Futures requires ₹{futures_margin:,.2f} margin "
                f"(Contract Value: ₹{spot_plan.entry_price * lot_size:,.2f}). Your capital is ₹{capital:,.2f}. "
                f"Auto-switch to Options (requires only premium ~₹2.5k - ₹5k) or increase capital."
            )

        # Max loss & profit based on point stop-loss
        pts_risk = abs(spot_plan.entry_price - spot_plan.stop_loss)
        pts_reward = abs(spot_plan.take_profit - spot_plan.entry_price)
        max_loss = pts_risk * lot_size
        max_profit = pts_reward * lot_size
        rr = max_profit / max_loss if max_loss > 0 else 0.0

        # Safety check: Futures risk per trade should not exceed 2% of capital
        if max_loss > (capital * 0.025):
            is_approved = False
            rejections.append(
                f"Futures Risk Overlimit: Stop-loss distance ({pts_risk:.1f} pts = ₹{max_loss:,.2f}) "
                f"exceeds safe 2.5% risk limit of account capital (₹{capital * 0.025:,.2f})."
            )

        reasoning = (
            f"{'✅ APPROVED' if is_approved else '⛔ REJECTED'}: {contract_symbol} ({direction})\n"
            f"  📈 Contract Value: ₹{spot_plan.entry_price * lot_size:,.2f} | Margin: ₹{futures_margin:,.2f}\n"
            f"  🎯 Target: ₹{spot_plan.take_profit:,.2f} (+₹{max_profit:,.2f}) | 🛑 SL: ₹{spot_plan.stop_loss:,.2f} (-₹{max_loss:,.2f})\n"
            f"  ⚖️  Futures R:R: {rr:.2f}:1 | Lots: 1 ({lot_size} qty) | Delta: 1.0 (Full directional leverage)"
        )
        if rejections:
            reasoning += "\n  " + "\n  ".join(f"• {r}" for r in rejections)

        return DerivativeTradePlan(
            original_spot_plan=spot_plan,
            instrument_type="FUTURE",
            underlying_ticker=underlying,
            contract_symbol=contract_symbol,
            direction=direction,
            option_type="FUT",
            strike_price=0.0,
            strike_type="FUT",
            lot_size=lot_size,
            lots_to_trade=1,
            total_quantity=lot_size,
            entry_price=spot_plan.entry_price,
            target_price=spot_plan.take_profit,
            stop_loss_price=spot_plan.stop_loss,
            margin_or_premium_required=futures_margin,
            max_loss_amount=max_loss,
            max_profit_amount=max_profit,
            risk_reward_ratio=rr,
            delta=1.0 if direction == "LONG" else -1.0,
            theta=0.0,
            gamma=0.0,
            vega=0.0,
            is_approved=is_approved,
            rejection_reasons=rejections,
            reasoning=reasoning
        )

    # -----------------------------------------------------------------------
    # Options Plan Builder with Smart Strike Selection
    # -----------------------------------------------------------------------

    def _build_options_plan(
        self,
        spot_plan: TradePlan,
        underlying: str,
        capital: float,
        lot_size: int,
        interval: int,
        strike_pref: str,
        regime: str,
        iv: float
    ) -> DerivativeTradePlan:
        direction = "LONG" if spot_plan.direction in ("LONG", "bullish") else "SHORT"
        option_type = "CE" if direction == "LONG" else "PE"
        spot = spot_plan.entry_price
        atm_strike = self._round_to_nearest(spot, interval)

        T = self.DAYS_TO_EXPIRY / 365.0
        r = self.RISK_FREE_RATE
        sigma = iv

        # Calculate Candidate Strikes: ITM, ATM, OTM1, OTM2
        if option_type == "CE":
            candidate_strikes = {
                "ITM": atm_strike - interval,
                "ATM": atm_strike,
                "OTM": atm_strike + interval,
                "OTM2": atm_strike + (2 * interval)
            }
        else:
            candidate_strikes = {
                "ITM": atm_strike + interval,
                "ATM": atm_strike,
                "OTM": atm_strike - interval,
                "OTM2": atm_strike - (2 * interval)
            }

        # Determine budget limit based on capital tier
        from ml.risk_engine import RiskEngine
        tier = RiskEngine.get_capital_tier(capital)
        max_alloc_amount = capital * tier["max_allocation_pct"]
        max_risk_amount = capital * tier["max_risk_pct"]

        # Strike Selection Strategy
        chosen_strike_type = "ATM"
        chosen_strike = atm_strike
        chosen_bs = None

        # If user explicitly requested strike preference
        pref_upper = strike_pref.upper()
        if pref_upper in ("ITM", "ATM", "OTM"):
            candidate_keys = [pref_upper]
        else:
            # Auto: Order strikes by RL learned score for current regime
            rl_rankings = [s[0] for s in self.fo_learner.get_strike_rankings(underlying, regime)]
            candidate_keys = rl_rankings + ["OTM", "OTM2"]

        # Evaluate candidate strikes against user budget
        for sk in candidate_keys:
            stk_price = candidate_strikes.get(sk, atm_strike)
            bs = self.black_scholes(spot, stk_price, T, r, sigma, option_type)
            cost = bs["premium"] * lot_size

            # Check if this strike can fit into the user's budget!
            if cost <= max_alloc_amount or (capital <= 25000 and cost <= capital * 0.45):
                chosen_strike_type = sk
                chosen_strike = stk_price
                chosen_bs = bs
                break

        # Fallback if none fitted comfortably: pick the cheapest OTM strike
        if not chosen_bs:
            chosen_strike_type = "OTM"
            chosen_strike = candidate_strikes["OTM"]
            chosen_bs = self.black_scholes(spot, chosen_strike, T, r, sigma, option_type)

        contract_symbol = f"{underlying} {chosen_strike} {option_type}"
        entry_premium = chosen_bs["premium"]
        total_cost = entry_premium * lot_size

        # Premium at underlying Target and Stop Loss
        T_target = max(0.001, (self.DAYS_TO_EXPIRY - 1.5) / 365.0)
        bs_target = self.black_scholes(spot_plan.take_profit, chosen_strike, T_target, r, sigma, option_type)
        target_premium = max(entry_premium * 1.10, bs_target["premium"])

        T_sl = max(0.001, (self.DAYS_TO_EXPIRY - 1.0) / 365.0)
        bs_sl = self.black_scholes(spot_plan.stop_loss, chosen_strike, T_sl, r, sigma, option_type)
        stop_loss_premium = min(entry_premium * 0.90, bs_sl["premium"])

        # Risk and Reward amounts
        risk_per_qty = max(1.0, entry_premium - stop_loss_premium)
        reward_per_qty = max(1.0, target_premium - entry_premium)
        max_loss = risk_per_qty * lot_size
        max_profit = reward_per_qty * lot_size
        rr = max_profit / max_loss if max_loss > 0 else 0.0

        # Quality Gating
        rejections = []
        is_approved = True

        # Gate 1: Affordability check
        if total_cost > capital:
            is_approved = False
            rejections.append(
                f"Capital Insufficiency: 1 lot of {contract_symbol} costs ₹{total_cost:,.2f} "
                f"(Premium ₹{entry_premium:.2f} × {lot_size}). Available capital: ₹{capital:,.2f}."
            )

        # Gate 2: Theta decay check relative to expected gain
        hold_days = max(1.0, spot_plan.max_hold_bars / 6.25)
        total_theta = abs(chosen_bs["theta"]) * hold_days
        if reward_per_qty > 0 and (total_theta / reward_per_qty) > 0.45:
            is_approved = False
            rejections.append(
                f"Theta Drag Warning: Expected theta decay (₹{total_theta:.2f} over {hold_days:.1f} days) "
                f"absorbs >45% of expected profit. Switch to ITM strike or shorter hold."
            )

        # Gate 3: R:R check (demand 1.4:1 for Options)
        if rr < 1.3:
            is_approved = False
            rejections.append(f"Options R:R {rr:.2f}:1 is below required 1.3:1 asymmetric edge.")

        # Gate 4: Delta floor check
        if abs(chosen_bs["delta"]) < 0.20:
            is_approved = False
            rejections.append(f"Delta {chosen_bs['delta']:.2f} is too low; contract lacks directional sensitivity.")

        reasoning = (
            f"{'✅ APPROVED' if is_approved else '⛔ REJECTED'}: {contract_symbol} ({chosen_strike_type})\n"
            f"  ⚡ Delta: {chosen_bs['delta']:.3f} | ⏳ Theta: ₹{chosen_bs['theta']:.2f}/day | IV: {sigma*100:.1f}%\n"
            f"  💰 Entry Prem: ₹{entry_premium:,.2f} | Target: ₹{target_premium:,.2f} | SL: ₹{stop_loss_premium:,.2f}\n"
            f"  📊 Invested: ₹{total_cost:,.2f} (1 lot = {lot_size} qty) | Max Risk: ₹{max_loss:,.2f} | R:R: {rr:.2f}:1\n"
            f"  🎯 Spot Underlying: {spot_plan.ticker} @ ₹{spot:,.2f} ({spot_plan.direction})"
        )
        if rejections:
            reasoning += "\n  " + "\n  ".join(f"• {r}" for r in rejections)

        return DerivativeTradePlan(
            original_spot_plan=spot_plan,
            instrument_type="OPTION",
            underlying_ticker=underlying,
            contract_symbol=contract_symbol,
            direction=direction,
            option_type=option_type,
            strike_price=chosen_strike,
            strike_type=chosen_strike_type,
            lot_size=lot_size,
            lots_to_trade=1,
            total_quantity=lot_size,
            entry_price=entry_premium,
            target_price=target_premium,
            stop_loss_price=stop_loss_premium,
            margin_or_premium_required=total_cost,
            max_loss_amount=max_loss,
            max_profit_amount=max_profit,
            risk_reward_ratio=rr,
            delta=chosen_bs["delta"],
            theta=chosen_bs["theta"],
            gamma=chosen_bs["gamma"],
            vega=chosen_bs["vega"],
            days_to_expiry=self.DAYS_TO_EXPIRY,
            iv=sigma,
            is_approved=is_approved,
            rejection_reasons=rejections,
            reasoning=reasoning
        )

    # -----------------------------------------------------------------------
    # Live Option MTM Re-pricing
    # -----------------------------------------------------------------------

    def calculate_option_mtm(
        self,
        trade: Dict[str, Any],
        current_spot: float,
        days_elapsed: float = 0.1
    ) -> Tuple[float, float]:
        """
        Re-prices an active option trade using Black-Scholes given current spot
        and elapsed holding time. Returns (live_premium, live_delta).
        """
        strike = trade.get("strike", 0.0)
        option_type = trade.get("option_type", "CE")
        iv = trade.get("iv", self.DEFAULT_IV)
        days_left = max(0.01, self.DAYS_TO_EXPIRY - days_elapsed)
        T = days_left / 365.0

        if strike <= 0 or current_spot <= 0:
            return trade.get("entry_price", 0.0), trade.get("delta", 0.5)

        bs = self.black_scholes(current_spot, strike, T, self.RISK_FREE_RATE, iv, option_type)
        return bs["premium"], bs["delta"]

    def _build_unsupported_plan(self, spot_plan: TradePlan, ticker: str) -> DerivativeTradePlan:
        return DerivativeTradePlan(
            original_spot_plan=spot_plan,
            instrument_type="OPTION",
            underlying_ticker=ticker,
            contract_symbol=f"{ticker} [NO_FO]",
            direction=spot_plan.direction,
            option_type="NONE",
            strike_price=0.0,
            strike_type="NONE",
            lot_size=1,
            lots_to_trade=0,
            total_quantity=0,
            entry_price=0.0,
            target_price=0.0,
            stop_loss_price=0.0,
            margin_or_premium_required=0.0,
            max_loss_amount=0.0,
            max_profit_amount=0.0,
            risk_reward_ratio=0.0,
            is_approved=False,
            rejection_reasons=[f"Derivatives not supported for {ticker}. Trade cash equity instead."],
            reasoning=f"⛔ REJECTED: No F&O contracts configured for {ticker}."
        )


# Backwards compatibility class alias
OptionsEngine = DerivativeEngine
