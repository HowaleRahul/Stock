"""
Curated Liquid Indian Universe with Sector Mappings for Swing Scanners.

Contains active, liquid momentum candidates spanning Nifty 50, Nifty Next 50,
and high-beta sector leaders (Defense, Capital Goods, IT, Auto, Banking, Metals, Power, EMS).
"""

from typing import Dict, List

# Sector mapping for universe candidates
STOCK_SECTORS: Dict[str, str] = {
    # Banking & Financial Services
    "HDFCBANK": "Banking",
    "ICICIBANK": "Banking",
    "SBIN": "Banking",
    "AXISBANK": "Banking",
    "KOTAKBANK": "Banking",
    "BAJFINANCE": "Finance",
    "BAJAJFINSV": "Finance",
    "CHOLAFIN": "Finance",

    # IT & Software
    "TCS": "IT",
    "INFY": "IT",
    "HCLTECH": "IT",
    "WIPRO": "IT",
    "COFORGE": "IT",
    "PERSISTENT": "IT",
    "LTIM": "IT",

    # Defense & Aerospace
    "HAL": "Defense",
    "BEL": "Defense",
    "MAZDOCK": "Defense",
    "BDL": "Defense",

    # Capital Goods & Infrastructure
    "LT": "Infra & Capital Goods",
    "SIEMENS": "Infra & Capital Goods",
    "ABB": "Infra & Capital Goods",
    "BHEL": "Infra & Capital Goods",
    "CUMMINSIND": "Infra & Capital Goods",

    # Auto & Ancillaries
    "TATAMOTORS": "Auto",
    "M&M": "Auto",
    "MARUTI": "Auto",
    "BAJAJ-AUTO": "Auto",
    "HEROMOTOCO": "Auto",
    "TIINDIA": "Auto",

    # Energy, Power & Utilities
    "RELIANCE": "Energy",
    "NTPC": "Power",
    "POWERGRID": "Power",
    "ONGC": "Energy",
    "COALINDIA": "Energy",
    "TATAPOWER": "Power",

    # Metals & Mining
    "TATASTEEL": "Metals",
    "HINDALCO": "Metals",
    "JSWSTEEL": "Metals",
    "JINDALSTEL": "Metals",

    # Consumer, Retail & Electronics
    "TRENT": "Retail",
    "TITAN": "Consumer",
    "ITC": "FMCG",
    "DIXON": "EMS & Electronics",
    "POLYCAB": "Electricals",
    "ZOMATO": "Tech & Internet",

    # Pharma & Healthcare
    "SUNPHARMA": "Pharma",
    "CIPLA": "Pharma",
    "DRREDDY": "Pharma",
    "APOLLOHOSP": "Healthcare",
}

# Default scanning universe: 40 liquid, high-volume candidates
DEFAULT_SWING_UNIVERSE: List[str] = list(STOCK_SECTORS.keys())

# Core benchmark index for relative strength comparison
BENCHMARK_TICKER = "^NSEI"  # Nifty 50
