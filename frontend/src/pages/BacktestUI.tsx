import { useState } from 'react';
import axios from 'axios';

const BacktestUI = () => {
  const [ticker, setTicker] = useState('^NSEI');
  const [timeframe, setTimeframe] = useState('1d');
  const [setup, setSetup] = useState('macd_cross');
  
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<any>(null);
  const [error, setError] = useState('');

  const runBacktest = async () => {
    setLoading(true);
    setError('');
    setResults(null);
    try {
      // Run backtest — the backend provides both stats and trade data
      const res = await axios.get('/api/v1/backtest/run', {
        params: { ticker, timeframe, setup }
      });
      setResults(res.data);
    } catch (err: any) {
      setError(err.response?.data?.detail || err.response?.data?.message || err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="bg-gray-900 p-6 rounded-lg border border-gray-800 flex flex-wrap gap-4 items-end">
        <div>
          <label htmlFor="bt-ticker" className="block text-sm text-gray-400 mb-1">Ticker</label>
          <input
            id="bt-ticker"
            type="text"
            value={ticker}
            onChange={e => setTicker(e.target.value.toUpperCase())}
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
          onClick={runBacktest}
          disabled={loading}
          className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-700 disabled:cursor-not-allowed px-6 py-2 rounded text-white font-medium transition-colors"
        >
          {loading ? 'Running...' : 'Run Backtest'}
        </button>
      </div>

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
              <div className={`text-2xl font-bold ${results.win_rate > 50 ? 'text-emerald-400' : 'text-red-400'}`}>
                {results.win_rate.toFixed(1)}%
              </div>
            </div>
            <div className="bg-gray-900 p-4 rounded-lg border border-gray-800">
              <div className="text-gray-400 text-sm">Total Trades</div>
              <div className="text-2xl font-bold text-white">{results.total_trades}</div>
            </div>
            <div className="bg-gray-900 p-4 rounded-lg border border-gray-800">
              <div className="text-gray-400 text-sm">Total P&L</div>
              <div className={`text-2xl font-bold ${results.total_pnl_pct > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {results.total_pnl_pct > 0 ? '+' : ''}{results.total_pnl_pct.toFixed(2)}%
              </div>
            </div>
            <div className="bg-gray-900 p-4 rounded-lg border border-gray-800">
              <div className="text-gray-400 text-sm">Max Drawdown</div>
              <div className="text-2xl font-bold text-red-400">
                -{results.max_drawdown_pct.toFixed(2)}%
              </div>
            </div>
          </div>

          {results.trades.length > 0 && (
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
                    {results.trades.map((trade: any, idx: number) => (
                      <tr key={`${trade.entry_time}-${trade.exit_time}-${idx}`}>
                        <td className="p-3 text-gray-400 whitespace-nowrap">{trade.entry_time}</td>
                        <td className="p-3 text-gray-400 whitespace-nowrap">{trade.exit_time}</td>
                        <td className={`p-3 font-semibold ${trade.direction === 'bullish' ? 'text-emerald-400' : 'text-red-400'}`}>{trade.direction}</td>
                        <td className="p-3 text-right">{Number(trade.entry_price).toLocaleString('en-IN', { maximumFractionDigits: 2 })}</td>
                        <td className="p-3 text-right">{Number(trade.exit_price).toLocaleString('en-IN', { maximumFractionDigits: 2 })}</td>
                        <td className={`p-3 text-right font-semibold ${trade.pnl_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>{trade.pnl_pct >= 0 ? '+' : ''}{Number(trade.pnl_pct).toFixed(2)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default BacktestUI;
