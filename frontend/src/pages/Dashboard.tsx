import { useState, useRef, useCallback, useEffect } from 'react';
import axios from 'axios';
import ChartWidget from '../components/ChartWidget';
import { ArrowUpRight, RefreshCw, Search } from 'lucide-react';

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
      if (!controller.signal.aborted && abortRef.current === controller) {
        setLoading(false);
      }
    }
  }, [ticker, timeframe]);

  useEffect(() => {
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError('');

    axios.get(`/api/v1/indicators/${encodeURIComponent(ticker)}`, {
      params: { timeframe, limit: 500 },
      signal: controller.signal,
    }).then(async (res) => {
      setChartData((res.data.candles || []).map((row: any) => ({
        time: row.time, open: row.open, high: row.high, low: row.low, close: row.close,
      })));
      const signalsRes = await axios.get(`/api/v1/setups/${encodeURIComponent(ticker)}`, {
        params: { timeframe }, signal: controller.signal,
      });
      setSignals(signalsRes.data.setups || []);
    }).catch((err: any) => {
      if (!axios.isCancel(err)) setError(err.response?.data?.detail || 'Failed to load data');
    }).finally(() => {
      if (!controller.signal.aborted && abortRef.current === controller) setLoading(false);
    });

    return () => controller.abort();
  }, [ticker, timeframe]);

  const handleTimeframeChange = (tf: string) => {
    setTimeframe(tf);
  };

  return (
    <div className="dashboard-page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">Decision surface / 01</span>
          <h1>Market pulse</h1>
          <p>Read the tape, inspect the active setups, and decide what deserves attention.</p>
        </div>
        <div className="heading-note"><span className="live-dot" /> Data refreshes on demand</div>
      </div>
      <div className="dashboard-grid">
      <div className="chart-column">
        <div className="dashboard-toolbar">
            <div className="ticker-field">
                <Search aria-hidden="true" />
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
                    className="ticker-input"
                />
                  <span className="exchange-tag">NSE</span>
            </div>
                <div className="timeframe-tabs" role="tablist" aria-label="Timeframe selector">
                {['1h', '1d', '1wk'].map(tf => (
                    <button
                        key={tf}
                        role="tab"
                        aria-selected={timeframe === tf}
                        onClick={() => handleTimeframeChange(tf)}
                        className={`timeframe-tab ${timeframe === tf ? 'active' : ''}`}
                    >
                        {tf.toUpperCase()}
                    </button>
                ))}
            </div>
              <button className="icon-button" onClick={() => loadData()} aria-label="Refresh market data" title="Refresh market data"><RefreshCw className={loading ? 'spin' : ''} /></button>
        </div>

            <div className="chart-panel">
              <div className="chart-panel-heading"><div><span className="eyebrow">NIFTY 50 / NSE</span><h2>{ticker} <ArrowUpRight aria-hidden="true" /></h2></div><span className="chart-live">● LIVE FEED</span></div>
            {loading && (
                <div className="chart-state" role="status">
                  <div className="loader-line" /> Loading market data...
                </div>
            )}
            {error && (
                <div className="chart-state error" role="alert">
                  <div>{error}</div>
                </div>
            )}
            {chartData.length > 0 && <ChartWidget data={chartData} height={600} />}
              {!loading && !error && chartData.length === 0 && <div className="chart-state">Enter a ticker and load data to begin.</div>}
        </div>
      </div>

            <aside className="signals-panel">
            <div className="signals-heading"><div><span className="eyebrow">AI readout</span><h2>Setup signals</h2></div><span className="signal-count">{signals.length.toString().padStart(2, '0')}</span></div>
            <div className="signals-list">
            {signals.map((setup, idx) => (
                <div key={idx} className="signal-card">
                  <div className="signal-card-top">
                    <span className="signal-name">{(setup.name || '').replace(/_/g, ' ').toUpperCase()}</span>
                    <span className={`signal-pill ${
                            setup.signal === 'bullish' ? 'bg-emerald-900 text-emerald-400' :
                            setup.signal === 'bearish' ? 'bg-red-900 text-red-400' : 'bg-gray-700 text-gray-400'
                        }`}>
                            {setup.signal === 'bullish' ? 'BULLISH' : setup.signal === 'bearish' ? 'BEARISH' : 'NEUTRAL'}
                        </span>
                    </div>
                    {setup.reasoning && <p className="signal-reasoning">{setup.reasoning}</p>}
                </div>
            ))}
            {signals.length === 0 && !loading && (
                  <div className="empty-signal">No active setups on this timeframe.</div>
            )}
        </div>
              </aside>
              </div>
    </div>
  );
};

export default Dashboard;
