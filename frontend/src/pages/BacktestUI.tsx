import { useState, useRef, useEffect } from 'react';
import axios from 'axios';

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

const BacktestUI = () => {
  const [ticker, setTicker] = useState('^NSEI');
  const [timeframe, setTimeframe] = useState('1d');
  const [setup, setSetup] = useState('macd_cross');
  
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

  const runBacktest = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const cleanTicker = ticker.trim().toUpperCase();
    if (!cleanTicker) {
      setError('Please enter a valid ticker symbol.');
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

    try {
      // Run backtest — the backend provides both stats and trade data
      const res = await axios.get('/api/v1/backtest/run', {
        params: { ticker: cleanTicker, timeframe, setup },
        signal: controller.signal,
      });
      setResults(res.data);
    } catch (err: any) {
      if (axios.isCancel(err)) return;
      setError(err.response?.data?.detail || err.response?.data?.message || err.message || 'Backtest failed.');
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false);
      }
    }
  };

  const trades = Array.isArray(results?.trades) ? results.trades : [];
  const winRate = Number(results?.win_rate ?? 0);
  const totalTrades = Number(results?.total_trades ?? 0);
  const totalPnlPct = Number(results?.total_pnl_pct ?? 0);
  const maxDrawdown = Math.abs(Number(results?.max_drawdown_pct ?? 0));

  return (
    <div className="space-y-6">
      <form onSubmit={runBacktest} className="bg-gray-900 p-6 rounded-lg border border-gray-800 flex flex-wrap gap-4 items-end">
        <div>
          <label htmlFor="bt-ticker" className="block text-sm text-gray-400 mb-1">Ticker</label>
          <input
            id="bt-ticker"
            type="text"
            value={ticker}
            onChange={e => setTicker(e.target.value.toUpperCase())}
            placeholder="e.g. ^NSEI or RELIANCE.NS"
            className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white"
          />
        </div>
        <div>
          <label htmlFor="bt-timeframe" className="block text-sm text-gray-400 mb-1">Timeframe</label>
          <select
            id="bt-timeframe"
            value={timeframe}
            onChange={e => setTimeframe(e.target.value)}
            className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white"
          >
            <option value="1h">1 Hour</option>
            <option value="1d">1 Day</option>
          </select>
        </div>
        <div>
          <label htmlFor="bt-setup" className="block text-sm text-gray-400 mb-1">Setup</label>
          <select
            id="bt-setup"
            value={setup}
            onChange={e => setSetup(e.target.value)}
            className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white"
          >
            <option value="sma_crossover">SMA Crossover</option>
            <option value="macd_cross">MACD Cross</option>
            <option value="rsi_divergence">RSI Divergence</option>
            <option value="bollinger_breakout">Bollinger Breakout</option>
          </select>
        </div>
        <button
          type="submit"
          disabled={loading || !ticker.trim()}
          className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-700 disabled:cursor-not-allowed px-6 py-2 rounded text-white font-medium transition-colors"
        >
          {loading ? 'Running...' : 'Run Backtest'}
        </button>
      </form>

      {error && (
        <div className="bg-red-900/50 border border-red-500 text-red-200 p-4 rounded" role="alert">
          {error}
        </div>
      )}

      {results && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="bg-gray-900 p-4 rounded-lg border border-gray-800">
              <div className="text-gray-400 text-sm">Win Rate</div>
              <div className={`text-2xl font-bold ${winRate >= 50 ? 'text-emerald-400' : 'text-red-400'}`}>
                {winRate.toFixed(1)}%
              </div>
            </div>
            <div className="bg-gray-900 p-4 rounded-lg border border-gray-800">
              <div className="text-gray-400 text-sm">Total Trades</div>
              <div className="text-2xl font-bold text-white">{totalTrades}</div>
            </div>
            <div className="bg-gray-900 p-4 rounded-lg border border-gray-800">
              <div className="text-gray-400 text-sm">Total P&L</div>
              <div className={`text-2xl font-bold ${totalPnlPct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {totalPnlPct >= 0 ? '+' : ''}{totalPnlPct.toFixed(2)}%
              </div>
            </div>
            <div className="bg-gray-900 p-4 rounded-lg border border-gray-800">
              <div className="text-gray-400 text-sm">Max Drawdown</div>
              <div className="text-2xl font-bold text-red-400">
                -{maxDrawdown.toFixed(2)}%
              </div>
            </div>
          </div>

          {trades.length > 0 ? (
            <div className="bg-gray-900 p-4 rounded-lg border border-gray-800">
              <h3 className="text-lg font-medium mb-4">Trade Results</h3>
              <div className="overflow-x-auto max-h-[460px] overflow-y-auto">
                <table className="w-full text-sm text-left">
                  <caption className="sr-only">Backtest trade results</caption>
                  <thead className="sticky top-0 bg-gray-900 text-gray-400">
                    <tr>
                      <th scope="col" className="p-3">Entry</th>
                      <th scope="col" className="p-3">Exit</th>
                      <th scope="col" className="p-3">Direction</th>
                      <th scope="col" className="p-3 text-right">Entry Price</th>
                      <th scope="col" className="p-3 text-right">Exit Price</th>
                      <th scope="col" className="p-3 text-right">P&L</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-800">
                    {trades.map((trade: BacktestTrade, idx: number) => {
                      const isBullish = String(trade.direction).toLowerCase() === 'bullish';
                      const pnl = Number(trade.pnl_pct || 0);
                      const cleanSym = (ticker || '').toUpperCase().trim();
                      const isIndian = cleanSym.endsWith('.NS') || cleanSym.endsWith('.BO') || cleanSym.includes('NSE') || cleanSym.includes('NIFTY') || cleanSym.includes('BANKNIFTY') || cleanSym.includes('SENSEX') || cleanSym === '^BSESN' || cleanSym === '^NSEI';
                      const currSym = isIndian ? '₹' : '$';
                      const loc = isIndian ? 'en-IN' : 'en-US';
                      return (
                        <tr key={`${trade.entry_time}-${trade.exit_time}-${idx}`}>
                          <td className="p-3 text-gray-400 whitespace-nowrap">{trade.entry_time}</td>
                          <td className="p-3 text-gray-400 whitespace-nowrap">{trade.exit_time}</td>
                          <td className={`p-3 font-semibold ${isBullish ? 'text-emerald-400' : 'text-red-400'}`}>
                            {trade.direction}
                          </td>
                          <td className="p-3 text-right">{currSym}{Number(trade.entry_price || 0).toLocaleString(loc, { maximumFractionDigits: 2 })}</td>
                          <td className="p-3 text-right">{currSym}{Number(trade.exit_price || 0).toLocaleString(loc, { maximumFractionDigits: 2 })}</td>
                          <td className={`p-3 text-right font-semibold ${pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}%
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <div className="bg-gray-900 p-8 rounded-lg border border-gray-800 text-center text-gray-400">
              No trade signals were triggered by this setup for the selected timeframe and ticker.
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default BacktestUI;
