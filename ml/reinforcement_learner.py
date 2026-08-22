"""
Reinforcement Learner — Phase 7: Contextual Bandit for Setup Reweighting.

Treats each paper trade as an episode and uses P&L as the reward signal
to learn which setups are actually profitable in which regimes.

This is a Contextual Bandit, not full RL, because:
1. Actions are independent (each trade is a separate episode)
2. The "context" is the regime + which setups fired
3. The "reward" is the trade P&L
4. We learn a weight per (setup, regime) pair

The bandit uses an exponential-weighted moving average (EWMA) with
Thompson Sampling to balance exploration vs exploitation.
"""

from __future__ import annotations

import json
import os
import logging
import math
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict

import numpy as np

from ml.trade_logger import TradeLogger

logger = logging.getLogger("trading.rl_learner")

WEIGHTS_FILE = "ml/models/setup_weights.json"
RL_HISTORY_FILE = "ml/models/rl_history.json"


class ReinforcementLearner:
    """
    Contextual Bandit that learns optimal setup weights from paper-trade outcomes.
    
    For each (setup, regime) pair, maintains:
    - alpha: Prior success count (Beta distribution)
    - beta: Prior failure count (Beta distribution)
    - ewma_reward: Exponential weighted moving average of rewards
    - n_observations: Number of times this pair has been observed
    
    The weight for a setup in a given regime is the Thompson-sampled
    expected value from its Beta posterior.
    """

    def __init__(self, weights_file: Optional[str] = None):
        self.weights_file = weights_file or WEIGHTS_FILE
        self._state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        """Load learned weights from disk."""
        if os.path.exists(self.weights_file):
            try:
                with open(self.weights_file, "r", encoding="utf-8") as f:
                    state = json.load(f)
                logger.info(f"Loaded RL state with {len(state.get('weights', {}))} setup-regime pairs")
                return state
            except Exception as e:
                logger.warning(f"Failed to load RL state: {e}")

        return {
            "weights": {},      # {setup_name: {regime: {"alpha": ..., "beta": ..., "ewma": ..., "n": ...}}}
            "global_weights": {},  # {setup_name: weight}  — regime-agnostic weight
            "version": 0,
            "last_update": None,
        }

    def _save_state(self) -> None:
        """Persist learned weights to disk."""
        os.makedirs(os.path.dirname(self.weights_file) or ".", exist_ok=True)
        try:
            import datetime
            self._state["last_update"] = datetime.datetime.now().isoformat()
            with open(self.weights_file, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save RL state: {e}")

    # -------------------------------------------------------------------
    # Core: Learn from a completed trade
    # -------------------------------------------------------------------

    def update_from_trade(
        self,
        setup_signals: List[Dict[str, Any]],
        regime: str,
        pnl_pct: float,
        is_win: bool,
    ) -> None:
        """
        Update the bandit's beliefs based on a completed trade outcome.
        
        Args:
            setup_signals: List of {name, signal, confidence} dicts for setups
                          that fired at entry time
            regime: The market regime at entry time
            pnl_pct: The trade's P&L as a decimal (e.g., 0.02 = 2%)
            is_win: Whether the trade was a winner
        """
        weights = self._state["weights"]
        ewma_decay = 0.1  # How fast old observations decay (higher = faster)

        for setup in setup_signals:
            name = setup.get("name", "")
            signal = setup.get("signal", "neutral")
            conf = setup.get("confidence", 0)

            # Only update for setups that actually contributed to the decision
            if signal == "neutral" or conf <= 0:
                continue

            # Initialize if needed
            if name not in weights:
                weights[name] = {}
            if regime not in weights[name]:
                weights[name][regime] = {
                    "alpha": 1.0,  # Prior: assume uniform (1 success)
                    "beta": 1.0,   # Prior: assume uniform (1 failure)
                    "ewma_reward": 0.0,
                    "n": 0,
                }

            state = weights[name][regime]

            # Update Beta distribution
            if is_win:
                state["alpha"] += 1.0
            else:
                state["beta"] += 1.0

            # Update EWMA reward
            state["ewma_reward"] = (
                (1 - ewma_decay) * state["ewma_reward"] + ewma_decay * pnl_pct
            )
            state["n"] += 1

        # Update global (regime-agnostic) weights
        self._update_global_weights()
        self._state["version"] += 1
        self._save_state()

    # -------------------------------------------------------------------
    # Compute Current Weights
    # -------------------------------------------------------------------

    def get_setup_weights(self, regime: str = "unknown") -> Dict[str, float]:
        """
        Get the current learned weight for each setup in the given regime.
        
        Uses Thompson Sampling: draw from each setup's Beta posterior
        and normalize to get weights. This naturally balances exploration
        (uncertain setups get sampled widely) vs exploitation (proven setups
        converge to stable high weights).
        
        Returns:
            Dict mapping setup name to weight (0.0 to 1.0, normalized)
        """
        weights = self._state["weights"]
        
        if not weights:
            # No learning yet — return uniform weights
            return {}

        sampled = {}
        for setup_name, regimes in weights.items():
            if regime in regimes:
                state = regimes[regime]
            else:
                # Fall back to global/average state
                all_states = list(regimes.values())
                avg_alpha = np.mean([s["alpha"] for s in all_states])
                avg_beta = np.mean([s["beta"] for s in all_states])
                state = {"alpha": avg_alpha, "beta": avg_beta}

            # Thompson Sample from Beta(alpha, beta)
            alpha = max(state["alpha"], 0.1)
            beta_val = max(state["beta"], 0.1)
            sample = np.random.beta(alpha, beta_val)
            sampled[setup_name] = sample

        # Normalize to [0, 1] range
        if sampled:
            max_val = max(sampled.values())
            if max_val > 0:
                sampled = {k: v / max_val for k, v in sampled.items()}

        return sampled

    def get_deterministic_weights(self, regime: str = "unknown") -> Dict[str, float]:
        """
        Get deterministic (non-sampled) weights based on the posterior mean.
        Used for logging and display, not for decision-making.
        
        Returns:
            Dict mapping setup name to weight (posterior mean E[Beta] = alpha / (alpha + beta))
        """
        weights = self._state["weights"]
        result = {}

        for setup_name, regimes in weights.items():
            if regime in regimes:
                state = regimes[regime]
            else:
                all_states = list(regimes.values())
                state = {
                    "alpha": np.mean([s["alpha"] for s in all_states]),
                    "beta": np.mean([s["beta"] for s in all_states]),
                }

            alpha = state["alpha"]
            beta_val = state["beta"]
            result[setup_name] = alpha / (alpha + beta_val) if (alpha + beta_val) > 0 else 0.5

        return result

    def _update_global_weights(self) -> None:
        """Compute regime-agnostic global weights for each setup."""
        global_weights = {}
        for setup_name, regimes in self._state["weights"].items():
            all_alphas = [s["alpha"] for s in regimes.values()]
            all_betas = [s["beta"] for s in regimes.values()]
            total_alpha = sum(all_alphas)
            total_beta = sum(all_betas)
            global_weights[setup_name] = total_alpha / (total_alpha + total_beta) if (total_alpha + total_beta) > 0 else 0.5
        self._state["global_weights"] = global_weights

    # -------------------------------------------------------------------
    # Batch Learning (Weekly Retrain)
    # -------------------------------------------------------------------

    def batch_learn_from_journal(self) -> int:
        """
        Re-learn weights from the complete trade journal.
        Called during weekly scheduled retraining.
        
        Returns the number of trades processed.
        """
        entries = TradeLogger.get_all_entries()
        exits = TradeLogger.get_all_exits()

        entry_map = {e["trade_id"]: e for e in entries}

        # Reset state for clean re-learn
        self._state["weights"] = {}
        self._state["global_weights"] = {}

        count = 0
        for exit_rec in exits:
            trade_id = exit_rec.get("trade_id")
            entry_rec = entry_map.get(trade_id, {})

            setup_signals = entry_rec.get("setup_signals", [])
            regime = entry_rec.get("regime", "unknown")
            pnl = exit_rec.get("pnl_pct", 0)
            is_win = pnl > 0

            if setup_signals:
                self.update_from_trade(setup_signals, regime, pnl, is_win)
                count += 1

        logger.info(f"[RL] Batch re-learned from {count} completed trades")
        return count

    # -------------------------------------------------------------------
    # Diagnostics
    # -------------------------------------------------------------------

    def get_diagnostics(self) -> Dict[str, Any]:
        """Return internal state for debugging."""
        return {
            "version": self._state["version"],
            "last_update": self._state.get("last_update"),
            "n_setup_regime_pairs": sum(
                len(regimes) for regimes in self._state["weights"].values()
            ),
            "global_weights": self._state["global_weights"],
        }

    # -------------------------------------------------------------------
    # Closed-Loop: Apply JournalAnalyzer Insights
    # -------------------------------------------------------------------

    def apply_insights(self, insights: List[Dict[str, Any]]) -> List[str]:
        """
        Apply actionable insights from JournalAnalyzer to adjust setup weights.

        For each insight:
        - "suppress": multiply the setup's alpha by action_value (< 1.0)
        - "boost": multiply the setup's alpha by action_value (> 1.0)

        Returns a list of human-readable actions taken.
        """
        actions_taken = []
        weights = self._state["weights"]

        for insight in insights:
            action = insight.get("action", "")
            setup = insight.get("setup", "")
            regime = insight.get("regime", "all")
            value = insight.get("action_value", 1.0)
            severity = insight.get("severity", "info")

            if action in ("suppress", "boost") and setup and setup != "PORTFOLIO":
                if setup in weights:
                    target_regimes = [regime] if regime != "all" else list(weights[setup].keys())
                    for r in target_regimes:
                        if r in weights[setup]:
                            old_alpha = weights[setup][r]["alpha"]
                            weights[setup][r]["alpha"] = max(0.1, old_alpha * value)
                            action_str = (
                                f"[{severity.upper()}] {action.upper()} {setup} in '{r}': "
                                f"alpha {old_alpha:.2f} → {weights[setup][r]['alpha']:.2f}"
                            )
                            actions_taken.append(action_str)
                            logger.info(f"[RL] {action_str}")

        if actions_taken:
            self._update_global_weights()
            self._state["version"] += 1
            self._save_state()

        return actions_taken

    def full_self_review(self) -> Dict[str, Any]:
        """
        Complete self-review cycle:
        1. Re-learn from journal (batch)
        2. Run JournalAnalyzer
        3. Apply insights
        
        Returns the full analysis report with actions taken.
        """
        from ml.journal_analyzer import JournalAnalyzer

        # Step 1: Batch re-learn from all trades
        n_trades = self.batch_learn_from_journal()

        # Step 2: Analyze journal for meta-patterns
        analyzer = JournalAnalyzer()
        report = analyzer.analyze()

        # Step 3: Apply insights
        insights = report.get("insights", [])
        actions = self.apply_insights(insights)

        report["actions_taken"] = actions
        report["trades_processed"] = n_trades

        logger.info(
            f"[RL] Self-review complete. "
            f"Processed {n_trades} trades, generated {len(insights)} insights, "
            f"took {len(actions)} actions."
        )

        return report

