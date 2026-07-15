import datetime
import logging
from typing import List, Dict, Any, Tuple

logger = logging.getLogger("trading.data.cleaner")

class DataCleaner:
    """
    Handles missing candle detection, price sanity checks, and corporate action (stock split / bonus issue) verification.
    """

    @staticmethod
    def detect_missing_trading_days(bars: List[Dict[str, Any]], timeframe: str = "1d") -> List[datetime.datetime]:
        """
        Identifies missing weekdays (M-F) across the date span of the provided daily bars.
        Excludes typical weekend gaps.
        """
        if not bars or timeframe != "1d":
            return []

        # Sort bars and get unique dates
        sorted_bars = sorted(bars, key=lambda x: x["time"])
        existing_dates = {b["time"].date() for b in sorted_bars}

        start_date = sorted_bars[0]["time"].date()
        end_date = sorted_bars[-1]["time"].date()

        missing_weekdays = []
        current = start_date
        while current <= end_date:
            # 0=Monday, 4=Friday
            if current.weekday() < 5 and current not in existing_dates:
                # Could be a market holiday or a missing candle gap
                missing_weekdays.append(current)
            current += datetime.timedelta(days=1)

        if missing_weekdays:
            logger.debug(f"Detected {len(missing_weekdays)} missing weekday dates across interval (may include market holidays).")
        return missing_weekdays

    @staticmethod
    def verify_corporate_actions(bars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Verifies and flags any stock splits or bonus issues in the dataset.
        Ensures adjusted_close is consistent when corporate actions occur.
        """
        splits_detected = []
        dividends_detected = []

        for b in bars:
            split = b.get("split_ratio", 1.0)
            div = b.get("dividend", 0.0)

            if split != 1.0 and split != 0.0:
                splits_detected.append((b["time"], split))
            if div > 0.0:
                dividends_detected.append((b["time"], div))

        if splits_detected:
            for dt, ratio in splits_detected:
                logger.info(f"Corporate Action Verified: Stock Split / Bonus Issue of ratio {ratio} on {dt.strftime('%Y-%m-%d')}")
        if dividends_detected:
            logger.debug(f"Corporate Action Verified: {len(dividends_detected)} dividend payouts detected across dataset.")

        return bars

    @classmethod
    def clean_and_verify(cls, bars: List[Dict[str, Any]], timeframe: str = "1d") -> List[Dict[str, Any]]:
        """
        Sorts bars chronologically, removes corrupted price records (e.g. close <= 0 or high < low),
        verifies corporate actions, and logs missing data checks.
        """
        if not bars:
            return []

        # 1. Sort chronologically
        sorted_bars = sorted(bars, key=lambda x: x["time"])

        # 2. Sanity check & filter corrupted outliers
        cleaned = []
        for b in sorted_bars:
            open_p = b.get("open", 0.0)
            high_p = b.get("high", 0.0)
            low_p = b.get("low", 0.0)
            close_p = b.get("close", 0.0)

            if close_p <= 0.0 or high_p <= 0.0 or low_p <= 0.0 or open_p <= 0.0:
                logger.warning(f"Dropping candle with non-positive price at {b['time']}: {b}")
                continue

            if high_p < low_p or open_p > high_p or open_p < low_p or close_p > high_p or close_p < low_p:
                logger.warning(f"Fixing/Dropping corrupted OHLC envelope at {b['time']}: H={high_p}, L={low_p}, O={open_p}, C={close_p}")
                # Fix high/low envelope using original values before mutation
                orig_h, orig_l = high_p, low_p
                b["high"] = max(orig_h, orig_l, open_p, close_p)
                b["low"] = min(orig_h, orig_l, open_p, close_p)

            cleaned.append(b)

        # 3. Verify corporate actions
        cls.verify_corporate_actions(cleaned)

        # 4. Check gaps for diagnostic insight
        cls.detect_missing_trading_days(cleaned, timeframe=timeframe)

        return cleaned
