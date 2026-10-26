"""
Momentum Masters Swing Toolkit — Unified Orchestrator & Watchlist Manager.

Connects the 3 Scanners, 8-Factor Filter Checklist, and 15m ORB Entry Breakout Engine.
Manages the Active Swing Watchlist persisted to disk.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from typing import Dict, Any, List, Optional
import pandas as pd

from data.fetcher import YFinanceFetcher
from setups.swing_toolkit.scanners import SwingScannerSuite
from setups.swing_toolkit.checklist import SwingFilterChecklist, QualityScoreResult
from setups.swing_toolkit.orb_entry import ORBBreakoutEngine, ORBExecutionPlan
from setups.swing_toolkit.universe import DEFAULT_SWING_UNIVERSE, BENCHMARK_TICKER, STOCK_SECTORS

logger = logging.getLogger("trading.setups.swing_toolkit")

WATCHLIST_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "swing_watchlist.json")
_watchlist_lock = threading.RLock()


class SwingToolkitManager:
    """
    Unified manager for running scanners, applying the 8-factor checklist,
    managing the winning watchlist, and evaluating ORB breakout entries.
    """

    def __init__(self) -> None:
        self.scanner_suite = SwingScannerSuite()
        self.checklist = SwingFilterChecklist()
        self.orb_engine = ORBBreakoutEngine()
        self._ensure_watchlist_file()

    def _ensure_watchlist_file(self) -> None:
        os.makedirs(os.path.dirname(WATCHLIST_FILE), exist_ok=True)
        if not os.path.exists(WATCHLIST_FILE):
            default_seeds = [
                {
                    "ticker": "HAL",
                    "sector": "Defense",
                    "source_scanners": ["Momentum", "ATH Contraction"],
                    "composite_score": 87.5,
                    "vcp_detected": True,
                    "stage_2": True,
                    "added_at": "2026-10-21",
                    "notes": "Tight contraction along 10 EMA near ATH, defense sector momentum leader.",
                },
                {
                    "ticker": "TRENT",
                    "sector": "Retail",
                    "source_scanners": ["Momentum", "ATH Contraction"],
                    "composite_score": 92.0,
                    "vcp_detected": True,
                    "stage_2": True,
                    "added_at": "2026-10-21",
                    "notes": "Market leader at All-Time Highs, textbook Weinstein Stage 2 markup.",
                },
                {
                    "ticker": "BEL",
                    "sector": "Defense",
                    "source_scanners": ["DWIB Inside Bar"],
                    "composite_score": 82.5,
                    "vcp_detected": True,
                    "stage_2": True,
                    "added_at": "2026-10-21",
                    "notes": "Weekly inside bar squeeze on 50-day pivot base, early volume drying up.",
                },
            ]
            self.save_watchlist(default_seeds)

    def load_watchlist(self) -> List[Dict[str, Any]]:
        """Loads the persisted active swing watchlist."""
        with _watchlist_lock:
            if os.path.exists(WATCHLIST_FILE):
                try:
                    with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception as e:
                    logger.error(f"Error loading swing watchlist: {e}")
            return []

    def save_watchlist(self, items: List[Dict[str, Any]]) -> None:
        """Atomically saves the active swing watchlist using a unique temp file."""
        import tempfile
        with _watchlist_lock:
            directory = os.path.dirname(os.path.abspath(WATCHLIST_FILE))
            os.makedirs(directory, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".watchlist-", suffix=".json")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(items, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                import time
                replaced = False
                last_err = None
                for attempt in range(5):
                    try:
                        os.replace(tmp_path, WATCHLIST_FILE)
                        replaced = True
                        break
                    except PermissionError as pe:
                        last_err = pe
                        time.sleep(0.02 * (attempt + 1))
                if not replaced and last_err:
                    raise last_err
            except Exception as e:
                logger.error(f"Error saving swing watchlist: {e}")
                if os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass

    def add_to_watchlist(self, candidate: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Adds a candidate to the active watchlist if not already present."""
        with _watchlist_lock:
            items = self.load_watchlist()
            ticker = candidate["ticker"].upper().strip()
            # Remove existing if present to update
            items = [it for it in items if it["ticker"] != ticker]
            items.append(candidate)
            self.save_watchlist(items)
            return items

    def remove_from_watchlist(self, ticker: str) -> List[Dict[str, Any]]:
        """Removes a ticker from the active swing watchlist."""
        with _watchlist_lock:
            clean_ticker = ticker.upper().strip()
            items = [it for it in self.load_watchlist() if it["ticker"] != clean_ticker]
            self.save_watchlist(items)
            return items

    async def run_scanners_and_filter(
        self,
        universe: Optional[List[str]] = None,
        period: str = "1y",
    ) -> Dict[str, Any]:
        """
        Executes the Weekly Routine:
        1. Runs the 3 Scanners (Momentum, DWIB, ATH) across the universe.
        2. Passes all hits through the 8-Factor Quality Checklist.
        3. Returns ranked candidates with actionable metrics.
        """
        target_universe = universe or DEFAULT_SWING_UNIVERSE

        # Fetch benchmark data for Relative Strength (RS) scoring
        bm_suffix = f"{BENCHMARK_TICKER}"
        benchmark_df = None
        try:
            benchmark_df = await YFinanceFetcher.fetch_history(bm_suffix, period=period, interval="1d")
        except Exception as e:
            logger.warning(f"Could not fetch benchmark {BENCHMARK_TICKER}: {e}")

        # Scan universe concurrently with semaphore limit
        semaphore = asyncio.Semaphore(5)

        async def _process_symbol(sym: str):
            async with semaphore:
                try:
                    # Resolve symbol to Yahoo Finance ticker
                    yf_sym = sym
                    if sym in ("NIFTY", "NIFTY 50"):
                        yf_sym = "^NSEI"
                    elif sym in ("BANKNIFTY", "NIFTY BANK"):
                        yf_sym = "^NSEBANK"
                    elif sym in ("SENSEX", "BSE SENSEX"):
                        yf_sym = "^BSESN"
                    elif not (sym.startswith("^") or "." in sym):
                        yf_sym = f"{sym}.NS"

                    # Gentle inter-request pacing to protect rate limits
                    await asyncio.sleep(0.04)

                    df = await YFinanceFetcher.fetch_history(yf_sym, period=period, interval="1d")
                    if df is None or len(df) < 50:
                        return None

                    scan_res = self.scanner_suite.scan_symbol(df, sym)
                    if not scan_res["is_hit"]:
                        return None

                    # Pass hit through 8-Factor Checklist
                    checklist_res = self.checklist.evaluate(df, sym, benchmark_df=benchmark_df)

                    return {
                        "ticker": sym,
                        "sector": STOCK_SECTORS.get(sym, "General"),
                        "matched_scanners": scan_res["matched_scanners"],
                        "confluence_count": scan_res["confluence_count"],
                        "composite_score": checklist_res.composite_score,
                        "qualifies_for_watchlist": checklist_res.qualifies_for_watchlist,
                        "summary": checklist_res.summary,
                        "checklist": checklist_res.to_dict(),
                        "scanner_metrics": {
                            "momentum": scan_res["results"]["momentum"].metrics,
                            "dwib": scan_res["results"]["dwib"].metrics,
                            "ath": scan_res["results"]["ath"].metrics,
                        },
                        "cur_close": float(df["close"].iloc[-1]),
                        "change_pct": round(float(((df["close"].iloc[-1] - df["close"].iloc[-2]) / df["close"].iloc[-2]) * 100), 2),
                    }
                except Exception as ex:
                    logger.warning(f"Error scanning {sym}: {ex}")
                    return None

        tasks = [_process_symbol(sym) for sym in target_universe]
        raw_results = await asyncio.gather(*tasks)
        hits = [r for r in raw_results if r is not None]

        # Rank hits: First by Watchlist qualification, then by Composite Score descending
        hits.sort(key=lambda x: (x["qualifies_for_watchlist"], x["composite_score"], x["confluence_count"]), reverse=True)

        qualified_count = sum(1 for h in hits if h["qualifies_for_watchlist"])

        return {
            "total_universe_scanned": len(target_universe),
            "total_scanner_hits": len(hits),
            "qualified_for_watchlist": qualified_count,
            "candidates": hits,
            "weekly_routine_guide": {
                "step1": "Run scanners once or twice a week (done).",
                "step2": "Filter every hit through the 8-factor checklist (done).",
                "step3": "Add top qualifying names (Score >= 70) in strong sectors to your watchlist.",
                "step4": "On breakout day, apply 15m ORB entry with 5m/15m volume gating.",
                "step5": "Predefine risk at ORB low, size position strictly, do not chase.",
            },
        }

    async def evaluate_orb_breakout(
        self,
        ticker: str,
        capital: float = 1000000.0,
        risk_per_trade_pct: float = 0.015,
    ) -> Dict[str, Any]:
        """
        Fetches live intraday 5m and daily bars for a watchlist candidate
        and runs the 15m ORB + early Volume Gate evaluation.
        """
        yf_sym = ticker
        if ticker in ("NIFTY", "NIFTY 50"):
            yf_sym = "^NSEI"
        elif ticker in ("BANKNIFTY", "NIFTY BANK"):
            yf_sym = "^NSEBANK"
        elif ticker in ("SENSEX", "BSE SENSEX"):
            yf_sym = "^BSESN"
        elif not (ticker.startswith("^") or "." in ticker):
            yf_sym = f"{ticker}.NS"

        try:
            intraday_5m_df = await YFinanceFetcher.fetch_history(yf_sym, period="5d", interval="5m")
            daily_df = await YFinanceFetcher.fetch_history(yf_sym, period="3mo", interval="1d")
        except Exception as e:
            return {
                "ticker": ticker,
                "error": f"Failed to fetch market data: {str(e)}",
                "is_triggered": False,
            }

        plan = self.orb_engine.evaluate_entry(
            intraday_5m_df=intraday_5m_df,
            daily_df=daily_df,
            ticker=ticker,
            capital=capital,
            risk_per_trade_pct=risk_per_trade_pct,
        )

        return plan.to_dict()
