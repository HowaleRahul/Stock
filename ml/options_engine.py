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
import datetime
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple

import scipy.stats as si
import numpy as np

from ml.risk_engine import TradePlan, IndianFOFrictionModel

logger = logging.getLogger("trading.options_engine")

FO_WEIGHTS_FILE = "ml/models/fo_weights.json"

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

INDEX_EXPIRY_WEEKDAYS = {
    "MIDCPNIFTY": 0,   # Monday
    "FINNIFTY": 1,     # Tuesday
    "BANKNIFTY": 2,    # Wednesday (weekly)
    "NIFTY": 3,        # Thursday
    "^NSEI": 3,        # Thursday
    "SENSEX": 4,       # Friday
    "^BSESN": 4,       # Friday
}


def normalize_index_ticker(ticker: str) -> str:
    """Normalizes any index ticker representation to canonical NSE/BSE symbol."""
    if not ticker or not isinstance(ticker, str):
        return ""
    t = ticker.upper().replace("^", "").strip()
    if "BSESN" in t or "SENSEX" in t:
        return "SENSEX"
    if "NSEBANK" in t or "BANK" in t:
        return "BANKNIFTY"
    if "FIN" in t:
        return "FINNIFTY"
    if "MID" in t:
        return "MIDCPNIFTY"
    if "NSEI" in t or "NIFTY" in t:
        return "NIFTY"
    return t


def get_days_to_expiry(
    ticker: str,
    dt: Optional[datetime.datetime] = None,
    is_monthly: bool = False
) -> float:
    """
    Calculates fractional trading days remaining until 15:30 IST on the index's expiry day.

    Weekly Indian Index Expiry Schedule:
    - MIDCPNIFTY: Monday (weekday = 0)
    - FINNIFTY: Tuesday (weekday = 1)
    - BANKNIFTY: Wednesday (weekday = 2, or monthly Thursday = 3)
    - NIFTY / ^NSEI: Thursday (weekday = 3)
    - SENSEX / ^BSESN: Friday (weekday = 4)
    - Other NSE F&O equities: Thursday (weekday = 3)

    Market trading session: 09:15 to 15:30 IST (375 minutes = 6.25 hours).
    Fractional trading day is computed proportionally during session hours.
    Weekends (Saturday & Sunday) are non-trading days and contribute 0.0.
    """
    norm = normalize_index_ticker(ticker)

    # Determine expiry weekday
    if is_monthly and norm == "BANKNIFTY":
        expiry_weekday = 3  # Monthly BANKNIFTY expiry is Thursday
    else:
        expiry_weekday = INDEX_EXPIRY_WEEKDAYS.get(norm, 3)

    # Timezone handling: ensure dt is in IST
    if dt is None:
        curr_dt = datetime.datetime.now(IST)
    elif dt.tzinfo is None:
        curr_dt = dt.replace(tzinfo=IST)
    else:
        curr_dt = dt.astimezone(IST)

    curr_date = curr_dt.date()
    curr_weekday = curr_date.weekday()

    # Find the upcoming target expiry date
    if curr_weekday == expiry_weekday:
        # Today is expiry day
        if curr_dt.time() <= datetime.time(15, 30):
            target_date = curr_date
        else:
            # Past 15:30 on expiry day -> roll to next week's expiry
            target_date = curr_date + datetime.timedelta(days=7)
    else:
        days_ahead = (expiry_weekday - curr_weekday) % 7
        target_date = curr_date + datetime.timedelta(days=days_ahead)

    # If monthly requested: find last occurrence of expiry weekday in the month
    if is_monthly:
        import calendar
        cal = calendar.monthcalendar(target_date.year, target_date.month)
        last_day = max(week[expiry_weekday] for week in cal if week[expiry_weekday] != 0)
        candidate_monthly_date = datetime.date(target_date.year, target_date.month, last_day)
        if candidate_monthly_date < curr_date or (candidate_monthly_date == curr_date and curr_dt.time() >= datetime.time(15, 30)):
            # Roll to next month's last expiry
            next_month = target_date.month + 1 if target_date.month < 12 else 1
            next_year = target_date.year if target_date.month < 12 else target_date.year + 1
            next_cal = calendar.monthcalendar(next_year, next_month)
            next_last_day = max(week[expiry_weekday] for week in next_cal if week[expiry_weekday] != 0)
            target_date = datetime.date(next_year, next_month, next_last_day)
        else:
            target_date = candidate_monthly_date

    # Sum fractional trading days from curr_date to target_date
    total_trading_days = 0.0
    day = curr_date

    while day <= target_date:
        # Skip weekends (Saturday=5, Sunday=6)
        if day.weekday() < 5:
            if day == curr_date and day == target_date:
                # Expiry is today!
                if curr_dt.time() <= datetime.time(9, 15):
                    fraction = 1.0
                elif curr_dt.time() >= datetime.time(15, 30):
                    fraction = 0.0
                else:
                    rem_mins = (15 * 60 + 30) - (curr_dt.hour * 60 + curr_dt.minute + curr_dt.second / 60.0)
                    fraction = max(0.0, min(1.0, rem_mins / 375.0))
                total_trading_days += fraction

            elif day == curr_date:
                # Current day (before expiry date)
                if curr_dt.time() <= datetime.time(9, 15):
                    fraction = 1.0
                elif curr_dt.time() >= datetime.time(15, 30):
                    fraction = 0.0
                else:
                    rem_mins = (15 * 60 + 30) - (curr_dt.hour * 60 + curr_dt.minute + curr_dt.second / 60.0)
                    fraction = max(0.0, min(1.0, rem_mins / 375.0))
                total_trading_days += fraction

            elif day == target_date:
                # Expiry day in the future (expires at 15:30, so full trading session available)
                total_trading_days += 1.0

            else:
                # Full intermediate trading day
                total_trading_days += 1.0

        day += datetime.timedelta(days=1)

    return round(float(total_trading_days), 4)


# ===========================================================================
# 1. Data Structures
# ===========================================================================

@dataclass
class DerivativeTradePlan:
    """A complete derivative (Options or Futures) trade recommendation."""
    original_spot_plan: TradePlan

    instrument_type: str        # "OPTION" or "FUTURE" or "SPREAD"
    underlying_ticker: str      # "NIFTY", "BANKNIFTY", etc.
    contract_symbol: str        # e.g. "NIFTY 22800 CE", "BANKNIFTY FUT"
    direction: str              # "LONG" or "SHORT"
    option_type: str            # "CE", "PE", "FUT", or "SPREAD"
    strike_price: float         # Strike price (0 for Futures)
    strike_type: str            # "ITM", "ATM", "OTM", "FUT", or "SPREAD"
    action: str = "BUY"         # "BUY" or "SELL"
    strategy_type: str = "DIRECTIONAL" # "DIRECTIONAL", "CREDIT_SPREAD", "FUTURES"

    lot_size: int = 25          # NSE lot size (NIFTY: 25, BANKNIFTY: 15)
    lots_to_trade: int = 1      # Number of lots
    total_quantity: int = 25    # lots * lot_size

    # Pricing & Premium
    entry_price: float = 0.0          # Entry option premium OR Future entry price
    target_price: float = 0.0         # Option target premium OR Future target price
    stop_loss_price: float = 0.0      # Option SL premium OR Future SL price

    # Spread Specific Attributes
    hedge_contract_symbol: str = ""   # Long protective wing for spreads
    hedge_strike_price: float = 0.0   # Long hedge strike
    hedge_entry_price: float = 0.0    # Long hedge entry premium
    net_credit: float = 0.0           # Net credit collected per share

    # Margins and Capital
    margin_or_premium_required: float = 0.0  # Capital deployed
    max_loss_amount: float = 0.0
    max_profit_amount: float = 0.0
    risk_reward_ratio: float = 0.0

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
            "action": self.action,
            "strategy_type": self.strategy_type,
            "lot_size": self.lot_size,
            "lots_to_trade": self.lots_to_trade,
            "total_quantity": self.total_quantity,
            "entry_price": round(self.entry_price, 2),
            "target_price": round(self.target_price, 2),
            "stop_loss_price": round(self.stop_loss_price, 2),
            "hedge_contract_symbol": self.hedge_contract_symbol,
            "hedge_strike_price": round(self.hedge_strike_price, 2),
            "hedge_entry_price": round(self.hedge_entry_price, 2),
            "net_credit": round(self.net_credit, 2),
            "margin_or_premium_required": max(0.0, round(self.margin_or_premium_required, 2)) if math.isfinite(self.margin_or_premium_required) else 0.0,
            "max_loss_amount": round(self.max_loss_amount, 2) if math.isfinite(self.max_loss_amount) else 0.0,
            "max_profit_amount": round(self.max_profit_amount, 2) if math.isfinite(self.max_profit_amount) else 0.0,
            "risk_reward_ratio": min(100.0, max(0.0, round(self.risk_reward_ratio, 2))) if math.isfinite(self.risk_reward_ratio) else 0.0,
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

    def get_days_to_expiry(
        self,
        ticker: str,
        dt: Optional[datetime.datetime] = None,
        is_monthly: bool = False
    ) -> float:
        """Calculates dynamic fractional trading days to expiry for index/equity."""
        return get_days_to_expiry(ticker, dt=dt, is_monthly=is_monthly)

    @classmethod
    def fetch_live_iv(
        cls,
        spot_plan: Optional[TradePlan] = None,
        ticker: Optional[str] = None
    ) -> float:
        """
        Dynamically fetches real India VIX IV from:
        1. Candle context 'macro_vix' on spot_plan if available
        2. RealTimeDataFeed live quote for INDIAVIX
        3. NSEFeed live India VIX
        4. Baseline fallback DEFAULT_IV (0.14)
        """
        if spot_plan is not None:
            macro_vix = getattr(spot_plan, "macro_vix", None)
            if macro_vix is not None and isinstance(macro_vix, (int, float)) and macro_vix > 0:
                return float(macro_vix / 100.0 if macro_vix > 1.0 else macro_vix)

        try:
            from data.realtime_feed import RealTimeDataFeed
            vix_val = RealTimeDataFeed.get_india_vix_sync()
            if vix_val > 0:
                return float(vix_val / 100.0 if vix_val > 1.0 else vix_val)
        except Exception as e:
            logger.debug(f"Could not fetch India VIX from RealTimeDataFeed: {e}")

        try:
            from data.nse_feed import NSEFeed
            v = NSEFeed.get_india_vix()
            if v and v > 0:
                return float(v / 100.0 if v > 1.0 else v)
        except Exception as e:
            logger.debug(f"Could not fetch India VIX from NSEFeed: {e}")

        return cls.DEFAULT_IV

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
        Accurately settles intrinsic value upon expiry (T <= 0) or extreme volatility bounds.
        """
        opt_type = str(option_type).upper().strip() if option_type else ""
        if opt_type not in ("CE", "PE"):
            return {"premium": 0.05, "delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}

        # Input validation: non-numeric, NaN, inf, or non-positive spot/strike
        if not all(isinstance(v, (int, float)) for v in (S, K, T, r, sigma)):
            return {"premium": 0.05, "delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
        if any(math.isnan(v) or math.isinf(v) for v in (S, K, T, r, sigma)):
            return {"premium": 0.05, "delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}

        if S <= 0.0 or K <= 0.0:
            return {"premium": 0.05, "delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}

        # Expiry moment (T <= 0) or zero volatility boundary: Option value converges to intrinsic value
        if T <= 0.0 or sigma <= 1e-9:
            if opt_type == "CE":
                intrinsic = max(0.05, max(0.0, S - K))
                delta = 1.0 if S > K else 0.0
            else:
                intrinsic = max(0.05, max(0.0, K - S))
                delta = -1.0 if K > S else 0.0
            return {
                "premium": round(float(intrinsic), 2),
                "delta": float(delta),
                "gamma": 0.0,
                "theta": 0.0,
                "vega": 0.0
            }

        denom = sigma * np.sqrt(T)
        if denom <= 1e-9 or (S * denom) <= 1e-12:
            if opt_type == "CE":
                intrinsic = max(0.05, max(0.0, S - K))
                delta = 1.0 if S > K else 0.0
            else:
                intrinsic = max(0.05, max(0.0, K - S))
                delta = -1.0 if K > S else 0.0
            return {
                "premium": round(float(intrinsic), 2),
                "delta": float(delta),
                "gamma": 0.0,
                "theta": 0.0,
                "vega": 0.0
            }

        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / denom
        d2 = d1 - denom

        # Deep ITM / Deep OTM asymptotic regime checks (|d1| >= 37 standard deviations)
        if d1 >= 37.0:
            if opt_type == "CE":
                prem = max(0.05, S - K * np.exp(-r * T))
                delta = 1.0
                theta = (-r * K * np.exp(-r * T)) / 365.0
            else:  # Put is deep OTM
                prem = 0.05
                delta = 0.0
                theta = 0.0
            return {
                "premium": round(float(prem), 2),
                "delta": float(delta),
                "gamma": 0.0,
                "theta": round(float(theta), 4),
                "vega": 0.0
            }
        elif d1 <= -37.0:
            if opt_type == "CE":  # Call is deep OTM
                prem = 0.05
                delta = 0.0
                theta = 0.0
            else:  # Put is deep ITM
                prem = max(0.05, K * np.exp(-r * T) - S)
                delta = -1.0
                theta = (r * K * np.exp(-r * T)) / 365.0
            return {
                "premium": round(float(prem), 2),
                "delta": float(delta),
                "gamma": 0.0,
                "theta": round(float(theta), 4),
                "vega": 0.0
            }

        try:
            if opt_type == "CE":
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

            # Guard against NaN or Inf values
            safe_prem = float(premium) if not (math.isnan(premium) or math.isinf(premium)) else max(0.05, (S - K) if opt_type == "CE" else (K - S))
            
            # Enforce Black-Scholes Greeks bounds
            if opt_type == "CE":
                safe_delta = float(np.clip(delta, 0.0, 1.0)) if not (math.isnan(delta) or math.isinf(delta)) else (1.0 if S > K else 0.0)
            else:
                safe_delta = float(np.clip(delta, -1.0, 0.0)) if not (math.isnan(delta) or math.isinf(delta)) else (-1.0 if K > S else 0.0)

            safe_gamma = float(max(0.0, gamma)) if not (math.isnan(gamma) or math.isinf(gamma)) else 0.0
            safe_theta = float(theta_per_day) if not (math.isnan(theta_per_day) or math.isinf(theta_per_day)) else 0.0
            safe_vega = float(max(0.0, vega / 100.0)) if not (math.isnan(vega) or math.isinf(vega)) else 0.0

            return {
                "premium": max(0.05, round(safe_prem, 2)),
                "delta": round(safe_delta, 4),
                "gamma": round(safe_gamma, 6),
                "theta": round(safe_theta, 4),
                "vega": round(safe_vega, 4)
            }
        except Exception:
            if opt_type == "CE":
                intrinsic = max(0.05, max(0.0, S - K))
                delta = 1.0 if S > K else 0.0
            else:
                intrinsic = max(0.05, max(0.0, K - S))
                delta = -1.0 if K > S else 0.0
            return {"premium": round(intrinsic, 2), "delta": float(delta), "gamma": 0.0, "theta": 0.0, "vega": 0.0}

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

        # 1. Decide Instrument Type: FUTURES vs OPTIONS vs SPREAD vs SELL_OPTIONS vs IRON_CONDOR
        chosen_instrument = derivative_type.upper().strip()
        if chosen_instrument == "AUTO":
            # Real Indian F&O Allocation Logic:
            # Rangebound / Low-ADX / Chop regime -> Option Selling (Iron Condor / Credit Spreads / Directional Writing)
            # Trending / Breakout regime -> Futures (if large cap) or Option Buying
            if "range" in regime.lower() or "chop" in regime.lower():
                if capital >= 50000.0 and abs(spot_plan.ai_probability - 0.5) <= 0.15:
                    chosen_instrument = "IRON_CONDOR"
                elif capital >= futures_margin:
                    chosen_instrument = "SELL_OPTIONS"
                elif capital >= 25000.0:
                    chosen_instrument = "CREDIT_SPREAD"
                else:
                    chosen_instrument = "OPTIONS"
            else:
                # Trending regime
                if capital >= (futures_margin * 1.5) and spot_plan.ai_probability >= 0.75:
                    chosen_instrument = "FUTURES"
                else:
                    chosen_instrument = "OPTIONS"

        real_iv = iv if (iv is not None and iv > 0) else self.fetch_live_iv(spot_plan=spot_plan, ticker=underlying)

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
        elif chosen_instrument in ("SELL_OPTIONS", "SELL_OPTION", "SHORT_OPTION"):
            return self._build_option_selling_plan(
                spot_plan=spot_plan,
                underlying=underlying,
                capital=capital,
                span_margin=futures_margin,
                lot_size=lot_size,
                interval=interval,
                regime=regime,
                iv=real_iv,
                strike_pref=strike_pref
            )
        elif chosen_instrument in ("CREDIT_SPREAD", "SPREAD"):
            return self._build_credit_spread_plan(
                spot_plan=spot_plan,
                underlying=underlying,
                capital=capital,
                lot_size=lot_size,
                interval=interval,
                regime=regime,
                iv=real_iv
            )
        elif chosen_instrument in ("IRON_CONDOR", "CONDOR"):
            return self._build_iron_condor_plan(
                spot_plan=spot_plan,
                underlying=underlying,
                capital=capital,
                lot_size=lot_size,
                interval=interval,
                regime=regime,
                iv=real_iv
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
                iv=real_iv
            )

    # -----------------------------------------------------------------------
    # Option Selling (Writing) Plan Builder
    # -----------------------------------------------------------------------

    def _build_option_selling_plan(
        self,
        spot_plan: TradePlan,
        underlying: str,
        capital: float,
        span_margin: float,
        lot_size: int,
        interval: int,
        regime: str,
        iv: float,
        strike_pref: str = "AUTO"
    ) -> DerivativeTradePlan:
        """
        Directional Option Selling (Writing) Strategy:
        - When Spot is Bearish: Sell OTM Call (strike = ATM + interval). Target = 70% decay, SL = 30% rise.
        - When Spot is Bullish: Sell OTM Put (strike = ATM - interval). Target = 70% decay, SL = 30% rise.
        - Enforces SPAN + Exposure margin.
        - Positive Theta (seller profits from time decay).
        """
        direction = "SHORT" if spot_plan.direction in ("SHORT", "bearish") else "LONG"
        # In Indian F&O: If market is Bearish, sell CALL (CE). If market is Bullish, sell PUT (PE).
        option_type = "CE" if direction == "SHORT" else "PE"
        spot = spot_plan.entry_price
        atm_strike = self._round_to_nearest(spot, interval)

        # Dynamic Days to Expiry (DTE) per Index
        dte = self.get_days_to_expiry(underlying)
        safe_dte = max(0.05, dte)
        T = safe_dte / 365.0
        r = self.RISK_FREE_RATE
        sigma = iv

        # Pick OTM strike for high probability theta collection
        if option_type == "CE":
            chosen_strike = atm_strike + interval  # OTM Call
        else:
            chosen_strike = atm_strike - interval  # OTM Put

        bs = self.black_scholes(spot, chosen_strike, T, r, sigma, option_type)
        entry_premium = bs["premium"]
        
        # In option selling, target is premium decaying to ~30% (70% profit capture)
        target_premium = max(0.05, round(entry_premium * 0.30, 2))
        # Stop loss is standard 30% above entry premium
        stop_loss_premium = round(entry_premium * 1.30, 2)

        risk_per_qty = max(1.0, stop_loss_premium - entry_premium)
        reward_per_qty = max(1.0, entry_premium - target_premium)
        max_loss = risk_per_qty * lot_size
        max_profit = reward_per_qty * lot_size
        rr = max_profit / max_loss if max_loss > 0 else 0.0

        contract_symbol = f"{underlying} {chosen_strike} {option_type} SELL"

        # Indian Options Friction for Option Selling
        f_breakdown = IndianFOFrictionModel.calculate_options_friction(
            buy_premium=target_premium,
            sell_premium=entry_premium,
            quantity=lot_size,
            action="SELL"
        )
        total_friction = f_breakdown.total_friction
        be_exit = f_breakdown.breakeven_exit_price
        net_profit = max_profit - total_friction

        rejections = []
        is_approved = True

        if capital < span_margin:
            is_approved = False
            rejections.append(
                f"Option Selling SPAN Margin Deficit: Selling 1 lot of {contract_symbol} requires ₹{span_margin:,.2f} margin. "
                f"Your capital is ₹{capital:,.2f}. Switch to Credit Spread (requires only ~₹25k-₹35k) or Option Buying."
            )

        if entry_premium < 20.0:
            is_approved = False
            rejections.append(
                f"Low Premium Warning: Option premium ₹{entry_premium:.2f} is too low for naked writing; "
                f"tail risk exceeds reward. Sell closer to ATM strike."
            )

        if max_profit <= total_friction:
            is_approved = False
            rejections.append(
                f"Selling Breakeven Deficit: Expected profit ₹{max_profit:.2f} fails to clear transaction friction ₹{total_friction:.2f}."
            )

        # Delta & Theta: For Short Call, delta is negative; for Short Put, delta is positive. Theta is POSITIVE.
        seller_delta = -bs["delta"] if option_type == "CE" else abs(bs["delta"])
        seller_theta = abs(bs["theta"])  # Positive daily theta income!

        reasoning = (
            f"{'✅ APPROVED' if is_approved else '⛔ REJECTED'}: {contract_symbol} (Option Writing)\n"
            f"  ⚡ Delta: {seller_delta:+.3f} | ⏳ Theta (Income): +₹{seller_theta:.2f}/day | IV: {sigma*100:.1f}%\n"
            f"  💰 Entry Credit: ₹{entry_premium:,.2f} | Target Buyback: ₹{target_premium:,.2f} | SL Buyback: ₹{stop_loss_premium:,.2f}\n"
            f"  🏷️  Est. Friction: ₹{total_friction:,.2f} | Net Profit: ₹{net_profit:,.2f} | Breakeven: ₹{be_exit:,.2f}\n"
            f"  📊 SPAN Margin: ₹{span_margin:,.2f} (1 lot = {lot_size} qty) | Max Risk: ₹{max_loss:,.2f} | R:R: {rr:.2f}:1\n"
            f"  🎯 Spot Underlying: {spot_plan.ticker} @ ₹{spot:,.2f} ({spot_plan.direction}) | DTE: {dte:.2f} days"
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
            strike_type="OTM",
            action="SELL",
            strategy_type="DIRECTIONAL_SELLING",
            lot_size=lot_size,
            lots_to_trade=1,
            total_quantity=lot_size,
            entry_price=entry_premium,
            target_price=target_premium,
            stop_loss_price=stop_loss_premium,
            margin_or_premium_required=span_margin,
            max_loss_amount=max_loss,
            max_profit_amount=max_profit,
            risk_reward_ratio=rr,
            delta=round(seller_delta, 4),
            theta=round(seller_theta, 4),
            gamma=round(-abs(bs["gamma"]), 6),
            vega=round(-abs(bs["vega"]), 4),
            days_to_expiry=round(dte, 4),
            iv=sigma,
            is_approved=is_approved,
            rejection_reasons=rejections,
            reasoning=reasoning
        )

    # -----------------------------------------------------------------------
    # Defined-Risk Credit Spread Plan Builder
    # -----------------------------------------------------------------------

    def _build_credit_spread_plan(
        self,
        spot_plan: TradePlan,
        underlying: str,
        capital: float,
        lot_size: int,
        interval: int,
        regime: str,
        iv: float
    ) -> DerivativeTradePlan:
        """
        Defined-Risk Credit Spread Strategy:
        - Bullish: Bull Put Spread (Sell OTM PE, Buy further OTM PE as hedge wing)
        - Bearish: Bear Call Spread (Sell OTM CE, Buy further OTM CE as hedge wing)
        - Margin required: Capped at (Spread Width * Lot Size) + friction buffer (~₹25k-₹35k).
        - Theta: Positive (+ve) net decay income.
        """
        is_bullish = spot_plan.direction in ("LONG", "bullish")
        spot = spot_plan.entry_price
        atm_strike = self._round_to_nearest(spot, interval)

        dte = self.get_days_to_expiry(underlying)
        safe_dte = max(0.05, dte)
        T = safe_dte / 365.0
        r = self.RISK_FREE_RATE
        sigma = iv

        if is_bullish:
            # Bull Put Spread: Sell strike1 PE, Buy strike2 PE (strike2 < strike1)
            spread_name = "BULL PUT SPREAD"
            short_strike = atm_strike - interval
            long_strike = atm_strike - (2 * interval)
            opt_type = "PE"
            direction = "LONG"
            bs_short = self.black_scholes(spot, short_strike, T, r, sigma, "PE")
            bs_long = self.black_scholes(spot, long_strike, T, r, sigma, "PE")
        else:
            # Bear Call Spread: Sell strike1 CE, Buy strike2 CE (strike2 > strike1)
            spread_name = "BEAR CALL SPREAD"
            short_strike = atm_strike + interval
            long_strike = atm_strike + (2 * interval)
            opt_type = "CE"
            direction = "SHORT"
            bs_short = self.black_scholes(spot, short_strike, T, r, sigma, "CE")
            bs_long = self.black_scholes(spot, long_strike, T, r, sigma, "CE")

        p_short = bs_short["premium"]
        p_long = bs_long["premium"]
        net_credit = max(1.0, round(p_short - p_long, 2))
        spread_width = float(abs(short_strike - long_strike))
        max_loss_per_share = max(1.0, spread_width - net_credit)

        # Hedged SPAN margin benefit under NSE rules
        hedged_margin = round(max_loss_per_share * lot_size + 2500.0, 2)

        target_net_credit = max(0.05, round(net_credit * 0.30, 2))  # Capture 70% of credit
        sl_net_debit = round(net_credit * 1.50, 2)

        max_profit = round((net_credit - target_net_credit) * lot_size, 2)
        max_loss = round(max_loss_per_share * lot_size, 2)
        rr = max_profit / max_loss if max_loss > 0 else 0.0

        contract_symbol = f"{underlying} {short_strike}/{long_strike} {spread_name}"
        hedge_symbol = f"{underlying} {long_strike} {opt_type} HEDGE"

        f_breakdown = IndianFOFrictionModel.calculate_spread_friction(
            short_entry_prem=p_short,
            short_exit_prem=target_net_credit * 0.8,
            long_entry_prem=p_long,
            long_exit_prem=0.05,
            quantity=lot_size
        )
        total_friction = f_breakdown.total_friction
        net_profit = max_profit - total_friction

        rejections = []
        is_approved = True

        if capital < hedged_margin:
            is_approved = False
            rejections.append(
                f"Credit Spread Margin Deficit: 1 lot of {spread_name} requires ₹{hedged_margin:,.2f} margin "
                f"(Max loss ₹{max_loss:,.2f}). Available capital: ₹{capital:,.2f}."
            )

        if net_credit < 10.0:
            is_approved = False
            rejections.append(
                f"Low Net Credit: Net credit of ₹{net_credit:.2f} is insufficient to justify round-trip 2-leg friction (₹{total_friction:.2f})."
            )

        if max_profit <= total_friction:
            is_approved = False
            rejections.append(
                f"Spread Breakeven Deficit: Expected net profit ₹{max_profit:.2f} fails to clear transaction friction ₹{total_friction:.2f}."
            )

        net_delta = (-bs_short["delta"] + bs_long["delta"]) if opt_type == "CE" else (abs(bs_short["delta"]) - abs(bs_long["delta"]))
        net_theta = max(0.1, abs(bs_short["theta"]) - abs(bs_long["theta"]))

        reasoning = (
            f"{'✅ APPROVED' if is_approved else '⛔ REJECTED'}: {contract_symbol}\n"
            f"  ⚡ Net Delta: {net_delta:+.3f} | ⏳ Net Theta: +₹{net_theta:.2f}/day | IV: {sigma*100:.1f}%\n"
            f"  💰 Short Strike: {short_strike} (₹{p_short:.2f}) | Long Hedge: {long_strike} (₹{p_long:.2f})\n"
            f"  🏷️  Net Credit Collected: ₹{net_credit:,.2f} | Max Risk: ₹{max_loss:,.2f} | Max Profit: ₹{max_profit:,.2f}\n"
            f"  🏷️  Est. 2-Leg Friction: ₹{total_friction:,.2f} | Net Profit: ₹{net_profit:,.2f}\n"
            f"  📊 Hedged SPAN Margin: ₹{hedged_margin:,.2f} (1 lot = {lot_size} qty) | R:R: {rr:.2f}:1\n"
            f"  🎯 Spot Underlying: {spot_plan.ticker} @ ₹{spot:,.2f} ({spot_plan.direction}) | DTE: {dte:.2f} days"
        )
        if rejections:
            reasoning += "\n  " + "\n  ".join(f"• {r}" for r in rejections)

        return DerivativeTradePlan(
            original_spot_plan=spot_plan,
            instrument_type="SPREAD",
            underlying_ticker=underlying,
            contract_symbol=contract_symbol,
            direction=direction,
            option_type="SPREAD",
            strike_price=short_strike,
            strike_type="SPREAD",
            action="SELL",
            strategy_type="CREDIT_SPREAD",
            lot_size=lot_size,
            lots_to_trade=1,
            total_quantity=lot_size,
            entry_price=net_credit,
            target_price=target_net_credit,
            stop_loss_price=sl_net_debit,
            hedge_contract_symbol=hedge_symbol,
            hedge_strike_price=long_strike,
            hedge_entry_price=p_long,
            net_credit=net_credit,
            margin_or_premium_required=hedged_margin,
            max_loss_amount=max_loss,
            max_profit_amount=max_profit,
            risk_reward_ratio=rr,
            delta=round(net_delta, 4),
            theta=round(net_theta, 4),
            gamma=round(-abs(bs_short["gamma"]) + abs(bs_long["gamma"]), 6),
            vega=round(-abs(bs_short["vega"]) + abs(bs_long["vega"]), 4),
            days_to_expiry=round(dte, 4),
            iv=sigma,
            is_approved=is_approved,
            rejection_reasons=rejections,
            reasoning=reasoning
        )

    # -----------------------------------------------------------------------
    # Defined-Risk Iron Condor Plan Builder (Rangebound / Expiry Day)
    # -----------------------------------------------------------------------

    def _build_iron_condor_plan(
        self,
        spot_plan: TradePlan,
        underlying: str,
        capital: float,
        lot_size: int,
        interval: int,
        regime: str,
        iv: float
    ) -> DerivativeTradePlan:
        """
        Non-Directional 4-Leg Iron Condor Strategy for Rangebound / Expiry Day Markets:
        - Downside (Bull Put Spread):
            * Sell OTM Put: atm_strike - interval
            * Buy OTM Put: atm_strike - 2 * interval (hedge wing)
        - Upside (Bear Call Spread):
            * Sell OTM Call: atm_strike + interval
            * Buy OTM Call: atm_strike + 2 * interval (hedge wing)
        - Margin required: Capped at (Wing Width * Lot Size) - Net Credit + buffer (~₹35k-₹45k).
        - Theta: Substantial positive (+ve) net decay income from both sides.
        - Breakevens:
            * Lower Breakeven = (atm_strike - interval) - Net Credit
            * Upper Breakeven = (atm_strike + interval) + Net Credit
        """
        spot = spot_plan.entry_price
        atm_strike = self._round_to_nearest(spot, interval)

        dte = self.get_days_to_expiry(underlying)
        safe_dte = max(0.05, dte)
        T = safe_dte / 365.0
        r = self.RISK_FREE_RATE
        sigma = iv

        short_put = atm_strike - interval
        long_put = atm_strike - (2 * interval)
        short_call = atm_strike + interval
        long_call = atm_strike + (2 * interval)

        bs_sp = self.black_scholes(spot, short_put, T, r, sigma, "PE")
        bs_lp = self.black_scholes(spot, long_put, T, r, sigma, "PE")
        bs_sc = self.black_scholes(spot, short_call, T, r, sigma, "CE")
        bs_lc = self.black_scholes(spot, long_call, T, r, sigma, "CE")

        put_credit = max(0.5, round(bs_sp["premium"] - bs_lp["premium"], 2))
        call_credit = max(0.5, round(bs_sc["premium"] - bs_lc["premium"], 2))
        net_credit = round(put_credit + call_credit, 2)
        wing_width = float(interval)
        max_loss_per_share = max(1.0, wing_width - net_credit)

        # Hedged SPAN margin under NSE rules (only one side at risk)
        hedged_margin = round(max_loss_per_share * lot_size + 3500.0, 2)

        target_net_credit = max(0.05, round(net_credit * 0.30, 2))  # 70% decay capture
        sl_net_debit = round(net_credit * 1.50, 2)

        max_profit = round((net_credit - target_net_credit) * lot_size, 2)
        max_loss = round(max_loss_per_share * lot_size, 2)
        rr = max_profit / max_loss if max_loss > 0 else 0.0

        contract_symbol = f"{underlying} {short_put}/{short_call} IRON CONDOR"
        hedge_symbol = f"{underlying} {long_put} PE / {long_call} CE HEDGE"

        f_breakdown = IndianFOFrictionModel.calculate_iron_condor_friction(
            short_put_entry=bs_sp["premium"],
            short_put_exit=target_net_credit * 0.4,
            long_put_entry=bs_lp["premium"],
            long_put_exit=0.05,
            short_call_entry=bs_sc["premium"],
            short_call_exit=target_net_credit * 0.4,
            long_call_entry=bs_lc["premium"],
            long_call_exit=0.05,
            quantity=lot_size
        )
        total_friction = f_breakdown.total_friction
        net_profit = round(max_profit - total_friction, 2)

        lower_be = round(short_put - net_credit, 2)
        upper_be = round(short_call + net_credit, 2)

        rejections = []
        is_approved = True

        if capital < hedged_margin:
            is_approved = False
            rejections.append(
                f"Iron Condor Margin Deficit: 1 lot requires ₹{hedged_margin:,.2f} margin "
                f"(Max loss ₹{max_loss:,.2f}). Available capital: ₹{capital:,.2f}."
            )

        if net_credit < 15.0:
            is_approved = False
            rejections.append(
                f"Low Net Credit: Combined credit ₹{net_credit:.2f} is insufficient for 4-leg friction (₹{total_friction:.2f})."
            )

        if max_profit <= total_friction:
            is_approved = False
            rejections.append(
                f"Iron Condor Breakeven Deficit: Net profit ₹{max_profit:.2f} fails to clear transaction friction ₹{total_friction:.2f}."
            )

        net_delta = round((abs(bs_sp["delta"]) - abs(bs_lp["delta"])) + (-bs_sc["delta"] + bs_lc["delta"]), 4)
        net_theta = round((abs(bs_sp["theta"]) - abs(bs_lp["theta"])) + (abs(bs_sc["theta"]) - abs(bs_lc["theta"])), 4)
        net_theta = max(0.2, net_theta)

        reasoning = (
            f"{'✅ APPROVED' if is_approved else '⛔ REJECTED'}: {contract_symbol}\n"
            f"  ⚡ Net Delta: {net_delta:+.3f} (Delta Neutral) | ⏳ Net Theta: +₹{net_theta:.2f}/day | IV: {sigma*100:.1f}%\n"
            f"  💰 Put Wing: Sell {short_put} PE (₹{bs_sp['premium']:.2f}) / Buy {long_put} PE (₹{bs_lp['premium']:.2f})\n"
            f"  💰 Call Wing: Sell {short_call} CE (₹{bs_sc['premium']:.2f}) / Buy {long_call} CE (₹{bs_lc['premium']:.2f})\n"
            f"  🏷️  Combined Net Credit: ₹{net_credit:,.2f} | Max Risk: ₹{max_loss:,.2f} | Max Profit: ₹{max_profit:,.2f}\n"
            f"  🎯 Breakevens: ₹{lower_be:,.2f} to ₹{upper_be:,.2f} | Est. 4-Leg Friction: ₹{total_friction:,.2f}\n"
            f"  📊 Hedged Margin: ₹{hedged_margin:,.2f} (1 lot = {lot_size} qty) | R:R: {rr:.2f}:1 | DTE: {dte:.2f} days"
        )
        if rejections:
            reasoning += "\n  " + "\n  ".join(f"• {r}" for r in rejections)

        return DerivativeTradePlan(
            original_spot_plan=spot_plan,
            instrument_type="IRON_CONDOR",
            underlying_ticker=underlying,
            contract_symbol=contract_symbol,
            direction="NEUTRAL",
            option_type="IRON_CONDOR",
            strike_price=atm_strike,
            strike_type="IRON_CONDOR",
            action="SELL",
            strategy_type="IRON_CONDOR",
            lot_size=lot_size,
            lots_to_trade=1,
            total_quantity=lot_size,
            entry_price=net_credit,
            target_price=target_net_credit,
            stop_loss_price=sl_net_debit,
            hedge_contract_symbol=hedge_symbol,
            hedge_strike_price=long_put,
            hedge_entry_price=bs_lp["premium"],
            net_credit=net_credit,
            margin_or_premium_required=hedged_margin,
            max_loss_amount=max_loss,
            max_profit_amount=max_profit,
            risk_reward_ratio=rr,
            delta=net_delta,
            theta=net_theta,
            gamma=round(-abs(bs_sp["gamma"] + bs_sc["gamma"]), 6),
            vega=round(-abs(bs_sp["vega"] + bs_sc["vega"]), 4),
            days_to_expiry=round(dte, 4),
            iv=sigma,
            is_approved=is_approved,
            rejection_reasons=rejections,
            reasoning=reasoning
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

        # Real-World Indian Futures Friction & Breakeven Check
        f_breakdown = IndianFOFrictionModel.calculate_futures_friction(
            entry_price=spot_plan.entry_price,
            exit_price=spot_plan.take_profit,
            quantity=lot_size,
            direction=direction
        )
        total_friction = f_breakdown.total_friction
        be_price = f_breakdown.breakeven_exit_price
        net_profit = max_profit - total_friction

        if max_profit <= total_friction:
            is_approved = False
            rejections.append(
                f"Futures Friction Deficit: Expected profit (₹{max_profit:,.2f}) fails to cover "
                f"round-trip transaction friction (₹{total_friction:,.2f}). Breakeven price: ₹{be_price:,.2f}."
            )

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
            f"  🏷️  Est. Friction: ₹{total_friction:,.2f} | Net Profit: ₹{net_profit:,.2f} | Breakeven: ₹{be_price:,.2f}\n"
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

        # Dynamic Days to Expiry (DTE) per Index
        dte = self.get_days_to_expiry(underlying)
        safe_dte = max(0.05, dte)
        T = safe_dte / 365.0
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

        # Premium at underlying Target and Stop Loss (holding time scaled to remaining DTE)
        hold_target_days = min(1.5, max(0.05, safe_dte * 0.25))
        T_target = max(0.001, (safe_dte - hold_target_days) / 365.0)
        bs_target = self.black_scholes(spot_plan.take_profit, chosen_strike, T_target, r, sigma, option_type)
        target_premium = max(entry_premium * 1.05, bs_target["premium"])

        hold_sl_days = min(1.0, max(0.02, safe_dte * 0.15))
        T_sl = max(0.001, (safe_dte - hold_sl_days) / 365.0)
        bs_sl = self.black_scholes(spot_plan.stop_loss, chosen_strike, T_sl, r, sigma, option_type)
        stop_loss_premium = min(entry_premium * 0.95, bs_sl["premium"])

        # Risk and Reward amounts
        risk_per_qty = max(1.0, entry_premium - stop_loss_premium)
        reward_per_qty = max(1.0, target_premium - entry_premium)
        max_loss = risk_per_qty * lot_size
        max_profit = reward_per_qty * lot_size
        rr = max_profit / max_loss if max_loss > 0 else 0.0

        # Real-World Indian Options Friction & Breakeven Check
        f_breakdown = IndianFOFrictionModel.calculate_options_friction(
            buy_premium=entry_premium,
            sell_premium=target_premium,
            quantity=lot_size
        )
        total_friction = f_breakdown.total_friction
        be_premium = f_breakdown.breakeven_exit_price
        net_profit = max_profit - total_friction

        # Quality Gating
        rejections = []
        is_approved = True

        # Gate 0: Breakeven Check
        if target_premium <= be_premium:
            is_approved = False
            rejections.append(
                f"Options Breakeven Deficit: Target premium ₹{target_premium:.2f} fails to clear "
                f"transaction friction breakeven ₹{be_premium:.2f} (Total friction ₹{total_friction:.2f})."
            )

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
            f"  🏷️  Est. Friction: ₹{total_friction:,.2f} | Net Profit: ₹{net_profit:,.2f} | Breakeven: ₹{be_premium:,.2f}\n"
            f"  📊 Invested: ₹{total_cost:,.2f} (1 lot = {lot_size} qty) | Max Risk: ₹{max_loss:,.2f} | R:R: {rr:.2f}:1\n"
            f"  🎯 Spot Underlying: {spot_plan.ticker} @ ₹{spot:,.2f} ({spot_plan.direction}) | DTE: {dte:.2f} days"
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
            action="BUY",
            strategy_type="DIRECTIONAL_BUY",
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
            days_to_expiry=round(dte, 4),
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
        days_elapsed: float = 0.1,
        iv: Optional[float] = None,
    ) -> Tuple[float, float]:
        """
        Re-prices an active option trade using Black-Scholes given current spot
        and elapsed holding time. Supports Option Buying, Option Selling, and Spreads.
        Returns (live_premium_or_net_value, live_delta).
        """
        strike = trade.get("strike", 0.0) or trade.get("opt_strike", 0.0)
        option_type = trade.get("option_type", "CE") or trade.get("opt_type", "CE")
        underlying = trade.get("underlying_ticker") or trade.get("ticker", "NIFTY")
        act = str(trade.get("action", "BUY")).upper()
        strat = str(trade.get("strategy_type", "DIRECTIONAL")).upper()

        if iv is None or iv <= 0:
            iv = trade.get("iv") or self.fetch_live_iv(ticker=underlying)

        if not isinstance(current_spot, (int, float)) or math.isnan(current_spot) or current_spot <= 0.0:
            return trade.get("entry_price", 0.0), trade.get("delta", 0.5)

        if not isinstance(strike, (int, float)) or math.isnan(strike) or strike <= 0.0:
            return trade.get("entry_price", 0.0), trade.get("delta", 0.5)

        if days_elapsed is None or not isinstance(days_elapsed, (int, float)) or math.isnan(days_elapsed) or math.isinf(days_elapsed) or days_elapsed < 0:
            days_elapsed = 0.0

        initial_dte = float(trade.get("days_to_expiry") or self.get_days_to_expiry(underlying))
        days_left = max(0.001, initial_dte - days_elapsed)
        T = days_left / 365.0

        if strat == "CREDIT_SPREAD" or trade.get("instrument_type") == "SPREAD":
            hedge_strike = trade.get("hedge_strike_price", strike)
            bs_short = self.black_scholes(current_spot, strike, T, self.RISK_FREE_RATE, iv, option_type if option_type in ("CE", "PE") else "PE")
            bs_long = self.black_scholes(current_spot, hedge_strike, T, self.RISK_FREE_RATE, iv, option_type if option_type in ("CE", "PE") else "PE")
            net_val = max(0.05, round(bs_short["premium"] - bs_long["premium"], 2))
            net_delta = (-bs_short["delta"] + bs_long["delta"]) if option_type == "CE" else (abs(bs_short["delta"]) - abs(bs_long["delta"]))
            return net_val, round(net_delta, 4)

        bs = self.black_scholes(current_spot, strike, T, self.RISK_FREE_RATE, iv, option_type)
        if act == "SELL":
            seller_delta = -bs["delta"] if option_type == "CE" else abs(bs["delta"])
            return bs["premium"], round(seller_delta, 4)
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
