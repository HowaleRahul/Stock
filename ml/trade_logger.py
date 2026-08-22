"""
Trade Logger — Phase 7: Comprehensive trade journaling.

Every trade is logged with full context:
- Which setups fired and their individual signals/confidences
- The regime at entry and exit
- The RL-learned weights used at decision time
- Config version that produced the trade
- Full P&L accounting
"""

from __future__ import annotations

import json
import os
import csv
import logging
import datetime
from contextvars import ContextVar
from typing import Dict, Any, List, Optional

logger = logging.getLogger("trading.trade_logger")

TRADE_LOG_DIR = "logs"
TRADE_LOG_FILE = os.path.join(TRADE_LOG_DIR, "trade_journal.jsonl")
TRADE_LOG_CSV = os.path.join(TRADE_LOG_DIR, "trade_journal.csv")
_active_log_file = ContextVar("active_trade_log_file", default=TRADE_LOG_FILE)

os.makedirs(TRADE_LOG_DIR, exist_ok=True)


class TradeLogger:
    """
    Append-only trade journal in JSONL format.
    
    Each line is a complete, self-contained trade record with every piece
    of context needed to reconstruct why the system took the trade.
    This is the audit trail that makes the system's decisions traceable.
    """

    @staticmethod
    def use_log_file(path: str):
        return _active_log_file.set(path)

    @staticmethod
    def reset_log_file(token) -> None:
        _active_log_file.reset(token)

    @staticmethod
    def _current_log_file() -> str:
        return _active_log_file.get()

    @staticmethod
    def log_entry(
        trade_id: str,
        ticker: str,
        direction: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        quantity: int,
        invested: float,
        risk_pct: float,
        risk_reward: float,
        ai_probability: float,
        kelly_fraction: float,
        probability_of_ruin: float,
        regime: str,
        regime_adx: float,
        sl_method: str,
        tp_method: str,
        timeframe: str,
        atr_at_entry: float,
        setup_signals: List[Dict[str, Any]],
        setup_weights: Dict[str, float],
        config_version: str,
        capital_at_entry: float,
    ) -> Dict[str, Any]:
        """Log a new trade entry to the journal."""
        record = {
            "event": "ENTRY",
            "timestamp": datetime.datetime.now().isoformat(),
            "trade_id": trade_id,
            "ticker": ticker,
            "direction": direction,
            "entry_price": round(entry_price, 4),
            "stop_loss": round(stop_loss, 4),
            "take_profit": round(take_profit, 4),
            "quantity": quantity,
            "invested": round(invested, 2),
            "risk_pct": round(risk_pct, 6),
            "risk_reward": round(risk_reward, 4),
            "ai_probability": round(ai_probability, 4),
            "kelly_fraction": round(kelly_fraction, 4),
            "probability_of_ruin": round(probability_of_ruin, 6),
            "regime": regime,
            "regime_adx": round(regime_adx, 4),
            "sl_method": sl_method,
            "tp_method": tp_method,
            "timeframe": timeframe,
            "atr_at_entry": round(atr_at_entry, 4),
            "setup_signals": setup_signals,
            "setup_weights": setup_weights,
            "config_version": config_version,
            "capital_at_entry": round(capital_at_entry, 2),
        }
        TradeLogger._append(record)
        logger.info(f"[JOURNAL] Logged ENTRY for {trade_id} ({ticker} {direction})")
        return record

    @staticmethod
    def log_exit(
        trade_id: str,
        ticker: str,
        direction: str,
        exit_price: float,
        exit_reason: str,
        pnl_pct: float,
        cash_pnl: float,
        bars_held: int,
        regime_at_exit: str,
        capital_after_exit: float,
        setup_signals_at_entry: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Log a trade exit to the journal."""
        record = {
            "event": "EXIT",
            "timestamp": datetime.datetime.now().isoformat(),
            "trade_id": trade_id,
            "ticker": ticker,
            "direction": direction,
            "exit_price": round(exit_price, 4),
            "exit_reason": exit_reason,
            "pnl_pct": round(pnl_pct, 6),
            "cash_pnl": round(cash_pnl, 2),
            "bars_held": bars_held,
            "regime_at_exit": regime_at_exit,
            "capital_after_exit": round(capital_after_exit, 2),
        }
        if setup_signals_at_entry:
            record["setup_signals_at_entry"] = setup_signals_at_entry
        TradeLogger._append(record)
        logger.info(
            f"[JOURNAL] Logged EXIT for {trade_id} ({exit_reason}, "
            f"PnL: {pnl_pct*100:+.2f}%)"
        )
        return record

    @staticmethod
    def log_rejection(
        ticker: str,
        direction: str,
        reasons: List[str],
        ai_probability: float,
        regime: str,
        config_version: str,
    ) -> Dict[str, Any]:
        """Log a rejected trade for analysis."""
        record = {
            "event": "REJECTION",
            "timestamp": datetime.datetime.now().isoformat(),
            "ticker": ticker,
            "direction": direction,
            "reasons": reasons,
            "ai_probability": round(ai_probability, 4),
            "regime": regime,
            "config_version": config_version,
        }
        TradeLogger._append(record)
        return record

    @staticmethod
    def log_kill_switch(
        reason: str,
        capital: float,
        peak_capital: float,
        weekly_pnl: float,
        config_version: str,
    ) -> Dict[str, Any]:
        """Log a kill-switch activation."""
        record = {
            "event": "KILL_SWITCH",
            "timestamp": datetime.datetime.now().isoformat(),
            "reason": reason,
            "capital": round(capital, 2),
            "peak_capital": round(peak_capital, 2),
            "weekly_pnl": round(weekly_pnl, 2),
            "config_version": config_version,
        }
        TradeLogger._append(record)
        logger.error(f"[JOURNAL] KILL SWITCH: {reason}")
        return record

    @staticmethod
    def get_all_exits() -> List[Dict[str, Any]]:
        """Read all EXIT records from the journal."""
        exits = []
        log_file = TradeLogger._current_log_file()
        if not os.path.exists(log_file):
            return exits
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    if record.get("event") == "EXIT":
                        exits.append(record)
        except Exception as e:
            logger.error(f"Error reading trade journal: {e}")
        return exits

    @staticmethod
    def get_all_entries() -> List[Dict[str, Any]]:
        """Read all ENTRY records from the journal."""
        entries = []
        log_file = TradeLogger._current_log_file()
        if not os.path.exists(log_file):
            return entries
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    if record.get("event") == "ENTRY":
                        entries.append(record)
        except Exception as e:
            logger.error(f"Error reading trade journal: {e}")
        return entries

    @staticmethod
    def get_recent_exits(n_days: int = 7) -> List[Dict[str, Any]]:
        """Get EXIT records from the last N days."""
        cutoff = datetime.datetime.now() - datetime.timedelta(days=n_days)
        recent = []
        for record in TradeLogger.get_all_exits():
            try:
                ts = datetime.datetime.fromisoformat(record["timestamp"])
                if ts >= cutoff:
                    recent.append(record)
            except (KeyError, ValueError):
                continue
        return recent

    @staticmethod
    def _append(record: Dict[str, Any]) -> None:
        """Append a single JSON record to the journal file."""
        try:
            with open(TradeLogger._current_log_file(), "a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")
        except Exception as e:
            logger.error(f"Failed to write trade journal: {e}")

    @staticmethod
    def export_csv() -> str:
        """Export the journal to a flat CSV for spreadsheet analysis."""
        exits = TradeLogger.get_all_exits()
        if not exits:
            return ""

        fieldnames = [
            "timestamp", "trade_id", "ticker", "direction",
            "exit_price", "exit_reason", "pnl_pct", "cash_pnl",
            "bars_held", "regime_at_exit", "capital_after_exit"
        ]
        try:
            with open(TRADE_LOG_CSV, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(exits)
            logger.info(f"Exported {len(exits)} trade exits to {TRADE_LOG_CSV}")
            return TRADE_LOG_CSV
        except Exception as e:
            logger.error(f"CSV export failed: {e}")
            return ""
