import { useState, useRef, useCallback } from 'react';
import axios from 'axios';
import ChartWidget from '../components/ChartWidget';

const Dashboard = () => {
  const [ticker, setTicker] = useState('^NSEI');
  const [timeframe, setTimeframe] = useState('1d');
  const [chartData, setChartData] = useState<any[]>([]);
  const [signals, setSignals] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const abortRef = useRef<AbortController | null>(null);

  const loadData = useCallback(async (tf?: string) => {
    // Cancel any in-flight request
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const activeTf = tf || timeframe;
    setLoading(true);
    setError('');
    try {
      // Use the actual backend endpoint: /api/v1/indicators/{ticker}
      const res = await axios.get(`/api/v1/indicators/${encodeURIComponent(ticker)}`, {
        params: { timeframe: activeTf, limit: 500 },
        signal: controller.signal
      });

      const candles = res.data.candles || [];
      const formattedDf = candles.map((row: any) => ({
        time: row.time,
        open: row.open,
        high: row.high,
        low: row.low,
        close: row.close
      }));
      setChartData(formattedDf);

      // Fetch setup signals using the actual endpoint
      const signalsRes = await axios.get(`/api/v1/setups/${encodeURIComponent(ticker)}`, {
        params: { timeframe: activeTf },
        signal: controller.signal
      });
      setSignals(signalsRes.data.setups || []);

    } catch (err: any) {
      if (axios.isCancel(err)) return; // Silently ignore cancelled requests
      console.error(err);
      setError(err.response?.data?.detail || 'Failed to load data');
    } finally {
      setLoading(false);
    }
  }, [ticker, timeframe]);

  const handleTimeframeChange = (tf: string) => {
    setTimeframe(tf);
    loadData(tf);
  };

  return (
    <div className="flex gap-6 h-[calc(100vh-100px)]">
      <div className="flex-grow flex flex-col gap-4">
        <div className="flex justify-between items-center bg-gray-900 p-4 rounded-lg border border-gray-800">
            <div className="flex gap-4">
                <label htmlFor="ticker-input" className="sr-only">Ticker Symbol</label>
                <input
                    id="ticker-input"
                    type="text"
                    value={ticker}
                    onChange={e => setTicker(e.target.value.toUpperCase())}
                    onBlur={() => loadData()}
                    onKeyDown={e => e.key === 'Enter' && loadData()}
                    placeholder="Enter ticker..."
                    aria-label="Ticker symbol"
                    className="bg-gray-800 border border-gray-700 rounded px-3 py-1 text-white font-bold"
                />
            </div>
            <div className="flex gap-2 bg-gray-800 p-1 rounded-lg border border-gray-700" role="tablist" aria-label="Timeframe selector">
                {['1h', '1d', '1wk'].map(tf => (
                    <button
                        key={tf}
                        role="tab"
                        aria-selected={timeframe === tf}
                        onClick={() => handleTimeframeChange(tf)}
                        className={`px-3 py-1 rounded ${timeframe === tf ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white'}`}
                    >
                        {tf.toUpperCase()}
                    </button>
                ))}
            </div>
        </div>

        <div className="flex-grow bg-gray-900 rounded-lg border border-gray-800 relative">
            {loading && (
                <div className="absolute inset-0 z-10 flex items-center justify-center bg-gray-900/50 rounded-lg">
                    <div className="text-blue-400 animate-pulse" role="status">Loading Chart Data...</div>
                </div>
            )}
            {error && (
                <div className="absolute inset-0 z-10 flex items-center justify-center bg-gray-900/80 rounded-lg">
                    <div className="text-red-400">{error}</div>
                </div>
            )}
            {chartData.length > 0 && <ChartWidget data={chartData} height={600} />}
        </div>
      </div>

      <div className="w-80 bg-gray-900 rounded-lg border border-gray-800 p-4 overflow-y-auto">
        <h2 className="text-xl font-bold mb-4 border-b border-gray-800 pb-2">Setup Signals</h2>
        <div className="space-y-4">
            {signals.map((setup, idx) => (
                <div key={idx} className="bg-gray-800 p-3 rounded border border-gray-700">
                    <div className="flex justify-between items-center mb-2">
                        <span className="font-semibold text-gray-200">{(setup.name || '').replace(/_/g, ' ').toUpperCase()}</span>
                        <span className={`px-2 py-1 rounded text-xs font-bold ${
                            setup.signal === 'bullish' ? 'bg-emerald-900 text-emerald-400' :
                            setup.signal === 'bearish' ? 'bg-red-900 text-red-400' : 'bg-gray-700 text-gray-400'
                        }`}>
                            {setup.signal === 'bullish' ? 'BULLISH' : setup.signal === 'bearish' ? 'BEARISH' : 'NEUTRAL'}
                        </span>
                    </div>
                    {setup.reasoning && <p className="text-sm text-gray-400">{setup.reasoning}</p>}
                </div>
            ))}
            {signals.length === 0 && !loading && (
                <div className="text-gray-500 text-center py-4">No active setups on this timeframe.</div>
            )}
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
