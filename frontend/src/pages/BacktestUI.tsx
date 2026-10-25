import { useState, useRef, useEffect, useMemo } from 'react';
import axios from 'axios';
import { AlertCircle, RefreshCw, Calendar, TrendingUp, HelpCircle, Layers } from 'lucide-react';
import ErrorBoundary from '../components/ErrorBoundary';
import { formatIndianCurrency } from '../utils/formatters';
import { getExchangeLotSize, formatContractSymbol } from '../utils/foUtils';

interface BacktestTrade {
  entry_time: string;
  exit_time: string;
  direction: string;
  entry_price: number;
  exit_price: number;
  pnl_pct: number;
}

interface BacktestResults {
  win_rate: number;
  total_trades: number;
  total_pnl_pct: number;
  max_drawdown_pct: number;
  trades: BacktestTrade[];
}

const TICKER_REGEX = /^[A-Z0-9.\-^=]+$/;

const BacktestUI = () => {
  const [ticker, setTicker] = useState('^NSEI');
  const [timeframe, setTimeframe] = useState('1d');
  const [setup, setSetup] = useState('macd_cross');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [tickerError, setTickerError] = useState('');

  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<BacktestResults | null>(null);
  const [error, setError] = useState('');
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => {
      if (abortRef.current) {
        abortRef.current.abort();
      }
    };
  }, []);

  const validateTicker = (val: string): boolean => {
    const clean = val.trim().toUpperCase();
    if (!clean) {
      setTickerError('Ticker symbol is required.');
      return false;
    }
    if (clean.length > 64) {
      setTickerError('Ticker cannot exceed 64 characters.');
      return false;
    }
    if (!TICKER_REGEX.test(clean)) {
      setTickerError('Invalid characters. Allowed: letters, numbers, dot, dash, caret (^), equals (=).');
      return false;
    }
    setTickerError('');
    return true;
  };

  const handleTickerChange = (val: string) => {
    const upper = val.toUpperCase();
    setTicker(upper);
    if (tickerError) {
      validateTicker(upper);
    }
  };

  const handleDatePreset = (months: number) => {
    if (months === 0) {
      setStartDate('');
      setEndDate('');
      return;
    }
    const end = new Date();
    const start = new Date();
    start.setMonth(start.getMonth() - months);
    setStartDate(start.toISOString().split('T')[0]);
    setEndDate(end.toISOString().split('T')[0]);
  };

  const runBacktest = async (e?: React.FormEvent, overrideSetup?: string) => {
    if (e) e.preventDefault();
    const cleanTicker = ticker.trim().toUpperCase();
    if (!validateTicker(cleanTicker)) {
      return;
    }

    if (startDate && endDate && new Date(startDate) > new Date(endDate)) {
      setError('Start date cannot be after end date.');
      return;
    }

    if (abortRef.current) {
      abortRef.current.abort();
    }
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError('');
    setResults(null);

    const activeSetup = overrideSetup || setup;

    try {
      const res = await axios.get('/api/v1/backtest/run', {
        params: { ticker: cleanTicker, timeframe, setup: activeSetup },
        signal: controller.signal,
      });
      setResults(res.data);
    } catch (err: any) {
      if (axios.isCancel(err)) return;
      const detail = err.response?.data?.detail;
      const message = typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: any) => d.msg || JSON.stringify(d)).join(' ')
          : err.response?.data?.message || err.message || 'Backtest failed. Ensure the server is online and the symbol is valid.';
      setError(message);
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false);
      }
    }
  };

  // Filter trades by user-selected date range
  const rawTrades = useMemo(() => Array.isArray(results?.trades) ? results.trades : [], [results]);
  const filteredTrades = useMemo(() => {
    if (!startDate && !endDate) return rawTrades;
    return rawTrades.filter(t => {
      if (!t.entry_time) return true;
      const tradeDate = t.entry_time.split(' ')[0] || t.entry_time.split('T')[0];
      if (startDate && tradeDate < startDate) return false;
      if (endDate && tradeDate > endDate) return false;
      return true;
    });
  }, [rawTrades, startDate, endDate]);

  // Dynamically compute stats on filtered trades
  const stats = useMemo(() => {
    if (!results) {
      return { totalTrades: 0, winRate: 0, totalPnlPct: 0, maxDrawdown: 0, wins: 0, losses: 0, profitFactor: 0 };
    }
    // If no date filters, prefer backend returned stats
    if (!startDate && !endDate) {
      const totalTrades = Number(results.total_trades ?? 0);
      const winRate = Number(results.win_rate ?? 0);
      const totalPnlPct = Number(results.total_pnl_pct ?? 0);
      const rawDd = Math.abs(Number(results.max_drawdown_pct ?? 0));
      const maxDrawdown = Number.isFinite(rawDd) ? rawDd : 0;
      const wins = rawTrades.filter(t => Number(t.pnl_pct || 0) > 0).length;
      const losses = rawTrades.filter(t => Number(t.pnl_pct || 0) < 0).length;
      const grossWins = rawTrades.filter(t => Number(t.pnl_pct || 0) > 0).reduce((acc, t) => acc + Number(t.pnl_pct), 0);
      const grossLosses = Math.abs(rawTrades.filter(t => Number(t.pnl_pct || 0) < 0).reduce((acc, t) => acc + Number(t.pnl_pct), 0));
      const profitFactor = grossLosses > 0 ? grossWins / grossLosses : grossWins > 0 ? Infinity : 0;
      return { totalTrades, winRate, totalPnlPct, maxDrawdown, wins, losses, profitFactor };
    }

    // Filtered computation
    const totalTrades = filteredTrades.length;
    if (totalTrades === 0) {
      return { totalTrades: 0, winRate: 0, totalPnlPct: 0, maxDrawdown: 0, wins: 0, losses: 0, profitFactor: 0 };
    }
    const wins = filteredTrades.filter(t => Number(t.pnl_pct || 0) > 0).length;
    const losses = filteredTrades.filter(t => Number(t.pnl_pct || 0) < 0).length;
    const winRate = (wins / totalTrades) * 100;
    const totalPnlPct = filteredTrades.reduce((acc, t) => acc + Number(t.pnl_pct || 0), 0);
    const grossWins = filteredTrades.filter(t => Number(t.pnl_pct || 0) > 0).reduce((acc, t) => acc + Number(t.pnl_pct), 0);
    const grossLosses = Math.abs(filteredTrades.filter(t => Number(t.pnl_pct || 0) < 0).reduce((acc, t) => acc + Number(t.pnl_pct), 0));
    const profitFactor = grossLosses > 0 ? grossWins / grossLosses : grossWins > 0 ? Infinity : 0;

    let peak = 0;
    let cum = 0;
    let maxDd = 0;
    filteredTrades.forEach(t => {
      cum += Number(t.pnl_pct || 0);
      if (cum > peak) peak = cum;
      const dd = peak - cum;
      if (dd > maxDd) maxDd = dd;
    });

    return {
      totalTrades,
      winRate: Number.isFinite(winRate) ? winRate : 0,
      totalPnlPct: Number.isFinite(totalPnlPct) ? totalPnlPct : 0,
      maxDrawdown: Number.isFinite(maxDd) ? maxDd : 0,
      wins,
      losses,
      profitFactor,
    };
  }, [results, filteredTrades, rawTrades, startDate, endDate]);

  return (
    <div className="space-y-6">
      <div className="page-heading">
        <div>
          <span className="eyebrow">Quantitative Validation / 05</span>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <TrendingUp className="w-6 h-6 text-blue-400" />
            Historical Setup Backtester
          </h1>
          <p className="text-sm text-gray-400">
            Simulate rule-based technical setups over historical F&O candles to verify edge and expectancy.
          </p>
        </div>
      </div>

      <ErrorBoundary compact title="Backtest Configuration Error">
        <form onSubmit={runBacktest} className="bg-gray-900 p-6 rounded-lg border border-gray-800 space-y-4">
          <div className="flex flex-wrap gap-4 items-end">
            <div className="flex-1 min-w-[220px]">
              <label htmlFor="bt-ticker" className="block text-sm text-gray-400 mb-1">
                Index / Underlying Contract Symbol
              </label>
              <input
                id="bt-ticker"
                type="text"
                value={ticker}
                onChange={e => handleTickerChange(e.target.value)}
                placeholder="e.g. ^NSEI, ^NSEBANK, RELIANCE.NS"
                maxLength={64}
                className={`w-full bg-gray-800 border ${
                  tickerError ? 'border-red-500 focus:border-red-500' : 'border-gray-700 focus:border-blue-500'
                } rounded px-3 py-2 text-white font-mono focus:outline-none`}
              />
              {tickerError && (
                <p className="text-xs text-red-400 mt-1" role="alert">{tickerError}</p>
              )}
              <div className="flex flex-wrap gap-1.5 mt-2">
                {[
                  { label: 'NIFTY FUT', sym: '^NSEI' },
                  { label: 'BANKNIFTY FUT', sym: '^NSEBANK' },
                  { label: 'SENSEX FUT', sym: '^BSESN' },
                  { label: 'FINNIFTY FUT', sym: 'NIFTY_FIN_SERVICE.NS' },
                  { label: 'RELIANCE FUT', sym: 'RELIANCE.NS' },
                ].map(idx => (
                  <button
                    key={idx.sym}
                    type="button"
                    onClick={() => {
                      setTicker(idx.sym);
                      setTickerError('');
                    }}
                    className={`text-[11px] px-2 py-0.5 rounded font-mono border transition-colors ${
                      ticker === idx.sym
                        ? 'bg-blue-600 border-blue-500 text-white'
                        : 'bg-gray-800 border-gray-700 text-gray-400 hover:text-white'
                    }`}
                  >
                    {idx.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="w-48">
              <label htmlFor="bt-timeframe" className="block text-sm text-gray-400 mb-1">
                Timeframe
              </label>
              <select
                id="bt-timeframe"
                value={timeframe}
                onChange={e => setTimeframe(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500"
              >
                <option value="1h">1 Hour (F&O Swing)</option>
                <option value="1d">1 Day (F&O Swing)</option>
              </select>
              <span className="text-[10px] text-gray-500 mt-1 block">
                1h & 1d supported for multi-year historical bars
              </span>
            </div>

            <div className="w-56">
              <label htmlFor="bt-setup" className="block text-sm text-gray-400 mb-1">
                Setup Engine
              </label>
              <select
                id="bt-setup"
                value={setup}
                onChange={e => setSetup(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500"
              >
                <option value="macd_cross">MACD Crossover</option>
                <option value="sma_crossover">SMA 20/50 Crossover</option>
                <option value="rsi_divergence">RSI Overbought / Oversold</option>
                <option value="bollinger_breakout">Bollinger Bands Breakout</option>
              </select>
            </div>

            <button
              type="submit"
              disabled={loading || !ticker.trim() || !!tickerError}
              className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-700 disabled:cursor-not-allowed px-6 py-2 rounded text-white font-medium transition-colors flex items-center gap-2"
            >
              {loading ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  <span>Running...</span>
                </>
              ) : (
                'Run Backtest'
              )}
            </button>
          </div>

          {/* Date Filter & Presets Bar */}
          <div className="pt-3 border-t border-gray-800/80 flex flex-wrap items-center justify-between gap-3 text-xs">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-gray-400 flex items-center gap-1 font-semibold">
                <Calendar className="w-3.5 h-3.5 text-blue-400" />
                Date Filter:
              </span>
              <input
                type="date"
                aria-label="Start Date"
                value={startDate}
                onChange={e => setStartDate(e.target.value)}
                className="bg-gray-800 border border-gray-700 text-gray-200 px-2.5 py-1 rounded focus:outline-none focus:border-blue-500 text-xs"
              />
              <span className="text-gray-500">to</span>
              <input
                type="date"
                aria-label="End Date"
                value={endDate}
                onChange={e => setEndDate(e.target.value)}
                className="bg-gray-800 border border-gray-700 text-gray-200 px-2.5 py-1 rounded focus:outline-none focus:border-blue-500 text-xs"
              />
              {(startDate || endDate) && (
                <button
                  type="button"
                  onClick={() => { setStartDate(''); setEndDate(''); }}
                  className="text-xs text-gray-400 hover:text-white underline ml-1"
                >
                  Clear
                </button>
              )}
            </div>

            <div className="flex items-center gap-1.5">
              <span className="text-gray-500">Presets:</span>
              {[
                { label: 'All', m: 0 },
                { label: '3M', m: 3 },
                { label: '6M', m: 6 },
                { label: '1Y', m: 12 },
                { label: '3Y', m: 36 },
              ].map(p => (
                <button
                  key={p.label}
                  type="button"
                  onClick={() => handleDatePreset(p.m)}
                  className="px-2 py-0.5 rounded bg-gray-800 hover:bg-gray-700 text-gray-300 text-[11px] font-mono border border-gray-700"
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>
        </form>
      </ErrorBoundary>

      {error && (
        <div className="bg-red-950/60 border border-red-800 text-red-200 p-4 rounded-lg flex items-start justify-between gap-3" role="alert">
          <div className="flex items-start gap-2.5">
            <AlertCircle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
            <div>
              <strong className="block text-sm font-semibold">Backtest Execution Failed</strong>
              <p className="text-xs text-red-300 mt-0.5">{error}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => runBacktest()}
            className="px-3 py-1 bg-red-900/80 hover:bg-red-800 border border-red-700 rounded text-xs font-semibold text-white shrink-0 transition"
          >
            Retry Backtest
          </button>
        </div>
      )}

      {results && (
        <>
          <ErrorBoundary compact title="Performance Metrics Error">
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
              <div className="bg-gray-900 p-4 rounded-lg border border-gray-800">
                <div className="text-gray-400 text-xs uppercase font-semibold">Win Rate</div>
                <div className={`text-2xl font-bold mt-1 ${
                  stats.totalTrades === 0
                    ? 'text-gray-400'
                    : stats.winRate >= 50
                      ? 'text-emerald-400'
                      : 'text-red-400'
                }`}>
                  {stats.totalTrades === 0 ? '0.0%' : `${stats.winRate.toFixed(1)}%`}
                </div>
                <span className="text-[11px] text-gray-500 font-mono">
                  {stats.wins} Won / {stats.losses} Lost
                </span>
              </div>

              <div className="bg-gray-900 p-4 rounded-lg border border-gray-800">
                <div className="text-gray-400 text-xs uppercase font-semibold">Total Trades</div>
                <div className="text-2xl font-bold text-white mt-1">{stats.totalTrades}</div>
                <span className="text-[11px] text-gray-500">
                  {startDate || endDate ? 'In filtered window' : 'Entire dataset'}
                </span>
              </div>

              <div className="bg-gray-900 p-4 rounded-lg border border-gray-800">
                <div className="text-gray-400 text-xs uppercase font-semibold">Total Return P&amp;L</div>
                <div className={`text-2xl font-bold mt-1 ${
                  stats.totalTrades === 0
                    ? 'text-gray-400'
                    : stats.totalPnlPct >= 0
                      ? 'text-emerald-400'
                      : 'text-red-400'
                }`}>
                  {stats.totalPnlPct > 0 ? '+' : ''}{stats.totalPnlPct.toFixed(2)}%
                </div>
                <span className="text-[11px] text-gray-500">
                  Avg: {stats.totalTrades > 0 ? (stats.totalPnlPct / stats.totalTrades).toFixed(2) : '0.00'}%/trade
                </span>
              </div>

              <div className="bg-gray-900 p-4 rounded-lg border border-gray-800">
                <div className="text-gray-400 text-xs uppercase font-semibold">Max Drawdown</div>
                <div className="text-2xl font-bold text-red-400 mt-1">
                  {stats.maxDrawdown === 0 ? '0.00%' : `-${stats.maxDrawdown.toFixed(2)}%`}
                </div>
                <span className="text-[11px] text-gray-500">Peak equity drop</span>
              </div>

              <div className="bg-gray-900 p-4 rounded-lg border border-gray-800 col-span-2 md:col-span-1">
                <div className="text-gray-400 text-xs uppercase font-semibold">F&amp;O Lot Size &amp; Edge</div>
                <div className="text-2xl font-bold text-blue-400 mt-1">
                  {getExchangeLotSize(ticker)} Qty
                </div>
                <span className="text-[11px] text-gray-500">
                  PF: {stats.profitFactor === Infinity ? '∞' : stats.profitFactor.toFixed(2)}
                </span>
              </div>
            </div>
          </ErrorBoundary>

          {filteredTrades.length > 0 ? (
            <ErrorBoundary compact title="Trade Execution Log Error">
              <div className="bg-gray-900 p-4 rounded-lg border border-gray-800">
                <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
                  <div>
                    <h3 className="text-lg font-medium text-white flex items-center gap-2">
                      <Layers className="w-4 h-4 text-blue-400" /> Trade Execution Log
                    </h3>
                    <p className="text-xs text-gray-400">
                      Contract: <span className="font-mono text-white">{formatContractSymbol(ticker, undefined, undefined, 'FUT')}</span> | Lot Size: <span className="font-mono text-white">{getExchangeLotSize(ticker)}</span>
                    </p>
                  </div>
                  <span className="text-xs text-gray-400 font-mono">
                    {filteredTrades.length} trade{filteredTrades.length === 1 ? '' : 's'} recorded
                  </span>
                </div>
                <div className="overflow-x-auto max-h-[460px] overflow-y-auto">
                  <table className="w-full text-sm text-left min-w-[760px]">
                    <caption className="sr-only">Backtest trade results table</caption>
                    <thead className="sticky top-0 bg-gray-900 text-gray-400 border-b border-gray-800">
                      <tr>
                        <th scope="col" className="p-3">Entry Time</th>
                        <th scope="col" className="p-3">Exit Time</th>
                        <th scope="col" className="p-3">Direction</th>
                        <th scope="col" className="p-3 text-right">Entry Price</th>
                        <th scope="col" className="p-3 text-right">Exit Price</th>
                        <th scope="col" className="p-3 text-right">Return %</th>
                        <th scope="col" className="p-3 text-right">Est. 1 Lot P&amp;L</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-800 font-mono text-xs">
                      {filteredTrades.map((trade: BacktestTrade, idx: number) => {
                        const isBullish = String(trade.direction).toLowerCase() === 'bullish';
                        const pnl = Number(trade.pnl_pct || 0);
                        const isProfit = pnl >= 0;
                        const lot = getExchangeLotSize(ticker);
                        const ptDiff = (Number(trade.exit_price || 0) - Number(trade.entry_price || 0)) * (isBullish ? 1 : -1);
                        const rupeePnl = ptDiff * lot;

                        return (
                          <tr key={`${trade.entry_time}-${trade.exit_time}-${idx}`} className="hover:bg-gray-800/40">
                            <td className="p-3 text-gray-400 whitespace-nowrap">{trade.entry_time}</td>
                            <td className="p-3 text-gray-400 whitespace-nowrap">{trade.exit_time}</td>
                            <td className="p-3 font-semibold">
                              <span className={`px-2 py-0.5 rounded text-xs font-bold ${
                                isBullish ? 'bg-emerald-950 text-emerald-300 border border-emerald-800' : 'bg-amber-950 text-amber-300 border border-amber-800'
                              }`}>
                                {isBullish ? 'LONG (BUY)' : 'SHORT (SELL)'}
                              </span>
                            </td>
                            <td className="p-3 text-right">
                              {formatIndianCurrency(trade.entry_price || 0)}
                            </td>
                            <td className="p-3 text-right">
                              {formatIndianCurrency(trade.exit_price || 0)}
                            </td>
                            <td className={`p-3 text-right font-bold ${isProfit ? 'text-emerald-400' : 'text-red-400'}`}>
                              {isProfit ? '+' : ''}{pnl.toFixed(2)}%
                            </td>
                            <td className={`p-3 text-right font-bold ${isProfit ? 'text-emerald-400' : 'text-red-400'}`}>
                              {formatIndianCurrency(rupeePnl, { showSign: true })}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            </ErrorBoundary>
          ) : (
            <div className="bg-gray-900 p-8 rounded-lg border border-gray-800 text-center">
              <HelpCircle className="w-8 h-8 text-gray-500 mx-auto mb-2" />
              <h4 className="text-white font-semibold mb-1">No Trade Signals Triggered</h4>
              <p className="text-gray-400 text-sm max-w-md mx-auto">
                {rawTrades.length > 0 && (startDate || endDate)
                  ? `No trades occurred between ${startDate || 'beginning'} and ${endDate || 'present'}. Clear date filters to view all ${rawTrades.length} trades.`
                  : `No signals met the setup criteria for ${ticker} on the ${timeframe} timeframe. Try switching setups (e.g. SMA Crossover or Bollinger Breakout) or testing a different symbol.`}
              </p>
              <div className="flex gap-2 justify-center mt-4">
                {(startDate || endDate) && (
                  <button
                    type="button"
                    onClick={() => { setStartDate(''); setEndDate(''); }}
                    className="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-xs text-white rounded border border-gray-700 transition"
                  >
                    Clear Date Filters
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => {
                    setSetup('sma_crossover');
                    void runBacktest(undefined, 'sma_crossover');
                  }}
                  className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-xs text-white rounded transition"
                >
                  Test SMA Crossover
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default BacktestUI;
