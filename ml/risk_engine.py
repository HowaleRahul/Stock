"""
Risk Engine — Phase 6: Complete Trade Plan Generator.

Converts raw AI signals into fully actionable trade plans with:
- Position sizing (Kelly Criterion, capped at 2% risk per trade)
- ATR + S/R based Entry / Target / Stop Loss
- Risk:Reward gating (reject < 1.5:1)
- Probability of Ruin calculation
- Trailing stop management
- Time-based exit enforcement
- Portfolio correlation checks
"""

from __future__ import annotations

import math
import logging
import datetime
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
import pandas as pd

from setups.indicators import find_support_resistance

logger = logging.getLogger("trading.risk_engine")

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


def is_intraday_square_off_time(dt: Optional[datetime.datetime] = None) -> bool:
    """
    Checks if current or candle time has reached or exceeded Indian intraday
    MIS auto square-off threshold (15:15 IST).
    Broker RMS triggers automatic square-off between 15:15 and 15:30 IST on trading days.
    """
    if dt is None:
        dt_ist = datetime.datetime.now(IST)
        # Live clock check: only trigger during active weekday session within MIS window
        if dt_ist.weekday() >= 5:
            return False
        return datetime.time(15, 15) <= dt_ist.time() <= datetime.time(15, 30)

    if dt.tzinfo is None:
        dt_ist = dt.replace(tzinfo=IST)
    else:
        dt_ist = dt.astimezone(IST)

    return datetime.time(15, 15) <= dt_ist.time() <= datetime.time(15, 30)


# ---------------------------------------------------------------------------
# Indian F&O Transaction Friction & Regulatory Cost Model
# ---------------------------------------------------------------------------

@dataclass
class FOFrictionBreakdown:
    """Detailed breakdown of Indian regulatory and broker transaction costs."""
    instrument_type: str        # "OPTION" or "FUTURE"
    brokerage: float            # ₹40 round-trip (₹20 entry + ₹20 exit)
    stt: float                  # Securities Transaction Tax
    exchange_txn_charge: float  # Exchange transaction fee
    sebi_charges: float         # SEBI turnover charge (₹10/crore)
    gst: float                  # 18% on (Brokerage + Exchange Txn Charge)
    stamp_duty: float           # Stamp duty on buy turnover
    total_friction: float       # Sum of all regulatory and broker fees
    gross_pnl: float            # Gross profit / loss in ₹
    net_pnl: float              # Gross PnL - Total Friction in ₹
    breakeven_exit_price: float # Exit price where net_pnl == 0.0
    breakeven_points_required: float # Points move required to cover all friction

    def to_dict(self) -> Dict[str, Any]:
        return {
            "instrument_type": self.instrument_type,
            "brokerage": round(self.brokerage, 2),
            "stt": round(self.stt, 2),
            "exchange_txn_charge": round(self.exchange_txn_charge, 2),
            "sebi_charges": round(self.sebi_charges, 4),
            "gst": round(self.gst, 2),
            "stamp_duty": round(self.stamp_duty, 2),
            "total_friction": round(self.total_friction, 2),
            "gross_pnl": round(self.gross_pnl, 2),
            "net_pnl": round(self.net_pnl, 2),
            "breakeven_exit_price": round(self.breakeven_exit_price, 2),
            "breakeven_points_required": round(self.breakeven_points_required, 2),
        }


class IndianFOFrictionModel:
    """
    Real-world Indian F&O regulatory and brokerage transaction friction model.
    Accurately computes Brokerage, STT, Exchange Transaction Charges, GST, Stamp Duty,
    SEBI turnover charges, and Breakeven price thresholds.

    Regulatory specifications:
    - Options:
      - Brokerage: ₹20 buy + ₹20 sell = ₹40 flat per round trip
      - STT: 0.1% on sell premium turnover
      - NSE txn charge: 0.05% on premium turnover
      - GST: 18% on (Brokerage + Exchange Txn Charge)
      - Stamp duty: 0.003% on buy premium turnover
      - SEBI turnover charge: ₹10/crore (0.0001%)
    - Futures:
      - Brokerage: ₹20 buy + ₹20 sell = ₹40 flat per round trip
      - STT: 0.02% on sell turnover
      - Exchange txn charge: 0.0019% on total turnover
      - GST: 18% on (Brokerage + Exchange Txn Charge)
      - Stamp duty: 0.002% on buy turnover
      - SEBI turnover charge: ₹10/crore (0.0001%)
    """

    # Flat brokerages
    OPTIONS_BROKERAGE_BUY = 20.0
    OPTIONS_BROKERAGE_SELL = 20.0
    FUTURES_BROKERAGE_BUY = 20.0
    FUTURES_BROKERAGE_SELL = 20.0

    # Options statutory rates
    OPTIONS_STT_SELL_RATE = 0.001           # 0.1% on sell premium
    OPTIONS_EXCHANGE_TXN_RATE = 0.0005      # 0.05% on premium turnover
    OPTIONS_GST_RATE = 0.18                 # 18% on (Brokerage + Txn Charge)
    OPTIONS_STAMP_DUTY_BUY_RATE = 0.00003   # 0.003% on buy premium
    OPTIONS_SEBI_CHARGES_RATE = 0.000001    # ₹10 per crore

    # Futures statutory rates
    FUTURES_STT_SELL_RATE = 0.0002          # 0.02% on sell turnover
    FUTURES_EXCHANGE_TXN_RATE = 0.000019    # 0.0019% on turnover
    FUTURES_GST_RATE = 0.18                 # 18% on (Brokerage + Txn Charge)
    FUTURES_STAMP_DUTY_BUY_RATE = 0.00002   # 0.002% on buy turnover
    FUTURES_SEBI_CHARGES_RATE = 0.000001    # ₹10 per crore

    @classmethod
    def calculate_options_friction(
        cls,
        buy_premium: float,
        sell_premium: float,
        quantity: int,
        action: str = "BUY"
    ) -> FOFrictionBreakdown:
        """
        Calculates exact round-trip transaction friction for Indian Options.
        Supports both Option Buying (action='BUY') and Option Selling (action='SELL').
        """
        qty = max(1, int(quantity))
        b_prem = max(0.0, float(buy_premium))
        s_prem = max(0.0, float(sell_premium))
        act = str(action).upper().strip()

        buy_turnover = b_prem * qty
        sell_turnover = s_prem * qty
        total_turnover = buy_turnover + sell_turnover

        brokerage = cls.OPTIONS_BROKERAGE_BUY + cls.OPTIONS_BROKERAGE_SELL
        stt = sell_turnover * cls.OPTIONS_STT_SELL_RATE
        exchange_txn = total_turnover * cls.OPTIONS_EXCHANGE_TXN_RATE
        sebi_charges = total_turnover * cls.OPTIONS_SEBI_CHARGES_RATE
        gst = (brokerage + exchange_txn) * cls.OPTIONS_GST_RATE
        stamp_duty = buy_turnover * cls.OPTIONS_STAMP_DUTY_BUY_RATE

        total_friction = brokerage + stt + exchange_txn + sebi_charges + gst + stamp_duty
        gross_pnl = sell_turnover - buy_turnover
        net_pnl = gross_pnl - total_friction

        sell_cost_rate = (
            cls.OPTIONS_STT_SELL_RATE
            + cls.OPTIONS_EXCHANGE_TXN_RATE * (1.0 + cls.OPTIONS_GST_RATE)
            + cls.OPTIONS_SEBI_CHARGES_RATE
        )
        buy_cost_rate = (
            cls.OPTIONS_STAMP_DUTY_BUY_RATE
            + cls.OPTIONS_EXCHANGE_TXN_RATE * (1.0 + cls.OPTIONS_GST_RATE)
            + cls.OPTIONS_SEBI_CHARGES_RATE
        )

        if act == "SELL":
            # For Option Selling: s_prem is entry sell premium, b_prem is exit buyback premium
            # Breakeven buyback premium: Buy_Turnover * (1 + buy_cost_rate) = Sell_Turnover * (1 - sell_cost_rate) - Brokerage * (1 + GST)
            net_proceeds = sell_turnover * (1.0 - sell_cost_rate) - brokerage * (1.0 + cls.OPTIONS_GST_RATE)
            denom_sell = qty * (1.0 + buy_cost_rate)
            breakeven_exit = max(0.05, net_proceeds / denom_sell) if denom_sell > 0 else s_prem
            breakeven_points = max(0.0, s_prem - breakeven_exit)
        else:
            # For Option Buying: b_prem is entry buy premium, s_prem is exit sell premium
            buy_side_costs = (
                brokerage * (1.0 + cls.OPTIONS_GST_RATE)
                + buy_turnover * (
                    cls.OPTIONS_STAMP_DUTY_BUY_RATE
                    + cls.OPTIONS_EXCHANGE_TXN_RATE * (1.0 + cls.OPTIONS_GST_RATE)
                    + cls.OPTIONS_SEBI_CHARGES_RATE
                )
            )
            denom_buy = qty * (1.0 - sell_cost_rate)
            breakeven_exit = (buy_turnover + buy_side_costs) / denom_buy if denom_buy > 0 else b_prem
            breakeven_points = max(0.0, breakeven_exit - b_prem)

        return FOFrictionBreakdown(
            instrument_type="OPTION",
            brokerage=brokerage,
            stt=stt,
            exchange_txn_charge=exchange_txn,
            sebi_charges=sebi_charges,
            gst=gst,
            stamp_duty=stamp_duty,
            total_friction=total_friction,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            breakeven_exit_price=breakeven_exit,
            breakeven_points_required=breakeven_points,
        )

    @classmethod
    def calculate_spread_friction(
        cls,
        short_entry_prem: float,
        short_exit_prem: float,
        long_entry_prem: float,
        long_exit_prem: float,
        quantity: int
    ) -> FOFrictionBreakdown:
        """
        Calculates exact round-trip transaction friction for 2-leg Indian Option Spreads
        (e.g. Bull Put Credit Spread or Bear Call Credit Spread).
        """
        qty = max(1, int(quantity))
        p_short_in = max(0.0, float(short_entry_prem))
        p_short_out = max(0.0, float(short_exit_prem))
        p_long_in = max(0.0, float(long_entry_prem))
        p_long_out = max(0.0, float(long_exit_prem))

        # 4 orders total: Short Entry (SELL), Short Exit (BUY), Long Entry (BUY), Long Exit (SELL)
        brokerage = 4.0 * cls.OPTIONS_BROKERAGE_BUY

        total_sell_turnover = (p_short_in + p_long_out) * qty
        total_buy_turnover = (p_long_in + p_short_out) * qty
        total_turnover = total_sell_turnover + total_buy_turnover

        stt = total_sell_turnover * cls.OPTIONS_STT_SELL_RATE
        exchange_txn = total_turnover * cls.OPTIONS_EXCHANGE_TXN_RATE
        sebi_charges = total_turnover * cls.OPTIONS_SEBI_CHARGES_RATE
        gst = (brokerage + exchange_txn) * cls.OPTIONS_GST_RATE
        stamp_duty = total_buy_turnover * cls.OPTIONS_STAMP_DUTY_BUY_RATE

        total_friction = brokerage + stt + exchange_txn + sebi_charges + gst + stamp_duty
        gross_pnl = total_sell_turnover - total_buy_turnover
        net_pnl = gross_pnl - total_friction

        return FOFrictionBreakdown(
            instrument_type="SPREAD",
            brokerage=brokerage,
            stt=stt,
            exchange_txn_charge=exchange_txn,
            sebi_charges=sebi_charges,
            gst=gst,
            stamp_duty=stamp_duty,
            total_friction=total_friction,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            breakeven_exit_price=round(p_short_in - p_long_in, 2),
            breakeven_points_required=round(total_friction / qty, 2)
        )

    @classmethod
    def calculate_iron_condor_friction(
        cls,
        short_put_entry: float,
        short_put_exit: float,
        long_put_entry: float,
        long_put_exit: float,
        short_call_entry: float,
        short_call_exit: float,
        long_call_entry: float,
        long_call_exit: float,
        quantity: int
    ) -> FOFrictionBreakdown:
        """
        Calculates exact round-trip transaction friction for a 4-leg Indian Iron Condor
        (Short Put, Long Put, Short Call, Long Call).
        Total 8 orders (4 entry legs + 4 exit legs).
        """
        qty = max(1, int(quantity))
        sp_in = max(0.0, float(short_put_entry))
        sp_out = max(0.0, float(short_put_exit))
        lp_in = max(0.0, float(long_put_entry))
        lp_out = max(0.0, float(long_put_exit))

        sc_in = max(0.0, float(short_call_entry))
        sc_out = max(0.0, float(short_call_exit))
        lc_in = max(0.0, float(long_call_entry))
        lc_out = max(0.0, float(long_call_exit))

        # 8 orders: 4 entries + 4 exits = 8 * ₹20 = ₹160 flat brokerage
        brokerage = 8.0 * cls.OPTIONS_BROKERAGE_BUY

        total_sell_turnover = (sp_in + lp_out + sc_in + lc_out) * qty
        total_buy_turnover = (lp_in + sp_out + lc_in + sc_out) * qty
        total_turnover = total_sell_turnover + total_buy_turnover

        stt = total_sell_turnover * cls.OPTIONS_STT_SELL_RATE
        exchange_txn = total_turnover * cls.OPTIONS_EXCHANGE_TXN_RATE
        sebi_charges = total_turnover * cls.OPTIONS_SEBI_CHARGES_RATE
        gst = (brokerage + exchange_txn) * cls.OPTIONS_GST_RATE
        stamp_duty = total_buy_turnover * cls.OPTIONS_STAMP_DUTY_BUY_RATE

        total_friction = brokerage + stt + exchange_txn + sebi_charges + gst + stamp_duty
        gross_pnl = total_sell_turnover - total_buy_turnover
        net_pnl = gross_pnl - total_friction

        combined_net_credit = (sp_in - lp_in) + (sc_in - lc_in)

        return FOFrictionBreakdown(
            instrument_type="IRON_CONDOR",
            brokerage=brokerage,
            stt=stt,
            exchange_txn_charge=exchange_txn,
            sebi_charges=sebi_charges,
            gst=gst,
            stamp_duty=stamp_duty,
            total_friction=round(total_friction, 2),
            gross_pnl=round(gross_pnl, 2),
            net_pnl=round(net_pnl, 2),
            breakeven_exit_price=round(combined_net_credit, 2),
            breakeven_points_required=round(total_friction / qty, 2)
        )

    @classmethod
    def calculate_futures_friction(
        cls,
        entry_price: float,
        exit_price: float,
        quantity: int,
        direction: str = "LONG"
    ) -> FOFrictionBreakdown:
        """
        Calculates exact round-trip transaction friction for Indian Futures.
        """
        qty = max(1, int(quantity))
        p_entry = max(0.0, float(entry_price))
        p_exit = max(0.0, float(exit_price))
        is_long = str(direction).upper() in ("LONG", "BULLISH")

        if is_long:
            buy_turnover = p_entry * qty
            sell_turnover = p_exit * qty
            gross_pnl = (p_exit - p_entry) * qty
        else:
            sell_turnover = p_entry * qty
            buy_turnover = p_exit * qty
            gross_pnl = (p_entry - p_exit) * qty

        total_turnover = buy_turnover + sell_turnover

        brokerage = cls.FUTURES_BROKERAGE_BUY + cls.FUTURES_BROKERAGE_SELL
        stt = sell_turnover * cls.FUTURES_STT_SELL_RATE
        exchange_txn = total_turnover * cls.FUTURES_EXCHANGE_TXN_RATE
        sebi_charges = total_turnover * cls.FUTURES_SEBI_CHARGES_RATE
        gst = (brokerage + exchange_txn) * cls.FUTURES_GST_RATE
        stamp_duty = buy_turnover * cls.FUTURES_STAMP_DUTY_BUY_RATE

        total_friction = brokerage + stt + exchange_txn + sebi_charges + gst + stamp_duty
        net_pnl = gross_pnl - total_friction

        # Exact analytical breakeven exit price:
        sell_cost_rate = (
            cls.FUTURES_STT_SELL_RATE
            + cls.FUTURES_EXCHANGE_TXN_RATE * (1.0 + cls.FUTURES_GST_RATE)
            + cls.FUTURES_SEBI_CHARGES_RATE
        )
        buy_cost_rate = (
            cls.FUTURES_STAMP_DUTY_BUY_RATE
            + cls.FUTURES_EXCHANGE_TXN_RATE * (1.0 + cls.FUTURES_GST_RATE)
            + cls.FUTURES_SEBI_CHARGES_RATE
        )

        if is_long:
            buy_side_costs = brokerage * (1.0 + cls.FUTURES_GST_RATE) + buy_turnover * buy_cost_rate
            denom = qty * (1.0 - sell_cost_rate)
            breakeven_exit = (buy_turnover + buy_side_costs) / denom if denom > 0 else p_entry
            breakeven_points = max(0.0, breakeven_exit - p_entry)
        else:
            # Short Futures: sell at entry, buy back at exit
            net_entry_cash = sell_turnover * (1.0 - sell_cost_rate) - brokerage * (1.0 + cls.FUTURES_GST_RATE)
            denom = qty * (1.0 + buy_cost_rate)
            breakeven_exit = net_entry_cash / denom if denom > 0 else p_entry
            breakeven_points = max(0.0, p_entry - breakeven_exit)

        return FOFrictionBreakdown(
            instrument_type="FUTURE",
            brokerage=brokerage,
            stt=stt,
            exchange_txn_charge=exchange_txn,
            sebi_charges=sebi_charges,
            gst=gst,
            stamp_duty=stamp_duty,
            total_friction=total_friction,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            breakeven_exit_price=breakeven_exit,
            breakeven_points_required=breakeven_points,
        )


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class TradePlan:
    """A complete, actionable trade recommendation."""

    # Identification
    ticker: str
    direction: str  # "LONG" or "SHORT"

    # Prices
    entry_price: float
    stop_loss: float
    take_profit: float
    timeframe: str = "1h"  # "1h" or "1d"
    trailing_stop: Optional[float] = None

    # Risk Metrics
    risk_reward_ratio: float = 0.0
    risk_per_trade_pct: float = 0.0  # % of capital risked
    position_size_qty: int = 0
    position_value: float = 0.0
    max_loss_amount: float = 0.0
    max_profit_amount: float = 0.0

    # Probability & Statistics
    ai_probability: float = 0.0
    kelly_fraction: float = 0.0
    probability_of_ruin: float = 0.0
    win_rate: float = 0.5  # Historical win rate used
    capital: float = 100000.0  # Available user capital
    capital_tier: str = "STANDARD"  # MICRO, SMALL, or GROWTH

    # Context
    atr_at_entry: float = 0.0
    regime: str = "unknown"
    sl_method: str = ""  # "ATR" or "Swing Point"
    tp_method: str = ""  # "ATR" or "S/R Level"
    max_hold_bars: int = 0
    reasoning: str = ""

    # Real-World Indian F&O Friction & Breakeven
    estimated_friction: float = 0.0
    net_profit_amount: float = 0.0
    breakeven_price: float = 0.0

    # Gating
    is_approved: bool = True
    rejection_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "direction": self.direction,
            "timeframe": self.timeframe,
            "entry_price": round(self.entry_price, 2),
            "stop_loss": round(self.stop_loss, 2),
            "take_profit": round(self.take_profit, 2),
            "trailing_stop": round(self.trailing_stop, 2) if self.trailing_stop else None,
            "risk_reward_ratio": round(self.risk_reward_ratio, 2),
            "risk_per_trade_pct": round(self.risk_per_trade_pct, 4),
            "position_size_qty": self.position_size_qty,
            "position_value": round(self.position_value, 2),
            "max_loss_amount": round(self.max_loss_amount, 2),
            "max_profit_amount": round(self.max_profit_amount, 2),
            "estimated_friction": round(self.estimated_friction, 2),
            "net_profit_amount": round(self.net_profit_amount, 2),
            "breakeven_price": round(self.breakeven_price, 2),
            "ai_probability": round(self.ai_probability, 4),
            "kelly_fraction": round(self.kelly_fraction, 4),
            "probability_of_ruin": round(self.probability_of_ruin, 6),
            "win_rate": round(self.win_rate, 4),
            "capital": round(self.capital, 2),
            "capital_tier": self.capital_tier,
            "atr_at_entry": round(self.atr_at_entry, 4),
            "regime": self.regime,
            "sl_method": self.sl_method,
            "tp_method": self.tp_method,
            "max_hold_bars": self.max_hold_bars,
            "reasoning": self.reasoning,
            "is_approved": self.is_approved,
            "rejection_reasons": self.rejection_reasons,
        }


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Hard risk caps
MAX_RISK_PER_TRADE_PCT = 0.02   # Never risk more than 2% of capital per trade
MIN_RISK_REWARD_RATIO = 1.5     # Reject anything under 1.5:1 R:R
STT_SLIPPAGE_PCT = 0.0005       # 0.05% combined Indian STT + slippage friction

# Trailing stop parameters (in ATR multiples)
TRAIL_BREAKEVEN_THRESHOLD = 1.0  # Move SL to breakeven after 1× ATR move in our favor
TRAIL_LOCK_PROFIT_THRESHOLD = 1.5  # Lock in 0.5× ATR profit after 1.5× ATR move
TRAIL_LOCK_AMOUNT = 0.5  # ATR multiples of profit to lock

# Timeframe-specific hold limits
TIMEFRAME_HOLD_LIMITS = {
    "1h": 40,  # 40 hourly bars = ~1 week
    "1d": 20,  # 20 daily bars = ~1 month
}

# Correlation matrix for instruments we trade
# NIFTY and BANKNIFTY are ~0.92 correlated historically
CORRELATION_MATRIX = {
    ("^NSEI", "^NSEBANK"): 0.92,
    ("^NSEBANK", "^NSEI"): 0.92,
}

# If correlation > this threshold, treat positions as overlapping
CORRELATION_THRESHOLD = 0.70


# ---------------------------------------------------------------------------
# Risk Engine
# ---------------------------------------------------------------------------

class RiskEngine:
    """
    Institutional-grade risk management engine.
    
    Takes a raw AI signal and market data, outputs a complete trade plan
    or rejects the trade with explicit reasoning.
    """

    def __init__(self, historical_trades: Optional[List[Dict]] = None):
        """
        Args:
            historical_trades: List of past trade dicts with at minimum
                'status' ('CLOSED_WIN' or 'CLOSED_LOSS') and 'pnl_pct' fields.
                Used to compute historical win rate for Kelly and Ruin calculations.
        """
        self._historical_trades = historical_trades or []
        self._win_rate = self._compute_win_rate()
        self._avg_win = self._compute_avg_win()
        self._avg_loss = self._compute_avg_loss()

    def _compute_win_rate(self) -> float:
        """Calculate historical win rate from closed trades."""
        closed = [t for t in self._historical_trades
                  if t.get("status") in ("CLOSED_WIN", "CLOSED_LOSS")]
        if len(closed) < 5:
            # Not enough data — use conservative default
            return 0.50
        wins = sum(1 for t in closed if t["status"] == "CLOSED_WIN")
        return wins / len(closed)

    def _compute_avg_win(self) -> float:
        """Average winning trade return."""
        wins = [t.get("pnl_pct", 0) for t in self._historical_trades
                if t.get("status") == "CLOSED_WIN" and t.get("pnl_pct", 0) > 0]
        return float(np.mean(wins)) if wins else 0.01

    def _compute_avg_loss(self) -> float:
        """Average losing trade return (as positive number)."""
        losses = [abs(t.get("pnl_pct", 0)) for t in self._historical_trades
                  if t.get("status") == "CLOSED_LOSS" and t.get("pnl_pct", 0) < 0]
        return float(np.mean(losses)) if losses else 0.005

    @staticmethod
    def get_capital_tier(capital: float) -> Dict[str, Any]:
        """
        Dynamically classifies capital and adjusts risk limits, allocation caps,
        and prediction confidence thresholds.
        
        - MICRO (<= ₹25,000): e.g. ₹10k user. Ultra-tight risk, high confidence standard (68%+),
          early breakeven ratchet to ensure capital preservation.
        - SMALL (₹25,000 to ₹1 Lakh): Standard 2% risk, 65%+ confidence.
        - GROWTH (> ₹1 Lakh): Standard growth parameters.
        """
        cap = max(100.0, float(capital or 100000.0))
        if cap <= 25000.0:
            return {
                "tier": "MICRO",
                "label": "Micro Capital Tier (₹10k - ₹25k)",
                "max_risk_pct": 0.015,         # Max 1.5% risk per trade (e.g. ₹150 on ₹10k)
                "max_allocation_pct": 0.35,     # Max 35% of capital in a single stock
                "min_ai_confidence": 0.68,      # Strict confluence gate: never take weak trades
                "min_rr_ratio": 1.8,            # Demand minimum 1.8:1 edge
                "early_breakeven_atr": 0.8,     # Move to breakeven after 0.8× ATR move
            }
        elif cap <= 100000.0:
            return {
                "tier": "SMALL",
                "label": "Small Capital Tier (₹25k - ₹1 Lakh)",
                "max_risk_pct": 0.02,          # Max 2% risk per trade
                "max_allocation_pct": 0.30,
                "min_ai_confidence": 0.65,
                "min_rr_ratio": 1.5,
                "early_breakeven_atr": 1.0,
            }
        else:
            return {
                "tier": "GROWTH",
                "label": "Standard/Growth Capital Tier (> ₹1 Lakh)",
                "max_risk_pct": 0.02,
                "max_allocation_pct": 0.25,
                "min_ai_confidence": 0.60,
                "min_rr_ratio": 1.5,
                "early_breakeven_atr": 1.0,
            }

    # -----------------------------------------------------------------------
    # Core: Generate a complete trade plan
    # -----------------------------------------------------------------------

    def generate_trade_plan(
        self,
        ticker: str,
        direction: str,  # "bullish" or "bearish"
        ai_probability: float,
        df: pd.DataFrame,
        capital: float,
        regime: str = "unknown",
        timeframe: str = "1h",
        open_positions: Optional[List[Dict]] = None,
    ) -> TradePlan:
        """
        Generate a complete, actionable trade plan from a raw signal.

        Args:
            ticker: The instrument ticker (e.g., "^NSEI")
            direction: "bullish" or "bearish"
            ai_probability: AI confidence (0.0 to 1.0)
            df: OHLCV DataFrame with 'close', 'high', 'low', 'atr' columns
            capital: Current available capital
            regime: Current market regime string
            timeframe: "1h" or "1d"
            open_positions: List of currently open trade dicts for correlation check

        Returns:
            TradePlan with all fields populated, including approval status.
        """
        trade_dir = "LONG" if direction.lower() == "bullish" else "SHORT"
        close = float(df["close"].iloc[-1])
        atr = float(df["atr"].iloc[-1]) if "atr" in df.columns else self._calculate_atr(df)

        # Prevent zero or NaN ATR
        if math.isnan(atr) or atr <= 0:
            atr = close * 0.01

        max_hold = TIMEFRAME_HOLD_LIMITS.get(timeframe, 20)

        # 1. Calculate Entry Price (with slippage)
        if trade_dir == "LONG":
            entry = close * (1 + STT_SLIPPAGE_PCT)
        else:
            entry = close * (1 - STT_SLIPPAGE_PCT)

        # 2. Calculate Stop Loss (ATR-based vs Swing Point — pick the tighter one)
        sl_price, sl_method = self._calculate_stop_loss(df, entry, atr, trade_dir)

        # 3. Calculate Take Profit (ATR-based vs S/R level — pick optimal)
        tp_price, tp_method = self._calculate_take_profit(df, entry, atr, trade_dir, sl_price)

        # 4. Calculate Risk:Reward Ratio
        sl_distance = abs(entry - sl_price)
        tp_distance = abs(tp_price - entry)

        if sl_distance <= 1e-4:
            sl_distance = max(1.0, atr if atr > 0 else entry * 0.01)  # Fallback

        calc_rr = tp_distance / sl_distance if sl_distance > 1e-4 else 0.0
        # Cap rr_ratio at 100.0 to prevent infinite or absurd values if sl_distance is tiny
        rr_ratio = min(100.0, max(0.0, calc_rr)) if math.isfinite(calc_rr) else 0.0

        # 5. Position Sizing adapted dynamically to User Capital Tier
        tier = self.get_capital_tier(capital)
        kelly_f = self._kelly_criterion(ai_probability, rr_ratio)
        risk_pct = min(kelly_f, tier["max_risk_pct"])
        risk_pct = max(risk_pct, 0.001)  # Floor at 0.1% to avoid zero positions

        capital_at_risk = capital * risk_pct
        raw_qty = int(capital_at_risk / sl_distance) if sl_distance > 0 else 0

        # Max allocation cap (e.g. max 35% of total capital in any single instrument)
        max_position_val = capital * tier["max_allocation_pct"]
        alloc_qty = int(max_position_val / entry) if entry > 0 else 0
        qty = min(raw_qty, alloc_qty)

        # Micro-Capital Adaptation (e.g. ₹10,000 capital):
        # If integer truncation resulted in qty == 0, but user has enough capital
        # to safely buy 1 share without risking more than 2.5% of their capital, allow 1 share!
        if qty <= 0 and entry <= max_position_val and sl_distance <= (capital * 0.025):
            qty = 1

        position_val = qty * entry if qty > 0 else 0.0
        max_loss = qty * sl_distance
        max_profit = qty * tp_distance

        # 6. Probability of Ruin
        p_ruin = self._probability_of_ruin(
            win_rate=self._win_rate,
            avg_win=tp_distance,
            avg_loss=sl_distance,
            risk_fraction=risk_pct
        )

        # 7. Indian F&O Friction and Breakeven Calculation
        f_breakdown = IndianFOFrictionModel.calculate_futures_friction(
            entry_price=entry,
            exit_price=tp_price,
            quantity=max(1, qty),
            direction=trade_dir
        )
        est_friction = f_breakdown.total_friction
        be_price = f_breakdown.breakeven_exit_price
        net_profit = max(0.0, max_profit - est_friction)

        # 8. Build the Trade Plan
        plan = TradePlan(
            ticker=ticker,
            direction=trade_dir,
            timeframe=timeframe,
            entry_price=entry,
            stop_loss=sl_price,
            take_profit=tp_price,
            trailing_stop=sl_price,  # Initial trailing stop = SL
            risk_reward_ratio=rr_ratio,
            risk_per_trade_pct=risk_pct,
            position_size_qty=qty,
            position_value=position_val,
            max_loss_amount=max_loss,
            max_profit_amount=max_profit,
            estimated_friction=est_friction,
            net_profit_amount=net_profit,
            breakeven_price=be_price,
            ai_probability=ai_probability,
            kelly_fraction=kelly_f,
            probability_of_ruin=p_ruin,
            win_rate=self._win_rate,
            capital=capital,
            capital_tier=tier["tier"],
            atr_at_entry=atr,
            regime=regime,
            sl_method=sl_method,
            tp_method=tp_method,
            max_hold_bars=max_hold,
        )

        # 9. Apply Rejection Gates
        self._apply_gates(plan, open_positions or [])

        # 10. Build reasoning string
        plan.reasoning = self._build_reasoning(plan)

        return plan

    # -----------------------------------------------------------------------
    # Stop Loss Calculation
    # -----------------------------------------------------------------------

    def _calculate_stop_loss(
        self, df: pd.DataFrame, entry: float, atr: float, direction: str
    ) -> Tuple[float, str]:
        """
        Calculate optimal stop loss using:
        1. ATR-based: 1× ATR from entry
        2. Swing Point: Recent pivot high/low
        
        Uses whichever provides a tighter, more logical stop.
        """
        # ATR-based SL
        if direction == "LONG":
            atr_sl = entry - (1.0 * atr)
        else:
            atr_sl = entry + (1.0 * atr)

        # Swing Point SL
        try:
            sr_levels = find_support_resistance(
                df["close"], df["high"], df["low"], lookback=50, num_levels=5
            )

            if direction == "LONG" and sr_levels["support"]:
                # Find nearest support below entry
                supports_below = [s for s in sr_levels["support"] if s < entry]
                if supports_below:
                    swing_sl = max(supports_below)  # Closest support below
                    # Only use swing point if it's within 1.5× ATR distance
                    # (too far = not meaningful)
                    if abs(entry - swing_sl) <= 1.5 * atr:
                        # Use the tighter of ATR and swing point
                        if swing_sl > atr_sl:
                            return swing_sl, "Swing Point"
            elif direction == "SHORT" and sr_levels["resistance"]:
                resistances_above = [r for r in sr_levels["resistance"] if r > entry]
                if resistances_above:
                    swing_sl = min(resistances_above)  # Closest resistance above
                    if abs(swing_sl - entry) <= 1.5 * atr:
                        if swing_sl < atr_sl:
                            return swing_sl, "Swing Point"
        except Exception as e:
            logger.debug(f"Swing point SL calculation failed: {e}")

        return atr_sl, "ATR"

    # -----------------------------------------------------------------------
    # Take Profit Calculation
    # -----------------------------------------------------------------------

    def _calculate_take_profit(
        self, df: pd.DataFrame, entry: float, atr: float, direction: str,
        sl_price: float
    ) -> Tuple[float, str]:
        """
        Calculate optimal take profit using:
        1. ATR-based: 2× ATR from entry (default 2:1 R:R target)
        2. S/R Level: Next resistance (for longs) or support (for shorts)
        
        Uses whichever is closest to achieving 2:1 R:R without being unrealistic.
        """
        sl_distance = abs(entry - sl_price)

        # ATR-based TP (targeting 2:1 R:R minimum)
        if direction == "LONG":
            atr_tp = entry + (2.0 * atr)
        else:
            atr_tp = entry - (2.0 * atr)

        # S/R Level TP
        try:
            sr_levels = find_support_resistance(
                df["close"], df["high"], df["low"], lookback=50, num_levels=5
            )

            if direction == "LONG" and sr_levels["resistance"]:
                # Find resistance levels above entry
                resistances_above = sorted([r for r in sr_levels["resistance"] if r > entry])
                for res_level in resistances_above:
                    tp_distance = res_level - entry
                    # Only use S/R target if it achieves at least 1.5:1 R:R
                    if sl_distance > 0 and (tp_distance / sl_distance) >= MIN_RISK_REWARD_RATIO:
                        # Use S/R level if it's more conservative (closer) than 2× ATR
                        if res_level < atr_tp:
                            return res_level, "S/R Level"
                        break  # The ATR target is closer, use that

            elif direction == "SHORT" and sr_levels["support"]:
                supports_below = sorted([s for s in sr_levels["support"] if s < entry], reverse=True)
                for sup_level in supports_below:
                    tp_distance = entry - sup_level
                    if sl_distance > 0 and (tp_distance / sl_distance) >= MIN_RISK_REWARD_RATIO:
                        if sup_level > atr_tp:
                            return sup_level, "S/R Level"
                        break
        except Exception as e:
            logger.debug(f"S/R TP calculation failed: {e}")

        return atr_tp, "ATR"

    # -----------------------------------------------------------------------
    # Kelly Criterion Position Sizing
    # -----------------------------------------------------------------------

    def _kelly_criterion(self, win_probability: float, reward_risk_ratio: float) -> float:
        """
        Calculate Half-Kelly fraction for position sizing.
        
        Full Kelly = p - (1-p)/b
        where p = win probability, b = reward/risk ratio
        
        We use Half-Kelly (divide by 2) as a safety margin because:
        - Full Kelly is mathematically optimal but assumes perfect edge estimation
        - Half-Kelly sacrifices ~25% of theoretical returns but reduces variance by ~50%
        - This is what professional quant funds use in practice
        
        Returns:
            Fraction of capital to risk (capped at MAX_RISK_PER_TRADE_PCT)
        """
        p = max(0.01, min(0.99, win_probability if (isinstance(win_probability, (int, float)) and math.isfinite(win_probability)) else 0.5))
        q = 1.0 - p
        safe_b = reward_risk_ratio if (isinstance(reward_risk_ratio, (int, float)) and math.isfinite(reward_risk_ratio)) else 1.0
        b = max(0.01, safe_b)

        full_kelly = p - (q / b)

        if full_kelly <= 0 or not math.isfinite(full_kelly):
            # Negative Kelly means the edge is insufficient — size at minimum
            return 0.005  # 0.5% risk floor for exploration

        half_kelly = full_kelly / 2.0
        return min(half_kelly, MAX_RISK_PER_TRADE_PCT)

    # -----------------------------------------------------------------------
    # Probability of Ruin
    # -----------------------------------------------------------------------

    def _probability_of_ruin(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        risk_fraction: float,
        ruin_threshold: float = 0.5  # Account destroyed at 50% drawdown
    ) -> float:
        """
        Calculate the probability that a sequence of trades will draw the account
        down to the ruin threshold.
        
        Uses the classic gambler's ruin formula adapted for asymmetric payoffs:
        
        P(ruin) = ((1 - edge) / (1 + edge))^N
        
        where:
            edge = (win_rate × avg_win) - ((1 - win_rate) × avg_loss)
            N = number of risk units until ruin
        
        This accounts for the sequence-of-losses risk that a flat per-trade 
        percentage rule completely misses. A trader with 55% win rate and 2:1 R:R
        has very different ruin probability at 2% risk vs 10% risk.
        """
        safe_wr = win_rate if (isinstance(win_rate, (int, float)) and math.isfinite(win_rate)) else 0.5
        p = max(0.01, min(0.99, safe_wr))
        q = 1.0 - p

        # Expected value per trade in risk-units
        safe_win = avg_win if (isinstance(avg_win, (int, float)) and math.isfinite(avg_win) and avg_win >= 0) else 1.0
        safe_loss = avg_loss if (isinstance(avg_loss, (int, float)) and math.isfinite(avg_loss) and avg_loss > 0) else 1.0
        payoff_ratio = safe_win / safe_loss if safe_loss > 0 else 1.0

        # Edge per trade
        edge = (p * payoff_ratio) - q

        if edge <= 0:
            # Negative edge — ruin is nearly certain
            return 0.99

        # Number of risk units until ruin
        if not (isinstance(risk_fraction, (int, float)) and math.isfinite(risk_fraction)) or risk_fraction <= 0:
            return 0.0
        
        safe_thresh = max(0.01, min(0.99, ruin_threshold if (isinstance(ruin_threshold, (int, float)) and math.isfinite(ruin_threshold)) else 0.5))
        n_units = -math.log(1.0 - safe_thresh) / risk_fraction

        # Ruin probability using the adapted formula
        ratio = q / (p * payoff_ratio) if (p * payoff_ratio) > 0 else 1.0

        if ratio >= 1.0:
            return 0.99  # No edge, ruin nearly certain

        try:
            p_ruin = ratio ** n_units
        except (OverflowError, ValueError):
            p_ruin = 0.0

        return max(0.0, min(1.0, p_ruin))

    # -----------------------------------------------------------------------
    # Trailing Stop Management
    # -----------------------------------------------------------------------

    @staticmethod
    def update_trailing_stop(
        trade: Dict[str, Any],
        current_high: float,
        current_low: float,
    ) -> Dict[str, Any]:
        """
        Update trailing stop for an open trade based on current price action.
        
        Logic:
        1. After price moves 1× ATR in our favor → trail SL to breakeven
        2. After price moves 1.5× ATR in our favor → lock in 0.5× ATR profit
        3. Never move the trailing stop backwards (only tighten)
        
        Args:
            trade: Trade dict with 'direction', 'entry_price', 'atr_at_entry',
                   'trailing_stop', 'sl' keys
            current_high: Current bar's high
            current_low: Current bar's low
            
        Returns:
            Updated trade dict with new trailing_stop value
        """
        entry = float(trade.get("entry_price", 0.0))
        atr = trade.get("atr_at_entry")
        if atr is None or math.isnan(atr) or atr <= 0 or entry <= 0:
            return trade

        current_trail = trade.get("trailing_stop")
        if current_trail is None:
            current_trail = trade.get("sl")
        if current_trail is None:
            current_trail = entry

        is_micro = trade.get("capital_tier") == "MICRO" or trade.get("invested", 0) <= 25000
        be_thresh = 0.8 if is_micro else TRAIL_BREAKEVEN_THRESHOLD

        if trade.get("direction") == "LONG":
            # How far has price moved in our favor?
            favorable_move = current_high - entry

            if favorable_move >= TRAIL_LOCK_PROFIT_THRESHOLD * atr:
                # Lock in 0.5× ATR profit
                new_trail = entry + (TRAIL_LOCK_AMOUNT * atr)
            elif favorable_move >= be_thresh * atr:
                # Move to breakeven (+ minor buffer for STT friction)
                new_trail = entry * 1.0005
            else:
                new_trail = current_trail

            # Never move trailing stop downward
            trade["trailing_stop"] = max(current_trail, new_trail)

        elif trade.get("direction") == "SHORT":
            favorable_move = entry - current_low

            if favorable_move >= TRAIL_LOCK_PROFIT_THRESHOLD * atr:
                new_trail = entry - (TRAIL_LOCK_AMOUNT * atr)
            elif favorable_move >= be_thresh * atr:
                # Move to breakeven (- minor buffer for STT friction)
                new_trail = entry * 0.9995
            else:
                new_trail = current_trail

            # Never move trailing stop upward (for shorts)
            trade["trailing_stop"] = min(current_trail, new_trail)

        return trade

    # -----------------------------------------------------------------------
    # Time-Based Exit Check
    # -----------------------------------------------------------------------

    @staticmethod
    def check_time_exit(trade: Dict[str, Any], bars_held: int) -> bool:
        """
        Check if a trade has exceeded its maximum hold period.
        
        Returns True if the trade should be force-closed.
        """
        max_hold = trade.get("max_hold_bars", 20)
        return bars_held >= max_hold

    # -----------------------------------------------------------------------
    # Portfolio Correlation Check
    # -----------------------------------------------------------------------

    @staticmethod
    def check_correlation(
        ticker: str,
        direction: str,
        open_positions: List[Dict[str, Any]]
    ) -> Tuple[bool, str]:
        """
        Check if opening a new position would create hidden correlation risk.
        
        For example, going LONG on both NIFTY and BANKNIFTY is effectively
        a 2× leveraged bet on the same index — not diversification.
        
        Args:
            ticker: Proposed new ticker
            direction: "LONG" or "SHORT"
            open_positions: List of currently open trade dicts
            
        Returns:
            (is_correlated, reason) — True if correlated risk detected
        """
        if not open_positions:
            return False, ""

        for pos in open_positions:
            if pos.get("status") != "OPEN":
                continue

            existing_ticker = pos.get("ticker", "")
            existing_dir = pos.get("direction", "")

            # Check correlation matrix
            pair = (ticker, existing_ticker)
            corr = CORRELATION_MATRIX.get(pair, 0.0)

            if corr >= CORRELATION_THRESHOLD:
                if existing_dir == direction:
                    # Same direction on correlated instruments = hidden concentration
                    return True, (
                        f"CORRELATION BLOCK: {ticker} ({direction}) is {corr*100:.0f}% "
                        f"correlated with existing {existing_dir} position in "
                        f"{existing_ticker}. This is effectively a double-sized bet. "
                        f"Reduce existing position or skip."
                    )
                else:
                    # Opposite direction on correlated instruments = hedged (OK)
                    pass

        return False, ""

    # -----------------------------------------------------------------------
    # Rejection Gate
    # -----------------------------------------------------------------------

    def _apply_gates(self, plan: TradePlan, open_positions: List[Dict]) -> None:
        """
        Apply all rejection gates to a trade plan.
        If any gate fails, mark the plan as rejected with reasons.
        """
        rejections = []
        tier = self.get_capital_tier(plan.capital)

        # Gate 0: Capital Affordability Check
        if plan.entry_price > plan.capital:
            rejections.append(
                f"Capital Insufficiency: Instrument spot price ₹{plan.entry_price:,.2f} exceeds "
                f"available capital ₹{plan.capital:,.2f}. Trade affordable constituent equities (e.g. SBIN, TATAMOTORS, ITC) or Options instead."
            )

        # Gate 1: Risk:Reward minimum (Dynamically strict for Micro accounts)
        min_rr = tier["min_rr_ratio"]
        if plan.risk_reward_ratio < min_rr:
            rejections.append(
                f"R:R ratio {plan.risk_reward_ratio:.2f}:1 is below {min_rr}:1 minimum required for "
                f"{tier['tier']} capital tier. High-precision rule requires asymmetric reward to risk."
            )

        # Gate 2: Position size must be positive
        if plan.position_size_qty <= 0:
            rejections.append(
                f"Position size calculated as 0 units. Capital (₹{plan.capital:,.2f}) is insufficient "
                f"for 1 share at ₹{plan.entry_price:,.2f} within the safe risk allocation limits."
            )

        # Gate 3: Probability of Ruin (Strict 8% cap)
        if plan.probability_of_ruin > 0.08:
            rejections.append(
                f"Probability of Ruin is {plan.probability_of_ruin*100:.2f}% — "
                f"exceeds 8% safety threshold. Skipping trade to guarantee capital preservation."
            )

        # Gate 4: Correlation check
        is_correlated, corr_reason = self.check_correlation(
            plan.ticker, plan.direction, open_positions
        )
        if is_correlated:
            rejections.append(corr_reason)

        # Gate 5: AI confidence floor (Dynamically calibrated to Capital Tier)
        min_conf = tier["min_ai_confidence"]
        if plan.ai_probability < min_conf:
            rejections.append(
                f"AI confidence {plan.ai_probability*100:.1f}% is below {min_conf*100:.1f}% requirement "
                f"for {tier['tier']} capital tier. High-precision confluence standard not met."
            )

        # Gate 6: Real-World Indian F&O Friction & Breakeven Check
        if plan.max_profit_amount > 0 and plan.max_profit_amount <= plan.estimated_friction:
            rejections.append(
                f"Friction Deficit: Expected profit (₹{plan.max_profit_amount:,.2f}) does not cover "
                f"estimated Indian transaction friction (₹{plan.estimated_friction:,.2f}). Breakeven price: ₹{plan.breakeven_price:,.2f}."
            )

        if rejections:
            plan.is_approved = False
            plan.rejection_reasons = rejections

    # -----------------------------------------------------------------------
    # Reasoning Builder
    # -----------------------------------------------------------------------

    def _build_reasoning(self, plan: TradePlan) -> str:
        """Build a human-readable trade plan summary."""
        if not plan.is_approved:
            return (
                f"⛔ TRADE REJECTED for {plan.ticker} ({plan.direction})\n"
                + "\n".join(f"  • {r}" for r in plan.rejection_reasons)
            )

        sl_dist_pct = abs(plan.entry_price - plan.stop_loss) / plan.entry_price * 100
        tp_dist_pct = abs(plan.take_profit - plan.entry_price) / plan.entry_price * 100

        return (
            f"✅ TRADE APPROVED: {plan.direction} {plan.ticker}\n"
            f"  📊 Entry:  ₹{plan.entry_price:,.2f}\n"
            f"  🎯 Target: ₹{plan.take_profit:,.2f} (+{tp_dist_pct:.2f}%) [{plan.tp_method}]\n"
            f"  🛑 Stop:   ₹{plan.stop_loss:,.2f} (-{sl_dist_pct:.2f}%) [{plan.sl_method}]\n"
            f"  ⚖️  R:R Ratio: {plan.risk_reward_ratio:.2f}:1\n"
            f"  📐 Position: {plan.position_size_qty} units × ₹{plan.entry_price:,.2f} = ₹{plan.position_value:,.2f}\n"
            f"  💰 Max Loss: ₹{plan.max_loss_amount:,.2f} ({plan.risk_per_trade_pct*100:.2f}% of capital)\n"
            f"  💎 Max Profit: ₹{plan.max_profit_amount:,.2f} (Net after friction: ₹{plan.net_profit_amount:,.2f})\n"
            f"  🏷️  Est. Friction: ₹{plan.estimated_friction:,.2f} | Breakeven: ₹{plan.breakeven_price:,.2f}\n"
            f"  🧠 AI Confidence: {plan.ai_probability*100:.1f}% | Kelly: {plan.kelly_fraction*100:.2f}%\n"
            f"  📉 P(Ruin): {plan.probability_of_ruin*100:.4f}% | Win Rate: {plan.win_rate*100:.1f}%\n"
            f"  ⏱️  Max Hold: {plan.max_hold_bars} bars | Regime: {plan.regime}\n"
        )

    # -----------------------------------------------------------------------
    # Utility
    # -----------------------------------------------------------------------

    @staticmethod
    def _calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
        """Calculate ATR from raw OHLCV data."""
        high_low = df["high"] - df["low"]
        high_close = np.abs(df["high"] - df["close"].shift())
        low_close = np.abs(df["low"] - df["close"].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        atr_series = true_range.rolling(period, min_periods=1).mean()
        if len(atr_series) == 0:
            return 1.0
        atr = float(atr_series.iloc[-1])
        if math.isnan(atr) or atr <= 0:
            close = float(df["close"].iloc[-1]) if "close" in df else 100.0
            return float(close * 0.01)
        return float(atr)
