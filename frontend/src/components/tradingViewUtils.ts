/**
 * Utility functions for TradingView symbol formatting and mapping.
 */

export const formatTradingViewSymbol = (ticker: string): string => {
  const clean = (ticker || '').trim().toUpperCase();
  if (clean === '^NSEI' || clean === 'NIFTY' || clean === 'NIFTY 50') {
    return 'NSE:NIFTY';
  }
  if (clean === '^NSEBANK' || clean === 'BANKNIFTY' || clean === 'NIFTY BANK') {
    return 'NSE:BANKNIFTY';
  }
  if (clean === '^BSESN' || clean === 'SENSEX') {
    return 'BSE:SENSEX';
  }
  if (clean.endsWith('.NS')) {
    return `NSE:${clean.replace('.NS', '')}`;
  }
  if (clean.endsWith('.BO')) {
    return `BSE:${clean.replace('.BO', '')}`;
  }
  if (clean === 'BTC-USD' || clean === 'BTC') {
    return 'BINANCE:BTCUSDT';
  }
  if (clean === 'ETH-USD' || clean === 'ETH') {
    return 'BINANCE:ETHUSDT';
  }
  if (clean === 'SOL-USD' || clean === 'SOL') {
    return 'BINANCE:SOLUSDT';
  }
  if (clean === '^GSPC' || clean === 'SPX') {
    return 'SP:SPX';
  }
  if (clean === '^IXIC' || clean === 'NDX') {
    return 'NASDAQ:NDX';
  }
  if (clean === '^DJI') {
    return 'DJ:DJI';
  }
  return clean;
};
