"""
Options / Index Recommendation Engine — Phase 8

Translates a Spot/Futures-based TradePlan into a specific, lot-size-aware
Index Options recommendation (Buy Call / Buy Put).

Uses theoretical Black-Scholes pricing since live Indian options chain data
is not directly available via the current data source.
"""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass
from typing import Dict, Any, Optional

import scipy.stats as si
import numpy as np

from ml.risk_engine import TradePlan

logger = logging.getLogger("trading.options_engine")


@dataclass
class OptionsTradePlan:
    """A complete options trade recommendation."""
    original_plan: TradePlan
    
    option_symbol: str
    option_type: str  # "CE" (Call) or "PE" (Put)
    strike_price: float
    lot_size: int
    lots_to_buy: int
    
    # Premium Estimates (Theoretical)
    entry_premium: float
    target_premium: float
    stop_loss_premium: float
    
    # Options Specific Risk Metrics
    delta: float
    theta: float
    gamma: float
    vega: float
    
    total_premium_invested: float
    max_loss_amount: float
    max_profit_amount: float
    risk_reward_ratio: float
    
    is_approved: bool = True
    rejection_reasons: list = None
    reasoning: str = ""

    def __post_init__(self):
        if self.rejection_reasons is None:
            self.rejection_reasons = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "option_symbol": self.option_symbol,
            "option_type": self.option_type,
            "strike_price": self.strike_price,
            "lot_size": self.lot_size,
            "lots_to_buy": self.lots_to_buy,
            "entry_premium": round(self.entry_premium, 2),
            "target_premium": round(self.target_premium, 2),
            "stop_loss_premium": round(self.stop_loss_premium, 2),
            "delta": round(self.delta, 4),
            "theta": round(self.theta, 4),
            "total_premium_invested": round(self.total_premium_invested, 2),
            "max_loss_amount": round(self.max_loss_amount, 2),
            "max_profit_amount": round(self.max_profit_amount, 2),
            "risk_reward_ratio": round(self.risk_reward_ratio, 2),
            "is_approved": self.is_approved,
            "rejection_reasons": self.rejection_reasons,
            "reasoning": self.reasoning,
        }


class OptionsEngine:
    """
    Translates Spot signals into Options Trade Plans using Black-Scholes.
    """
    
    # Contract specifications
    LOT_SIZES = {
        "^NSEI": 25,     # NIFTY 50
        "^NSEBANK": 15,  # BANKNIFTY
    }
    
    STRIKE_INTERVALS = {
        "^NSEI": 50,
        "^NSEBANK": 100,
    }
    
    # Constants
    DAYS_TO_EXPIRY = 7.0       # Assume weekly options (7 days to expiry)
    RISK_FREE_RATE = 0.06      # 6% repo rate assumption
    DEFAULT_IV = 0.15          # 15% IV fallback

    def __init__(self):
        pass

    def _round_to_nearest(self, x: float, base: int) -> int:
        return int(base * round(x / base))

    def _black_scholes(self, S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> dict:
        """
        Calculate Theoretical Option Premium and Greeks using Black-Scholes-Merton.
        
        S = Spot price
        K = Strike price
        T = Time to expiry (in years)
        r = Risk-free interest rate
        sigma = Volatility (IV)
        option_type = "CE" or "PE"
        """
        if T <= 0:
            return {"premium": 0.0, "delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
            
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        
        try:
            if option_type == "CE":
                premium = (S * si.norm.cdf(d1, 0.0, 1.0) - K * np.exp(-r * T) * si.norm.cdf(d2, 0.0, 1.0))
                delta = si.norm.cdf(d1, 0.0, 1.0)
                theta = (- (S * si.norm.pdf(d1, 0.0, 1.0) * sigma) / (2 * np.sqrt(T)) 
                         - r * K * np.exp(-r * T) * si.norm.cdf(d2, 0.0, 1.0))
            else: # "PE"
                premium = (K * np.exp(-r * T) * si.norm.cdf(-d2, 0.0, 1.0) - S * si.norm.cdf(-d1, 0.0, 1.0))
                delta = -si.norm.cdf(-d1, 0.0, 1.0)
                theta = (- (S * si.norm.pdf(d1, 0.0, 1.0) * sigma) / (2 * np.sqrt(T)) 
                         + r * K * np.exp(-r * T) * si.norm.cdf(-d2, 0.0, 1.0))
                
            gamma = si.norm.pdf(d1, 0.0, 1.0) / (S * sigma * np.sqrt(T))
            vega = S * si.norm.pdf(d1, 0.0, 1.0) * np.sqrt(T)
            
            # Theta is usually expressed per day
            theta_per_day = theta / 365.0
            
            return {
                "premium": max(0.01, premium), # ensure positive premium
                "delta": delta,
                "gamma": gamma,
                "theta": theta_per_day,
                "vega": vega / 100.0 # vega is usually per 1% change in IV
            }
        except Exception:
            # Fallback for math errors
            return {"premium": 0.01, "delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}

    def generate_options_plan(self, plan: TradePlan, iv: float = None, pcr: float = 1.0, max_pain: float = None) -> OptionsTradePlan:
        """
        Converts a spot TradePlan into an OptionsTradePlan.
        """
        ticker = plan.ticker
        if ticker not in self.LOT_SIZES:
            # Cannot convert non-index or unconfigured instruments
            opt_plan = OptionsTradePlan(
                original_plan=plan, option_symbol="", option_type="", strike_price=0,
                lot_size=0, lots_to_buy=0, entry_premium=0, target_premium=0, stop_loss_premium=0,
                delta=0, theta=0, gamma=0, vega=0, total_premium_invested=0, max_loss_amount=0,
                max_profit_amount=0, risk_reward_ratio=0, is_approved=False,
                rejection_reasons=["Options trading not configured for this ticker."]
            )
            return opt_plan
            
        # 1. Determine Option Type & Initial Strike (At-The-Money)
        option_type = "CE" if plan.direction == "LONG" else "PE"
        interval = self.STRIKE_INTERVALS[ticker]
        atm_strike = self._round_to_nearest(plan.entry_price, interval)
        
        # 1b. Phase 3 Options-Specific Setups Check (Mocked for YFinance)
        # If PCR is highly contrarian or Max Pain is far away, we log it as reasoning
        phase3_reasoning = ""
        if option_type == "CE" and pcr > 1.5:
            phase3_reasoning = " (PCR > 1.5 supports Bullish)"
        elif option_type == "PE" and pcr < 0.7:
            phase3_reasoning = " (PCR < 0.7 supports Bearish)"
        if max_pain:
            phase3_reasoning += f" [Max Pain: {max_pain}]"
            
        # 2. Strike Hunting based on budget (Try ATM, then up to 2 strikes OTM)
        sigma = iv if iv and iv > 0 else self.DEFAULT_IV
        T = self.DAYS_TO_EXPIRY / 365.0
        r = self.RISK_FREE_RATE
        capital_at_risk = plan.max_loss_amount
        lot_size = self.LOT_SIZES[ticker]
        
        strike_price = atm_strike
        bs_current = None
        lots_to_buy = 0
        expected_loss_per_qty = 0
        
        for strike_offset in [0, 1, 2]:
            if option_type == "CE":
                test_strike = atm_strike + (strike_offset * interval)
            else:
                test_strike = atm_strike - (strike_offset * interval)
                
            bs_test = self._black_scholes(plan.entry_price, test_strike, T, r, sigma, option_type)
            
            # Premium at Stop Loss
            days_to_sl = 1.0
            T_sl = max(0.001, (self.DAYS_TO_EXPIRY - days_to_sl) / 365.0)
            bs_sl_test = self._black_scholes(plan.stop_loss, test_strike, T_sl, r, sigma, option_type)
            
            test_loss_per_qty = bs_test["premium"] - bs_sl_test["premium"]
            test_loss_per_qty = max(0.01, test_loss_per_qty)
            
            qty_to_buy = capital_at_risk / test_loss_per_qty
            test_lots = int(qty_to_buy // lot_size)
            
            if test_lots >= 1:
                strike_price = test_strike
                bs_current = bs_test
                lots_to_buy = test_lots
                expected_loss_per_qty = test_loss_per_qty
                break
                
        # If even 2 OTM strikes couldn't fit the budget, fallback to ATM and it will be rejected by the gate
        if not bs_current:
            strike_price = atm_strike
            bs_current = self._black_scholes(plan.entry_price, strike_price, T, r, sigma, option_type)
            days_to_sl = 1.0
            T_sl = max(0.001, (self.DAYS_TO_EXPIRY - days_to_sl) / 365.0)
            bs_sl_test = self._black_scholes(plan.stop_loss, strike_price, T_sl, r, sigma, option_type)
            expected_loss_per_qty = max(0.01, bs_current["premium"] - bs_sl_test["premium"])
            lots_to_buy = int((capital_at_risk / expected_loss_per_qty) // lot_size)
        
        option_symbol = f"{ticker.replace('^', '')} {strike_price} {option_type}"
        entry_premium = bs_current["premium"]
        
        # Premium at Target
        # Assume Target is reached in max_hold_bars (e.g. 2 days)
        days_to_target = 2.0
        T_target = max(0.001, (self.DAYS_TO_EXPIRY - days_to_target) / 365.0)
        bs_target = self._black_scholes(plan.take_profit, strike_price, T_target, r, sigma, option_type)
        target_premium = bs_target["premium"]
        
        days_to_sl = 1.0
        T_sl = max(0.001, (self.DAYS_TO_EXPIRY - days_to_sl) / 365.0)
        bs_sl = self._black_scholes(plan.stop_loss, strike_price, T_sl, r, sigma, option_type)
        stop_loss_premium = bs_sl["premium"]
        
        expected_profit_per_qty = target_premium - entry_premium
        total_qty = lots_to_buy * lot_size
        total_premium_invested = total_qty * entry_premium
        max_loss = total_qty * expected_loss_per_qty
        max_profit = total_qty * expected_profit_per_qty
        
        # Recalculate R:R for the option
        rr_ratio = max_profit / max_loss if max_loss > 0 else 0.0
        
        opt_plan = OptionsTradePlan(
            original_plan=plan,
            option_symbol=option_symbol,
            option_type=option_type,
            strike_price=strike_price,
            lot_size=lot_size,
            lots_to_buy=lots_to_buy,
            entry_premium=entry_premium,
            target_premium=target_premium,
            stop_loss_premium=stop_loss_premium,
            delta=bs_current["delta"],
            theta=bs_current["theta"],
            gamma=bs_current["gamma"],
            vega=bs_current["vega"],
            total_premium_invested=total_premium_invested,
            max_loss_amount=max_loss,
            max_profit_amount=max_profit,
            risk_reward_ratio=rr_ratio,
            is_approved=True,
            rejection_reasons=[]
        )
        
        # 4. Options-Specific Gating
        self._apply_options_gates(opt_plan)
        opt_plan.reasoning = self._build_reasoning(opt_plan) + phase3_reasoning
        
        return opt_plan
        
    def _apply_options_gates(self, opt_plan: OptionsTradePlan):
        """Apply options-specific risk checks."""
        # Gate 1: Check if we can afford even 1 lot
        if opt_plan.lots_to_buy < 1:
            opt_plan.rejection_reasons.append(
                f"Insufficient risk budget for 1 lot. Premium: ₹{opt_plan.entry_premium:.2f}, "
                f"Lot Size: {opt_plan.lot_size}. Risk allowed: ₹{opt_plan.original_plan.max_loss_amount:.2f}"
            )
            opt_plan.is_approved = False
            
        # Gate 2: Theta Decay Check
        # If the daily theta decay is too high relative to expected profit, skip.
        # e.g., if Theta is -₹5/day and we expect a ₹10 profit, time will kill the trade.
        expected_hold_days = opt_plan.original_plan.max_hold_bars / 24.0 # approximate days
        total_theta_decay = abs(opt_plan.theta) * max(1.0, expected_hold_days)
        expected_profit_per_qty = (opt_plan.target_premium - opt_plan.entry_premium)
        
        if expected_profit_per_qty > 0 and (total_theta_decay / expected_profit_per_qty) > 0.40:
            opt_plan.rejection_reasons.append(
                f"Theta decay (-₹{abs(opt_plan.theta):.2f}/day) is too high. "
                f"It will eat >40% of the expected profit over {expected_hold_days:.1f} days."
            )
            opt_plan.is_approved = False
            
        # Gate 3: Options R:R check (Options often have worse R:R due to spread/premium)
        if opt_plan.risk_reward_ratio < 1.2:
            opt_plan.rejection_reasons.append(
                f"Options R:R {opt_plan.risk_reward_ratio:.2f}:1 is too low (minimum 1.2:1)."
            )
            opt_plan.is_approved = False

    def _build_reasoning(self, plan: OptionsTradePlan) -> str:
        if not plan.is_approved:
            return (
                f"⛔ OPTIONS TRADE REJECTED for {plan.option_symbol}\n"
                + "\n".join(f"  • {r}" for r in plan.rejection_reasons)
                + f"\n  Original Spot reasoning: {plan.original_plan.reasoning}"
            )
            
        return (
            f"✅ OPTIONS TRADE APPROVED: {plan.option_symbol}\n"
            f"  ⚡ Delta: {plan.delta:.3f} | ⏳ Theta: ₹{plan.theta:.2f}/day\n"
            f"  📊 Entry Premium:  ₹{plan.entry_premium:,.2f}\n"
            f"  🎯 Target Prem:    ₹{plan.target_premium:,.2f}\n"
            f"  🛑 Stop Premium:   ₹{plan.stop_loss_premium:,.2f}\n"
            f"  ⚖️  Options R:R:    {plan.risk_reward_ratio:.2f}:1\n"
            f"  📐 Position: {plan.lots_to_buy} lots ({plan.lots_to_buy * plan.lot_size} qty) "
            f"= ₹{plan.total_premium_invested:,.2f} invested\n"
            f"  💰 Max Risk: ₹{plan.max_loss_amount:,.2f} | 💎 Max Profit: ₹{plan.max_profit_amount:,.2f}\n"
            f"  Underlying Spot: {plan.original_plan.entry_price:.2f} ({plan.original_plan.direction})\n"
        )
