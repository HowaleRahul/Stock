import pandas as pd
import numpy as np
import scipy.stats as si
import yfinance as yf
import logging

logger = logging.getLogger("trading.ml.features")

def calculate_black_scholes_greeks(S, K, T, r, sigma):
    """
    S: Underlying Price
    K: Strike Price
    T: Time to Expiration (in years, e.g. 7/365 for weekly)
    r: Risk-free rate (e.g. 0.05 for 5%)
    sigma: Volatility (from VIX, e.g. 15/100 = 0.15)
    
    Returns ATM Call Delta and Gamma
    """
    # Prevent division by zero
    if sigma <= 0 or T <= 0 or S <= 0 or K <= 0:
        return 0.5, 0.0
        
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    # d2 = d1 - sigma * np.sqrt(T)
    
    delta = si.norm.cdf(d1, 0.0, 1.0)
    gamma = si.norm.pdf(d1, 0.0, 1.0) / (S * sigma * np.sqrt(T))
    
    return delta, gamma

def enrich_with_macro_and_options(df: pd.DataFrame, ticker: str, period: str = "2y", interval: str = "1d") -> pd.DataFrame:
    """
    Downloads macro indicators and mathematically generates synthetic options Greeks.
    Merges them directly into the primary dataframe.
    """
    logger.info(f"Downloading Macro Features (VIX, S&P500, USDINR) for {ticker}...")
    
    # We download synchronously here since this is run in the feature pipeline
    macro_tickers = {
        "VIX": "^INDIAVIX",
        "SPX": "^GSPC",
        "USDINR": "INR=X"
    }
    
    macro_dfs = {}
    for name, sym in macro_tickers.items():
        try:
            data = yf.download(sym, period=period, interval=interval, progress=False)
            if not data.empty:
                # Yahoo Finance sometimes returns MultiIndex columns if multiple tickers are passed, 
                # but for a single ticker it's usually flat. We ensure we get the 'Close' column.
                if isinstance(data.columns, pd.MultiIndex):
                    close_series = data['Close'][sym]
                else:
                    close_series = data['Close']
                    
                macro_dfs[name] = close_series
        except Exception as e:
            logger.warning(f"Failed to fetch {sym}: {e}")
            
    # Combine into main df
    df = df.copy()
    
    if "VIX" in macro_dfs:
        df['macro_vix'] = macro_dfs["VIX"]
    else:
        df['macro_vix'] = 15.0 # Fallback average VIX
        
    if "SPX" in macro_dfs:
        df['macro_spx_close'] = macro_dfs["SPX"]
        df['macro_spx_ret'] = df['macro_spx_close'].pct_change()
    else:
        df['macro_spx_ret'] = 0.0
        
    if "USDINR" in macro_dfs:
        df['macro_usdinr'] = macro_dfs["USDINR"]
        df['macro_usdinr_ret'] = df['macro_usdinr'].pct_change()
    else:
        df['macro_usdinr_ret'] = 0.0
        
    # Forward fill NaNs (due to differing market holidays between US and India)
    df.ffill(inplace=True)
    df.fillna(0.0, inplace=True)
    
    logger.info(f"Generating Synthetic Black-Scholes Greeks for {ticker}...")
    
    # Generate Synthetic Greeks
    deltas = []
    gammas = []
    
    for i in range(len(df)):
        S = float(df['close'].iloc[i])
        K = S # Assume ATM Strike
        T = 7 / 365.0 # Assume 7 days to expiry for weekly options
        r = 0.05 # 5% Repo rate
        sigma = float(df['macro_vix'].iloc[i]) / 100.0 # VIX is in percentage points (e.g. 15.0 = 15%)
        
        delta, gamma = calculate_black_scholes_greeks(S, K, T, r, sigma)
        deltas.append(delta)
        gammas.append(gamma)
        
    df['opt_delta'] = deltas
    df['opt_gamma'] = gammas
    
    return df

def enrich_with_psychology_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Injects human psychology and behavioral finance metrics into the ML dataset.
    """
    logger.info("Generating Psychological and Behavioral features...")
    
    # 1. FOMO Streak (Consecutive Candles of the same color)
    # Retail traders buy after 3-4 green candles, Smart Money fades it.
    is_green = (df['close'] > df['open']).astype(int)
    is_red = (df['close'] < df['open']).astype(int)
    
    # Calculate streak (positive for green, negative for red)
    streak = np.zeros(len(df))
    current_streak = 0
    for i in range(len(df)):
        if is_green.iloc[i]:
            current_streak = current_streak + 1 if current_streak >= 0 else 1
        elif is_red.iloc[i]:
            current_streak = current_streak - 1 if current_streak <= 0 else -1
        else:
            current_streak = 0
        streak[i] = current_streak
    df['psych_fomo_streak'] = streak
    
    # 2. Panic Capitulation Index (Large lower wicks with high relative volume)
    # Smart Money buys when retail panics.
    vol_sma_20 = df['volume'].rolling(20).mean().fillna(1)
    rel_vol = df['volume'] / vol_sma_20
    
    lower_wick = np.minimum(df['open'], df['close']) - df['low']
    candle_body = np.abs(df['open'] - df['close']) + 1e-5 # prevent div zero
    
    # High lower wick + high volume = Retail Panic / Smart Money Accumulation
    df['psych_panic_index'] = (lower_wick / candle_body) * rel_vol
    
    # 3. Distance to Round Number Proximity (Retail places stops at '00' levels)
    # e.g., 25000, 1000, 500. We'll find distance to nearest 100 level.
    nearest_100 = (df['close'] / 100).round() * 100
    df['psych_dist_to_round'] = np.abs(df['close'] - nearest_100) / df['close']
    
    # 4. Session Phase (Morning=1, Mid-day=2, Closing=3, Daily/Unknown=0)
    # Morning is emotional/retail. Mid-day is choppy. Close is institutional rebalancing.
    df['psych_session_phase'] = 0
    if isinstance(df.index, pd.DatetimeIndex) and len(np.unique(df.index.time)) > 1:
        hours = df.index.hour
        mins = df.index.minute
        time_float = hours + mins / 60.0
        
        # 09:15 to 10:30 -> Morning (1)
        # 10:30 to 13:30 -> Mid-day (2)
        # 13:30 to 15:30 -> Close (3)
        conditions = [
            (time_float < 10.5),
            (time_float >= 10.5) & (time_float < 13.5),
            (time_float >= 13.5)
        ]
        choices = [1, 2, 3]
        df['psych_session_phase'] = np.select(conditions, choices, default=0)
        
    return df

def generate_triple_barrier_labels(df: pd.DataFrame, tp_atr_mult: float = 2.0, sl_atr_mult: float = 1.0, max_hold_bars: int = 20) -> list:
    """
    Simulates a trade entry on every single bar and scans forward to see if the
    Take Profit (TP), Stop Loss (SL), or Time Barrier is hit first.
    
    Uses Average True Range (ATR) to dynamically scale targets based on volatility.
    
    Returns a list of labels aligned with the dataframe:
     1  = Long TP hit first (Bullish Win)
    -1  = Short TP hit first (Bearish Win)
     0  = Neither hit TP before SL (Whipsaw) or Time Barrier hit.
    """
    labels = []
    
    # Compute ATR (14-period)
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    atr = true_range.rolling(14).mean().fillna(true_range.mean())
    df['atr'] = atr # Save ATR as a potential feature
    
    for i in range(len(df)):
        if i >= len(df) - 1:
            labels.append(0)
            continue
            
        entry_price = float(df['close'].iloc[i])
        current_atr = float(atr.iloc[i])
        
        # Prevent zero ATR from causing identical TP/SL
        if current_atr == 0:
            current_atr = entry_price * 0.01 
            
        # LONG Barriers
        long_tp = entry_price + (tp_atr_mult * current_atr)
        long_sl = entry_price - (sl_atr_mult * current_atr)
        
        # SHORT Barriers
        short_tp = entry_price - (tp_atr_mult * current_atr)
        short_sl = entry_price + (sl_atr_mult * current_atr)
        
        # Scan forward
        hit_label = 0
        long_active = True
        short_active = True
        
        max_scan = min(i + max_hold_bars + 1, len(df))
        
        for j in range(i + 1, max_scan):
            high = float(df['high'].iloc[j])
            low = float(df['low'].iloc[j])
            
            # Check Stop Losses First (always prioritize risk)
            if low <= long_sl:
                long_active = False
            if high >= short_sl:
                short_active = False
                
            # If both SL hit in the same bar, it's a massive whip, trade fails
            if not long_active and not short_active:
                break
                
            # Check Take Profits
            if long_active and high >= long_tp:
                hit_label = 1
                break
                
            if short_active and low <= short_tp:
                hit_label = -1
                break
                
        labels.append(hit_label)
        
    return labels
