import { useState, useRef, useCallback, useEffect } from 'react';
import axios from 'axios';
import ChartWidget from '../components/ChartWidget';
import TradingViewWidget from '../components/TradingViewWidget';
import TradingViewTASummary from '../components/TradingViewTASummary';
import { OptionChartViewer } from '../components/OptionChartViewer';
import { ArrowUpRight, RefreshCw, Search, BarChart3, TrendingUp, ShieldCheck, Zap } from 'lucide-react';

interface WatchlistItem {
  ticker: string;
  name: string;
  tv_symbol: string;
  ltp: number;
  change: number;
  change_pct: number;
  recommendation: string;
  buy_votes: number;
  sell_votes: number;
  neutral_votes: number;
}

const Dashboard = () => {
  const [tickerInput, setTickerInput] = useState('NIFTY');
  const [activeTicker, setActiveTicker] = useState('NIFTY');
  const [timeframe, setTimeframe] = useState('1h');
  const [chartMode, setChartMode] = useState<'tv_pro' | 'ai_overlay' | 'option_chart'>('tv_pro');

  const [chartData, setChartData] = useState<any[]>([]);
  const [signals, setSignals] = useState<any[]>([]);
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [marketStatus, setMarketStatus] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const abortRef = useRef<AbortController | null>(null);

  // Fetch Watchlist & Market Status
  const fetchMarketOverview = useCallback(async () => {
    try {
      const res = await axios.get('/api/v1/market/watchlist');
      if (res.data?.watchlist) {
        setWatchlist(res.data.watchlist);
      }
      if (res.data?.market_status) {
        setMarketStatus(res.data.market_status);
      }
    } catch {
      // Fallback silently if watchlist endpoint fails temporarily
    }
  }, []);

  useEffect(() => {
    fetchMarketOverview();
    const interval = setInterval(fetchMarketOverview, 15000);
    return () => clearInterval(interval);
  }, [fetchMarketOverview]);

  // Fetch Chart & Signal Data for AI Overlay Mode
  const fetchData = useCallback(async (tickerToLoad: string, tfToLoad: string) => {
    const cleanTicker = tickerToLoad.trim().toUpperCase();
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

    try {
      const [candlesResult, signalsResult] = await Promise.allSettled([
        axios.get(`/api/v1/market/candles/${encodeURIComponent(cleanTicker)}`, {
          params: { timeframe: tfToLoad, limit: 300 },
          signal: controller.signal,
        }),
        axios.get(`/api/v1/setups/${encodeURIComponent(cleanTicker)}`, {
          params: { timeframe: tfToLoad },
          signal: controller.signal,
        }),
      ]);

      if (controller.signal.aborted) return;

      if (candlesResult.status === 'fulfilled') {
        const candles = candlesResult.value.data?.candles || [];
        setChartData(candles);
      } else {
        // Fallback to legacy indicators endpoint
        try {
          const fb = await axios.get(`/api/v1/indicators/${encodeURIComponent(cleanTicker)}`, {
            params: { timeframe: tfToLoad, limit: 300 },
            signal: controller.signal,
          });
          setChartData(fb.data?.candles || []);
        } catch (e: any) {
          if (!axios.isCancel(e)) {
            setError('Failed to load market candles.');
          }
        }
      }

      if (signalsResult.status === 'fulfilled') {
        setSignals(signalsResult.value.data?.setups || []);
      } else {
        setSignals([]);
      }
    } catch (err: any) {
      if (!axios.isCancel(err)) {
        setError(err?.response?.data?.detail || 'Failed to load data.');
      }
    } finally {
      if (!controller.signal.aborted && abortRef.current === controller) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    fetchData(activeTicker, timeframe);
    return () => {
      if (abortRef.current) {
        abortRef.current.abort();
      }
    };
  }, [activeTicker, timeframe, fetchData]);

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const clean = tickerInput.trim().toUpperCase();
    if (clean && clean !== activeTicker) {
      setActiveTicker(clean);
    } else {
      fetchData(activeTicker, timeframe);
    }
  };

  const handleSelectTicker = (sym: string) => {
    setTickerInput(sym);
    setActiveTicker(sym);
  };

  const handleTimeframeChange = (tf: string) => {
    if (tf !== timeframe) {
      setTimeframe(tf);
    }
  };

  const isOpen = marketStatus?.is_open;

  return (
    <div className="dashboard-page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">Real-Time Market Surface / 01</span>
          <h1>Market Pulse & TradingView Analytics</h1>
          <p>Real-time live streaming charts, AI technical setups, and orderflow recommendations.</p>
        </div>
        <div className="flex items-center gap-3">
          <span className={`px-3 py-1 rounded-full text-xs font-semibold flex items-center gap-1.5 ${
            isOpen ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : 'bg-gray-800 text-gray-300 border border-gray-700'
          }`}>
            <span className={`w-2 h-2 rounded-full ${isOpen ? 'bg-emerald-400 animate-pulse' : 'bg-gray-400'}`} />
            {isOpen ? 'NSE LIVE (09:15 - 15:30 IST)' : 'NSE MARKET CLOSED'}
          </span>
          <div className="heading-note"><span className="live-dot" /> Real-time feed active</div>
        </div>
      </div>

      {/* Live Market Watchlist Ticker Bar */}
      {watchlist.length > 0 && (
        <section className="mb-4 overflow-x-auto pb-2" aria-label="Watchlist bar">
          <div className="flex gap-3 min-w-max">
            {watchlist.map((item) => {
              const isPositive = (item.change_pct || 0) >= 0;
              const isSelected = activeTicker === item.ticker;
              return (
                <button
                  key={item.ticker}
                  onClick={() => handleSelectTicker(item.ticker)}
                  className={`flex flex-col text-left px-3.5 py-2 rounded-lg border transition-all ${
                    isSelected
                      ? 'bg-blue-950/60 border-blue-500 shadow-md shadow-blue-500/20'
                      : 'bg-gray-900/60 border-gray-800 hover:border-gray-700'
                  }`}
                >
                  <div className="flex items-center justify-between gap-4">
                    <span className="font-bold text-xs text-gray-200">{item.ticker}</span>
                    <span className={`text-xs font-semibold ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
                      {isPositive ? '+' : ''}{item.change_pct?.toFixed(2)}%
                    </span>
                  </div>
                  <div className="flex items-center justify-between gap-2 mt-1">
                    <span className="font-mono text-sm font-bold text-white">
                      ₹{item.ltp?.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold uppercase ${
                      item.recommendation.includes('BUY') ? 'bg-emerald-900/80 text-emerald-300' :
                      item.recommendation.includes('SELL') ? 'bg-red-900/80 text-red-300' : 'bg-gray-800 text-gray-400'
                    }`}>
                      {item.recommendation}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        </section>
      )}

      <div className="dashboard-grid">
        <div className="chart-column">
          <div className="dashboard-toolbar flex flex-wrap items-center justify-between gap-3">
            <form onSubmit={handleSubmit} className="ticker-field">
              <Search aria-hidden="true" />
              <label htmlFor="ticker-input" className="sr-only">Ticker Symbol</label>
              <input
                id="ticker-input"
                type="text"
                value={tickerInput}
                onChange={e => setTickerInput(e.target.value.toUpperCase())}
                onKeyDown={e => e.key === 'Enter' && handleSubmit()}
                placeholder="Enter ticker (e.g. NIFTY, RELIANCE)..."
                aria-label="Ticker symbol"
                className="ticker-input"
              />
              <button type="submit" className="sr-only">Search</button>
              <span className="exchange-tag">NSE</span>
            </form>

            {/* Chart Mode Toggle */}
            <div className="flex items-center gap-1 bg-gray-900 border border-gray-800 p-1 rounded-lg">
              <button
                type="button"
                onClick={() => setChartMode('tv_pro')}
                className={`px-3 py-1 text-xs font-semibold rounded flex items-center gap-1.5 transition-all ${
                  chartMode === 'tv_pro'
                    ? 'bg-blue-600 text-white shadow'
                    : 'text-gray-400 hover:text-white'
                }`}
              >
                <TrendingUp className="w-3.5 h-3.5" />
                TradingView Pro Chart
              </button>
              <button
                type="button"
                onClick={() => setChartMode('ai_overlay')}
                className={`px-3 py-1 text-xs font-semibold rounded flex items-center gap-1.5 transition-all ${
                  chartMode === 'ai_overlay'
                    ? 'bg-blue-600 text-white shadow'
                    : 'text-gray-400 hover:text-white'
                }`}
              >
                <BarChart3 className="w-3.5 h-3.5" />
                AI Signals & Overlays
              </button>
              <button
                type="button"
                onClick={() => setChartMode('option_chart')}
                className={`px-3 py-1 text-xs font-semibold rounded flex items-center gap-1.5 transition-all ${
                  chartMode === 'option_chart'
                    ? 'bg-purple-600 text-white shadow'
                    : 'text-gray-400 hover:text-white'
                }`}
              >
                <Zap className="w-3.5 h-3.5" />
                Option Candlestick (F&O)
              </button>
            </div>

            <div className="timeframe-tabs" role="tablist" aria-label="Timeframe selector">
              {['1m', '5m', '15m', '1h', '1d', '1wk'].map(tf => (
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

            <button
              className="icon-button"
              onClick={() => handleSubmit()}
              aria-label="Refresh market data"
              title="Refresh market data"
            >
              <RefreshCw className={loading ? 'spin' : ''} />
            </button>
          </div>

          <div className="chart-panel">
            <div className="chart-panel-heading">
              <div>
                <span className="eyebrow">NSE Real-Time Streaming</span>
                <h2>{activeTicker} <ArrowUpRight aria-hidden="true" /></h2>
              </div>
              <div className="flex items-center gap-2">
                <span className="chart-live">● REAL-TIME FEED</span>
              </div>
            </div>

            {loading && chartMode === 'ai_overlay' && (
              <div className="chart-state" role="status">
                <div className="loader-line" /> Loading market data...
              </div>
            )}
            {error && chartMode === 'ai_overlay' && (
              <div className="chart-state error" role="alert">
                <div>{error}</div>
              </div>
            )}

            {/* Tri-Mode Chart Render: TradingView Pro, Option Candlestick, or AI Overlays */}
            {chartMode === 'tv_pro' ? (
              <TradingViewWidget
                symbol={activeTicker}
                interval={timeframe === '1d' ? 'D' : timeframe === '1wk' ? 'W' : timeframe}
                height={600}
                theme="dark"
              />
            ) : chartMode === 'option_chart' ? (
              <OptionChartViewer
                initialUnderlying={activeTicker.includes('BANK') ? 'BANKNIFTY' : activeTicker.includes('FIN') ? 'FINNIFTY' : 'NIFTY'}
                height={600}
              />
            ) : (
              chartData.length > 0 && <ChartWidget data={chartData} height={600} ticker={activeTicker} timeframe={timeframe} />
            )}

          </div>
        </div>

        <aside className="signals-panel flex flex-col gap-4">
          {/* TradingView Technical Analysis Meter */}
          <div className="bg-gray-900/70 border border-gray-800 rounded-lg p-3">
            <div className="flex items-center justify-between mb-2">
              <span className="eyebrow">Technical Gauge</span>
              <span className="text-xs text-blue-400 font-semibold flex items-center gap-1">
                <ShieldCheck className="w-3.5 h-3.5" /> TradingView Consensus
              </span>
            </div>
            <TradingViewTASummary symbol={activeTicker} interval={timeframe} height={320} />
          </div>

          {/* AI Setup Signals */}
          <div className="flex-1">
            <div className="signals-heading">
              <div>
                <span className="eyebrow">AI readout</span>
                <h2>Setup signals</h2>
              </div>
              <span className="signal-count">{signals.length.toString().padStart(2, '0')}</span>
            </div>
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
          </div>
        </aside>
      </div>
    </div>
  );
};

export default Dashboard;
