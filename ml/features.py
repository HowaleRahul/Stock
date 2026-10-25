import math
import pandas as pd
import numpy as np
import scipy.stats as si
import yfinance as yf
import logging
from ml.assets import ASSET_CLASSES

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
    if not all(isinstance(v, (int, float)) for v in (S, K, T, r, sigma)):
        return 0.5, 0.0
    if any(math.isnan(v) or math.isinf(v) for v in (S, K, T, r, sigma)):
        return 0.5, 0.0
    if sigma <= 0 or T <= 0 or S <= 0 or K <= 0:
        return 0.5, 0.0
        
    denom = sigma * np.sqrt(T)
    if denom <= 1e-9 or (S * denom) <= 1e-12:
        return 0.5, 0.0

    try:
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / denom
        if d1 > 37.0:
            return 1.0, 0.0
        elif d1 < -37.0:
            return 0.0, 0.0

        delta = si.norm.cdf(d1, 0.0, 1.0)
        gamma = si.norm.pdf(d1, 0.0, 1.0) / (S * denom)

        safe_delta = float(np.clip(delta, 0.0, 1.0))
        safe_gamma = float(max(0.0, gamma))
        if math.isnan(safe_gamma) or math.isinf(safe_gamma):
            safe_gamma = 0.0
        return safe_delta, safe_gamma
    except Exception:
        return 0.5, 0.0

def _close_or_volume(data: pd.DataFrame, symbol: str, field: str) -> pd.Series | None:
    """Extract a Yahoo series from single- or multi-ticker response shapes."""
    if data.empty or field not in data:
        return None
    values = data[field]
    if isinstance(values, pd.DataFrame):
        if symbol not in values:
            return None
        values = values[symbol]
    return pd.to_numeric(values, errors="coerce")


def _align_daily_series(series: pd.Series, target_index: pd.Index) -> pd.Series:
    """Align delayed daily macro data to candles, including crypto weekends.

    Macro markets are closed on weekends.  Mapping by normalized date and
    forward-filling means a Saturday/Sunday BTC candle receives the latest
    *previously published* Friday macro observation without lookahead.
    """
    source = series.copy()
    source.index = pd.to_datetime(source.index, utc=True).tz_convert(None).normalize()
    source = source[~source.index.duplicated(keep="last")].sort_index()
    dates = pd.to_datetime(target_index, utc=True).tz_convert(None).normalize()
    return source.reindex(dates, method="ffill").set_axis(target_index)


def enrich_with_macro_and_options(df: pd.DataFrame, ticker: str, period: str = "2y", interval: str = "1d", asset_class: str = "IN_INDEX_FO") -> pd.DataFrame:
    """
    Downloads macro indicators and mathematically generates synthetic options Greeks.
    Merges them directly into the primary dataframe.
    """
    logger.info(f"Downloading Macro Features for {ticker} ({asset_class})...")
    
    if asset_class not in ASSET_CLASSES and asset_class != "IN_INDEX_FO":
        raise ValueError(f"Unsupported asset class: {asset_class}")
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("Feature input must use a DatetimeIndex.")

    if asset_class in ("IN_INDEX_FO", "IN_EQUITY"):
        macro_tickers = {"VIX": "^INDIAVIX", "SPX": "^GSPC", "USDINR": "INR=X"}
    elif asset_class == "US_EQUITY":
        macro_tickers = {"VIX": "^VIX", "SPX": "^GSPC", "USDINR": "DX-Y.NYB"} # Using DXY as fiat currency proxy
    elif asset_class == "CRYPTO":
        macro_tickers = {"VIX": "^VIX", "SPX": "^GSPC", "USDINR": "DX-Y.NYB", "BTC_VOLUME": "BTC-USD"}
    
    macro_dfs = {}
    for name, sym in macro_tickers.items():
        try:
            # Always fetch daily data for macro to avoid intraday timezone mismatch
            data = yf.download(sym, period=period, interval="1d", progress=False)
            if not data.empty:
                field = "Volume" if name == "BTC_VOLUME" else "Close"
                close_series = _close_or_volume(data, sym, field)
                if close_series is None:
                    continue
                
                # Shift by 1 day to strictly prevent lookahead bias
                close_series = close_series.shift(1)
                # Remove timezone to allow alignment
                macro_dfs[name] = close_series
        except Exception as e:
            logger.warning(f"Failed to fetch {sym}: {e}")

    # Fallback to Frankfurter Open API (public-apis) for USD/INR if Yahoo Finance was unavailable
    if "USDINR" not in macro_dfs and asset_class in ("IN_INDEX_FO", "IN_EQUITY"):
        try:
            from data.fx_fetcher import FrankfurterFXFetcher
            earliest_dt = df.index.min().strftime("%Y-%m-%d")
            fx_series = FrankfurterFXFetcher.get_historical_usdinr_series_sync(start_date=earliest_dt)
            if fx_series is not None and not fx_series.empty:
                macro_dfs["USDINR"] = fx_series.shift(1)
                logger.info("Successfully populated USD/INR macro feature via Frankfurter API fallback.")
        except Exception as e:
            logger.debug(f"Frankfurter fallback unavailable: {e}")
            
    # Combine into main df
    df = df.copy()
    
    # Create a temporary dataframe while retaining the caller's timezone and
    # timestamps.  `_align_daily_series` handles the normalized-day join.
    macro_combined = pd.DataFrame(index=df.index)
    
    for name, series in macro_dfs.items():
        aligned_series = _align_daily_series(series, df.index)
        macro_combined[name] = aligned_series

    if "VIX" in macro_dfs:
        df['macro_vix'] = macro_combined["VIX"]
    else:
        df['macro_vix'] = 15.0 # Fallback average VIX
        
    if "SPX" in macro_dfs:
        df['macro_spx_close'] = macro_combined["SPX"]
        df['macro_spx_ret'] = df['macro_spx_close'].pct_change().replace([np.inf, -np.inf], 0.0).fillna(0.0)
    else:
        df['macro_spx_ret'] = 0.0
        
    if "USDINR" in macro_dfs:
        df['macro_usdinr'] = macro_combined["USDINR"]
        df['macro_usdinr_ret'] = df['macro_usdinr'].pct_change().replace([np.inf, -np.inf], 0.0).fillna(0.0)
    else:
        df['macro_usdinr_ret'] = 0.0

    if "BTC_VOLUME" in macro_dfs:
        df["macro_btc_volume"] = macro_combined["BTC_VOLUME"]
        df["macro_btc_volume_ret"] = df["macro_btc_volume"].pct_change().replace([np.inf, -np.inf], 0.0).fillna(0.0)
    else:
        df["macro_btc_volume"] = 0.0
        df["macro_btc_volume_ret"] = 0.0
        
    # Clean inf and NaN values to prevent sklearn pipeline failures
    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    df.ffill(inplace=True)
    df.bfill(inplace=True)
    df.fillna(0.0, inplace=True)
    
    logger.info(f"Generating Synthetic Black-Scholes Greeks for {ticker}...")
    
    # Generate Synthetic Greeks
    deltas = []
    gammas = []
    
    for i in range(len(df)):
        try:
            S = float(df['close'].iloc[i])
            if math.isnan(S) or S <= 0.0:
                S = 100.0
        except Exception:
            S = 100.0
        K = S # Assume ATM Strike
        T = 7 / 365.0 # Assume 7 days to expiry for weekly options
        r = 0.05 # 5% Repo rate
        try:
            vix_val = float(df['macro_vix'].iloc[i])
            if math.isnan(vix_val) or vix_val <= 0.0:
                vix_val = 15.0
        except Exception:
            vix_val = 15.0
        sigma = vix_val / 100.0 # VIX is in percentage points (e.g. 15.0 = 15%)
        
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
    # Guard against volume division by zero or doji candle body singularity
    vol_series = pd.to_numeric(df['volume'], errors='coerce').fillna(0.0)
    vol_sma_20 = vol_series.rolling(20, min_periods=1).mean().replace(0, np.nan).ffill().bfill().fillna(1.0)
    vol_sma_20 = np.maximum(vol_sma_20, 1.0)
    rel_vol = np.clip((vol_series / vol_sma_20).replace([np.inf, -np.inf], 1.0).fillna(1.0), 0.0, 50.0)
    
    lower_wick = np.maximum(0.0, np.minimum(df['open'], df['close']) - df['low'])
    candle_body = np.abs(df['open'] - df['close'])
    candle_range = np.maximum(df['high'] - df['low'], 1e-4)
    # Use normalizer that avoids doji singularity (candle_body near 0)
    normalizer = np.maximum(candle_body, candle_range * 0.1)
    panic_idx = (lower_wick / normalizer) * rel_vol
    df['psych_panic_index'] = np.clip(panic_idx.replace([np.inf, -np.inf], 0.0).fillna(0.0), 0.0, 50.0)
    
    # 3. Distance to Round Number Proximity (Retail places stops at '00' levels)
    # e.g., 25000, 1000, 500. We'll find distance to nearest 100 level.
    safe_close = df['close'].abs().replace(0, np.nan).fillna(1.0)
    safe_close = np.maximum(safe_close, 1.0)
    nearest_100 = (df['close'] / 100).round() * 100
    dist_round = np.abs(df['close'] - nearest_100) / safe_close
    df['psych_dist_to_round'] = np.clip(dist_round.replace([np.inf, -np.inf], 0.0).fillna(0.0), 0.0, 1.0)
    
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

    # Sanitize dataframe
    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    df.fillna(0.0, inplace=True)
        
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
    high_low = np.maximum(0.0, df['high'] - df['low'])
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1).fillna(0.0)
    atr = true_range.rolling(14, min_periods=1).mean().bfill().fillna(1.0)
    df['atr'] = atr # Save ATR as a potential feature
    
    for i in range(len(df)):
        if i >= len(df) - 1:
            labels.append(0)
            continue
            
        try:
            entry_price = float(df['close'].iloc[i])
            if math.isnan(entry_price) or entry_price <= 0.0:
                entry_price = 100.0
        except Exception:
            entry_price = 100.0

        try:
            current_atr = float(atr.iloc[i])
        except Exception:
            current_atr = 1.0
        
        # Prevent zero or negative ATR from causing identical TP/SL
        if current_atr <= 0 or math.isnan(current_atr) or math.isinf(current_atr):
            current_atr = max(1.0, abs(entry_price) * 0.01)
            
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
            try:
                high = float(df['high'].iloc[j])
                low = float(df['low'].iloc[j])
            except Exception:
                continue
            
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
