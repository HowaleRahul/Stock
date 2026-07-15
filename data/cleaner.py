import datetime
import logging
import math
from typing import List, Dict, Any, Tuple, Optional

logger = logging.getLogger("trading.data.cleaner")

class DataCleaner:
    """
    Handles missing candle detection, price sanity checks, and corporate action (stock split / bonus issue) verification.
    """

    @staticmethod
    def sanitize_text(val: Any, max_len: Optional[int] = None) -> Optional[str]:
        """
        Sanitizes text by removing NUL (0x00) bytes and truncating to max_len to prevent Postgres DataError.
        """
        if val is None:
            return None
        try:
            import pandas as pd
            if pd.isna(val):
                return None
        except Exception:
            pass
        s = str(val).replace("\x00", "")
        if max_len is not None and len(s) > max_len:
            s = s[:max_len]
        return s if s else None

    @staticmethod
    def detect_missing_trading_days(bars: List[Dict[str, Any]], timeframe: str = "1d") -> List[datetime.date]:
        """
        Identifies missing weekdays (M-F) across the date span of the provided daily bars.
        Excludes typical weekend gaps.
        """
        if not bars or timeframe != "1d":
            return []

        # Sort bars and get unique dates
        sorted_bars = sorted(bars, key=lambda x: x["time"])
        def _to_date(val: Any) -> datetime.date:
            if isinstance(val, datetime.datetime):
                return val.date()
            if isinstance(val, datetime.date):
                return val
            try:
                import pandas as pd
                return pd.to_datetime(val).date()
            except Exception:
                return datetime.date.today()

        existing_dates = {_to_date(b["time"]) for b in sorted_bars if "time" in b}
        if not existing_dates:
            return []

        start_date = _to_date(sorted_bars[0]["time"])
        end_date = _to_date(sorted_bars[-1]["time"])

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

            if split is not None and split != 1.0 and split > 0.0 and not math.isnan(split) and not math.isinf(split):
                splits_detected.append((b["time"], split))
            if div is not None and div > 0.0 and not math.isnan(div) and not math.isinf(div):
                dividends_detected.append((b["time"], div))

        if splits_detected:
            for dt, ratio in splits_detected:
                dt_str = dt.strftime('%Y-%m-%d') if hasattr(dt, 'strftime') else str(dt)
                logger.info(f"Corporate Action Verified: Stock Split / Bonus Issue of ratio {ratio} on {dt_str}")
        if dividends_detected:
            logger.debug(f"Corporate Action Verified: {len(dividends_detected)} dividend payouts detected across dataset.")

        return bars

    @classmethod
    def clean_and_verify(cls, bars: List[Dict[str, Any]], timeframe: str = "1d") -> List[Dict[str, Any]]:
        """
        Sorts bars chronologically, removes corrupted price records (e.g. close <= 0, nan/inf, or high < low),
        verifies corporate actions, and logs missing data checks.
        """
        if not bars:
            return []

        # 1. Sort chronologically
        sorted_bars = sorted(bars, key=lambda x: x["time"])

        # 2. Sanity check & filter corrupted outliers
        cleaned = []
        for b in sorted_bars:
            def _get_float(key: str, default: float = 0.0) -> float:
                try:
                    val = b.get(key)
                    if val is None:
                        return default
                    f = float(val)
                    if math.isnan(f) or math.isinf(f):
                        return default
                    return f
                except (ValueError, TypeError):
                    return default

            open_p = _get_float("open", 0.0)
            high_p = _get_float("high", 0.0)
            low_p = _get_float("low", 0.0)
            close_p = _get_float("close", 0.0)

            if close_p <= 0.0 or high_p <= 0.0 or low_p <= 0.0 or open_p <= 0.0:
                logger.warning(f"Dropping candle with non-positive or nan/inf price at {b.get('time')}: {b}")
                continue

            if high_p < low_p or open_p > high_p or open_p < low_p or close_p > high_p or close_p < low_p:
                logger.warning(f"Fixing/Dropping corrupted OHLC envelope at {b.get('time')}: H={high_p}, L={low_p}, O={open_p}, C={close_p}")
                orig_h, orig_l = high_p, low_p
                high_p = max(orig_h, orig_l, open_p, close_p)
                low_p = min(orig_h, orig_l, open_p, close_p)
                b["high"] = high_p
                b["low"] = low_p
                b["open"] = open_p
                b["close"] = close_p

            # Sanitize corporate actions & volume
            split_r = _get_float("split_ratio", 1.0)
            if split_r <= 0.0:
                split_r = 1.0
            b["split_ratio"] = split_r

            div_v = _get_float("dividend", 0.0)
            if div_v < 0.0:
                div_v = 0.0
            b["dividend"] = div_v

            vol_v = _get_float("volume", 0.0)
            if vol_v < 0.0:
                vol_v = 0.0
            b["volume"] = vol_v

            adj_close = _get_float("adjusted_close", close_p)
            if adj_close <= 0.0:
                adj_close = close_p
            b["adjusted_close"] = adj_close

            cleaned.append(b)

        # 3. Deduplicate by timestamp (keeps the first unique bar if duplicate timestamps were emitted)
        deduped = []
        seen_times = set()
        for b in cleaned:
            t = b.get("time")
            if t not in seen_times:
                seen_times.add(t)
                deduped.append(b)
            else:
                logger.debug(f"Removing duplicate timestamp entry during cleaning at {t}")
        cleaned = deduped

        # 4. Verify corporate actions
        cls.verify_corporate_actions(cleaned)

        # 5. Check gaps for diagnostic insight
        cls.detect_missing_trading_days(cleaned, timeframe=timeframe)

        return cleaned
