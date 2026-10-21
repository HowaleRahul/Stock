"""
Market Hours and Session Management for Indian Stock Exchanges (NSE / BSE).

Provides real-time checks for:
- Regular trading hours: 09:15 to 15:30 IST (Monday - Friday)
- Pre-market session: 09:00 to 09:15 IST
- Post-market session: 15:40 to 16:00 IST
- Weekends and holiday schedules
- Calculation of countdown to next market open / close
"""

import datetime
from typing import Dict, Any, Optional

# IST Timezone: UTC+05:30
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30), name="IST")

# NSE Standard Trading Hours (IST)
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 15

MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 30

PRE_MARKET_OPEN_HOUR = 9
PRE_MARKET_OPEN_MINUTE = 0

# Comprehensive NSE Public & Exchange Holidays (month, day)
NSE_FIXED_HOLIDAYS = {
    (1, 26),   # Republic Day
    (3, 8),    # Maha Shivratri (typical early March)
    (3, 25),   # Holi (typical late March)
    (3, 29),   # Good Friday
    (4, 11),   # Id-Ul-Fitr
    (4, 17),   # Shri Ram Navami
    (5, 1),    # Maharashtra Day / Labour Day
    (6, 17),   # Bakri Id
    (7, 17),   # Muharram
    (8, 15),   # Independence Day
    (10, 2),   # Mahatma Gandhi Jayanti
    (11, 1),   # Diwali Laxmi Pujan
    (11, 15),  # Guru Nanak Jayanti
    (12, 25),  # Christmas
}


def get_current_ist_time() -> datetime.datetime:
    """Returns current datetime in Indian Standard Time (IST)."""
    return datetime.datetime.now(IST)


def is_weekend(dt: Optional[datetime.datetime] = None) -> bool:
    """Returns True if the given or current date is a Saturday or Sunday."""
    if dt is None:
        dt = get_current_ist_time()
    return dt.weekday() in (5, 6)  # 5=Saturday, 6=Sunday


def is_nse_holiday(dt: Optional[datetime.datetime] = None) -> bool:
    """Returns True if the date matches known Indian public/exchange holidays."""
    if dt is None:
        dt = get_current_ist_time()
    return (dt.month, dt.day) in NSE_FIXED_HOLIDAYS


def get_session_phase(dt: Optional[datetime.datetime] = None) -> float:
    """
    Returns normalized intraday session progression:
    0.0 at 09:15 AM IST open to 1.0 at 15:30 PM IST close.
    Outside regular hours, returns 0.0 before open and 1.0 after close.
    """
    if dt is None:
        dt = get_current_ist_time()
    cur_time = dt.time()
    open_time = datetime.time(MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE)
    close_time = datetime.time(MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE)
    if cur_time < open_time:
        return 0.0
    if cur_time >= close_time:
        return 1.0
    elapsed = (cur_time.hour - MARKET_OPEN_HOUR) * 60 + (cur_time.minute - MARKET_OPEN_MINUTE)
    total_minutes = (MARKET_CLOSE_HOUR - MARKET_OPEN_HOUR) * 60 + (MARKET_CLOSE_MINUTE - MARKET_OPEN_MINUTE)
    return round(min(1.0, max(0.0, elapsed / max(1, total_minutes))), 3)


def get_market_phase(dt: Optional[datetime.datetime] = None) -> str:
    """
    Returns specific granular trading phase:
    - 'PRE_OPEN_COLLECTION' (09:00 - 09:08)
    - 'PRE_OPEN_MATCHING' (09:08 - 09:15)
    - 'MORNING_MOMENTUM' (09:15 - 11:30)
    - 'MIDDAY_CONSOLIDATION' (11:30 - 13:30)
    - 'AFTERNOON_EXPIRY' (13:30 - 15:30)
    - 'POST_MARKET' (15:40 - 16:00)
    - 'CLOSED'
    """
    if dt is None:
        dt = get_current_ist_time()

    if is_weekend(dt) or is_nse_holiday(dt):
        return "CLOSED"

    t = dt.time()
    if datetime.time(9, 0) <= t < datetime.time(9, 8):
        return "PRE_OPEN_COLLECTION"
    elif datetime.time(9, 8) <= t < datetime.time(9, 15):
        return "PRE_OPEN_MATCHING"
    elif datetime.time(9, 15) <= t < datetime.time(11, 30):
        return "MORNING_MOMENTUM"
    elif datetime.time(11, 30) <= t < datetime.time(13, 30):
        return "MIDDAY_CONSOLIDATION"
    elif datetime.time(13, 30) <= t < datetime.time(15, 30):
        return "AFTERNOON_EXPIRY"
    elif datetime.time(15, 40) <= t < datetime.time(16, 0):
        return "POST_MARKET"
    else:
        return "CLOSED"



def get_market_session(dt: Optional[datetime.datetime] = None) -> str:
    """
    Returns the market session string:
    - 'REGULAR': 09:15 to 15:30 IST on trading days
    - 'PRE_OPEN': 09:00 to 09:15 IST on trading days
    - 'POST_MARKET': 15:30 to 16:00 IST on trading days
    - 'CLOSED': outside hours or weekend/holiday
    """
    if dt is None:
        dt = get_current_ist_time()

    if is_weekend(dt) or is_nse_holiday(dt):
        return "CLOSED"

    cur_time = dt.time()
    pre_open = datetime.time(PRE_MARKET_OPEN_HOUR, PRE_MARKET_OPEN_MINUTE)
    market_open = datetime.time(MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE)
    market_close = datetime.time(MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE)
    post_close = datetime.time(16, 0)

    if market_open <= cur_time < market_close:
        return "REGULAR"
    elif pre_open <= cur_time < market_open:
        return "PRE_OPEN"
    elif market_close <= cur_time < post_close:
        return "POST_MARKET"
    else:
        return "CLOSED"


def is_market_open(exchange: str = "NSE", dt: Optional[datetime.datetime] = None) -> bool:
    """
    Returns True if the Indian market (NSE/BSE) is actively trading in regular hours.
    For crypto or 24/7 assets, returns True.
    """
    exchange = exchange.upper().strip()
    if exchange in ("CRYPTO", "BINANCE", "FOREX_24_7"):
        return True

    return get_market_session(dt) == "REGULAR"


def get_market_status(exchange: str = "NSE", dt: Optional[datetime.datetime] = None) -> Dict[str, Any]:
    """
    Returns comprehensive market status, countdown timers, and human-readable message.
    """
    if dt is None:
        dt = get_current_ist_time()

    session = get_market_session(dt)
    market_open_today = dt.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0)
    market_close_today = dt.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE, second=0, microsecond=0)

    now_ts = dt.timestamp()
    open_ts = market_open_today.timestamp()
    close_ts = market_close_today.timestamp()

    is_open = session == "REGULAR"

    # Seconds until next open / close
    seconds_until_close = max(0, int(close_ts - now_ts)) if is_open else 0

    if now_ts < open_ts and not is_weekend(dt) and not is_nse_holiday(dt):
        seconds_until_open = max(0, int(open_ts - now_ts))
    else:
        # Calculate next trading day 09:15 IST
        next_day = dt + datetime.timedelta(days=1)
        while is_weekend(next_day) or is_nse_holiday(next_day):
            next_day += datetime.timedelta(days=1)
        next_open = next_day.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0)
        seconds_until_open = max(0, int(next_open.timestamp() - now_ts))

    time_str = dt.strftime("%Y-%m-%d %H:%M:%S IST")

    if is_open:
        msg = f"[OPEN] NSE Market is OPEN (Closes at 15:30 IST, {seconds_until_close // 60} min remaining)"
    elif session == "PRE_OPEN":
        msg = f"[PRE-OPEN] NSE Pre-Open Session Active (Regular trading starts at 09:15 IST, in {seconds_until_open // 60} min)"
    elif is_weekend(dt):
        day_name = dt.strftime("%A")
        msg = f"[CLOSED] NSE Market is CLOSED ({day_name} Weekend). Next open: Monday 09:15 IST"
    elif is_nse_holiday(dt):
        msg = "[CLOSED] NSE Market is CLOSED (Exchange Holiday). Reopens next trading session at 09:15 IST"
    else:
        msg = f"[CLOSED] NSE Market is CLOSED. Reopens at 09:15 IST (in {seconds_until_open // 3600}h {(seconds_until_open % 3600) // 60}m)"

    return {
        "exchange": exchange,
        "is_open": is_open,
        "session": session,
        "market_phase": get_market_phase(dt),
        "session_phase": get_session_phase(dt),
        "current_time_ist": time_str,
        "market_open_ist": "09:15:00",
        "market_close_ist": "15:30:00",
        "seconds_until_open": seconds_until_open,
        "seconds_until_close": seconds_until_close,
        "message": msg
    }

