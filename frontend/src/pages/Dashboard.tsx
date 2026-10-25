import { useState, useRef, useCallback, useEffect } from 'react';
import axios from 'axios';
import ChartWidget from '../components/ChartWidget';
import TradingViewWidget from '../components/TradingViewWidget';
import TradingViewTASummary from '../components/TradingViewTASummary';
import { OptionChartViewer } from '../components/OptionChartViewer';
import ErrorBoundary from '../components/ErrorBoundary';
import { MarketSessionBadge } from '../components/MarketSessionBadge';
import { formatIndianCurrency } from '../utils/formatters';
import { getExchangeLotSize } from '../utils/foUtils';
import {
  ArrowUpRight,
  RefreshCw,
  Search,
  BarChart3,
  TrendingUp,
  ShieldCheck,
  Zap,
  Newspaper,
  ExternalLink,
  AlertCircle,
} from 'lucide-react';

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

interface NewsSentimentSummary {
  ticker: string;
  total_headlines: number;
  bullish_count: number;
  bearish_count: number;
  neutral_count: number;
  overall_sentiment: string;
  mean_score: number;
  headlines: Array<{
    time: string;
    url: string;
    title: string;
    source: string;
    sentiment_score: number;
    sentiment_label: string;
  }>;
}

const DEFAULT_FALLBACK_WATCHLIST: WatchlistItem[] = [
  { ticker: 'NIFTY', name: 'Nifty 50', tv_symbol: 'NSE:NIFTY', ltp: 24850.0, change: 0, change_pct: 0, recommendation: 'NEUTRAL', buy_votes: 0, sell_votes: 0, neutral_votes: 0 },
  { ticker: 'BANKNIFTY', name: 'Bank Nifty', tv_symbol: 'NSE:BANKNIFTY', ltp: 52100.0, change: 0, change_pct: 0, recommendation: 'NEUTRAL', buy_votes: 0, sell_votes: 0, neutral_votes: 0 },
  { ticker: 'SENSEX', name: 'BSE Sensex', tv_symbol: 'BSE:SENSEX', ltp: 81200.0, change: 0, change_pct: 0, recommendation: 'NEUTRAL', buy_votes: 0, sell_votes: 0, neutral_votes: 0 },
  { ticker: 'FINNIFTY', name: 'Fin Nifty', tv_symbol: 'NSE:FINNIFTY', ltp: 23400.0, change: 0, change_pct: 0, recommendation: 'NEUTRAL', buy_votes: 0, sell_votes: 0, neutral_votes: 0 },
];

const Dashboard = () => {
  const [tickerInput, setTickerInput] = useState('NIFTY');
  const [activeTicker, setActiveTicker] = useState('NIFTY');
  const [timeframe, setTimeframe] = useState('1h');
  const [chartMode, setChartMode] = useState<'tv_pro' | 'ai_overlay' | 'option_chart'>('tv_pro');

  const [chartData, setChartData] = useState<any[]>([]);
  const [signals, setSignals] = useState<any[]>([]);
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [newsSentiment, setNewsSentiment] = useState<NewsSentimentSummary | null>(null);
  const [loadingNews, setLoadingNews] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const abortRef = useRef<AbortController | null>(null);
  const newsAbortRef = useRef<AbortController | null>(null);

  // Fetch Watchlist & Market Status
  const fetchMarketOverview = useCallback(async () => {
    try {
      const res = await axios.get('/api/v1/market/watchlist');
      if (Array.isArray(res.data?.watchlist) && res.data.watchlist.length > 0) {
        setWatchlist(res.data.watchlist);
      }
    } catch {
      // Keep existing watchlist or fallback if endpoint fails temporarily
    }
  }, []);

  // Fetch Indian Market Financial News & Sentiment
  const fetchNewsSentiment = useCallback(async (ticker: string) => {
    if (newsAbortRef.current) {
      newsAbortRef.current.abort();
    }
    const controller = new AbortController();
    newsAbortRef.current = controller;

    try {
      setLoadingNews(true);
      const res = await axios.get(`/api/v1/market/news-sentiment/${encodeURIComponent(ticker)}`, {
        signal: controller.signal,
      });
      if (!controller.signal.aborted) {
        setNewsSentiment(res.data);
      }
    } catch (err: any) {
      if (!axios.isCancel(err) && !controller.signal.aborted) {
        setNewsSentiment(null);
      }
    } finally {
      if (!controller.signal.aborted && newsAbortRef.current === controller) {
        setLoadingNews(false);
      }
    }
  }, []);

  useEffect(() => {
    let ignore = false;
    axios.get('/api/v1/market/watchlist').then(res => {
      if (!ignore && Array.isArray(res.data?.watchlist) && res.data.watchlist.length > 0) {
        setWatchlist(res.data.watchlist);
      }
    }).catch(() => {});

    const interval = setInterval(fetchMarketOverview, 15000);
    return () => {
      ignore = true;
      clearInterval(interval);
    };
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
            setError('Failed to load market candles. Please check if the market data service is running.');
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
        setError(err?.response?.data?.detail || err.message || 'Failed to load market data.');
      }
    } finally {
      if (!controller.signal.aborted && abortRef.current === controller) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void Promise.resolve().then(() => {
      if (!cancelled) {
        fetchData(activeTicker, timeframe);
        fetchNewsSentiment(activeTicker);
      }
    });

    return () => {
      cancelled = true;
      if (abortRef.current) abortRef.current.abort();
      if (newsAbortRef.current) newsAbortRef.current.abort();
    };
  }, [activeTicker, timeframe, fetchData, fetchNewsSentiment]);

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const clean = tickerInput.trim().toUpperCase().replace(/[^A-Z0-9.\-^=]/g, '');
    if (!clean) {
      setError('Please enter a valid Indian F&O symbol (e.g. NIFTY, BANKNIFTY, SENSEX).');
      return;
    }
    setError('');
    if (clean !== activeTicker) {
      setActiveTicker(clean);
    } else {
      fetchData(activeTicker, timeframe);
      fetchNewsSentiment(activeTicker);
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

  const displayWatchlist = watchlist.length > 0 ? watchlist : DEFAULT_FALLBACK_WATCHLIST;

  return (
    <div className="dashboard-page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">Real-Time Market Surface / 01</span>
          <h1>Market Pulse &amp; TradingView Analytics</h1>
          <p>Real-time live streaming charts, AI technical setups, and orderflow recommendations.</p>
        </div>
        <div className="flex flex-col sm:flex-row items-start sm:items-center gap-3">
          <MarketSessionBadge />
          <div className="heading-note"><span className="live-dot" /> F&O Index Stream Active</div>
        </div>
      </div>

      {/* Live Market Watchlist Ticker Bar */}
      <ErrorBoundary compact title="Watchlist Bar Error">
        <section className="mb-4 overflow-x-auto pb-2" aria-label="Watchlist bar">
          <div className="flex items-center gap-2 mb-1.5 text-[11px] text-gray-400 font-semibold px-1">
            <span>{watchlist.length > 0 ? 'LIVE TICKING F&O WATCHLIST' : 'DEFAULT F&O UNIVERSE'}</span>
            {watchlist.length === 0 && (
              <button
                type="button"
                onClick={fetchMarketOverview}
                className="text-blue-400 hover:underline flex items-center gap-1 ml-2"
              >
                <RefreshCw className="w-3 h-3" /> Sync Watchlist
              </button>
            )}
          </div>
          <div className="flex gap-3 min-w-max">
            {displayWatchlist.map((item) => {
              const isPositive = (item.change_pct || 0) >= 0;
              const isSelected = activeTicker === item.ticker;
              const lotSize = getExchangeLotSize(item.ticker);
              return (
                <button
                  key={item.ticker}
                  type="button"
                  onClick={() => handleSelectTicker(item.ticker)}
                  className={`flex flex-col text-left px-3.5 py-2 rounded-lg border transition-all ${
                    isSelected
                      ? 'bg-blue-950/60 border-blue-500 shadow-md shadow-blue-500/20'
                      : 'bg-gray-900/60 border-gray-800 hover:border-gray-700'
                  }`}
                >
                  <div className="flex items-center justify-between gap-4">
                    <div className="flex items-center gap-1.5">
                      <span className="font-bold text-xs text-gray-200">{item.ticker}</span>
                      <span className="text-[9px] px-1 py-0.2 rounded bg-gray-800 text-gray-400 font-mono">
                        {lotSize}L
                      </span>
                    </div>
                    <span className={`text-xs font-semibold ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
                      {isPositive ? '+' : ''}{item.change_pct?.toFixed(2)}%
                    </span>
                  </div>
                  <div className="flex items-center justify-between gap-2 mt-1">
                    <span className="font-mono text-sm font-bold text-white">
                      {formatIndianCurrency(item.ltp)}
                    </span>
                    {(() => {
                      const rec = String(item.recommendation || '').toUpperCase();
                      return (
                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold uppercase ${
                          rec.includes('BUY') ? 'bg-emerald-900/80 text-emerald-300' :
                          rec.includes('SELL') ? 'bg-red-900/80 text-red-300' : 'bg-gray-800 text-gray-400'
                        }`}>
                          {item.recommendation || 'NEUTRAL'}
                        </span>
                      );
                    })()}
                  </div>
                </button>
              );
            })}
          </div>
        </section>
      </ErrorBoundary>

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
                placeholder="Enter F&O ticker (e.g. NIFTY, BANKNIFTY, SENSEX)..."
                aria-label="Ticker symbol"
                className="ticker-input"
              />
              <button type="submit" className="sr-only">Search</button>
              <span className="exchange-tag">
                {activeTicker.includes('SENSEX') || activeTicker.includes('BSESN') ? 'BSE' : 'NSE'}
              </span>
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
                AI Signals &amp; Overlays
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
                Option Candlestick (F&amp;O)
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
              type="button"
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
                <span className="eyebrow">
                  {activeTicker.includes('SENSEX') || activeTicker.includes('BSESN') ? 'BSE F&O' : 'NSE F&O'} Real-Time Streaming
                </span>
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
              <div className="chart-state error p-4 flex flex-col items-center justify-center gap-2" role="alert">
                <div className="flex items-center gap-2 text-red-300 text-sm">
                  <AlertCircle className="w-4 h-4 shrink-0 text-red-400" />
                  <span>{error}</span>
                </div>
                <button
                  type="button"
                  onClick={() => fetchData(activeTicker, timeframe)}
                  className="px-3 py-1 bg-red-900/80 hover:bg-red-800 text-xs text-white rounded border border-red-700 transition"
                >
                  Retry Loading Candles
                </button>
              </div>
            )}

            {/* Tri-Mode Chart Render: TradingView Pro, Option Candlestick, or AI Overlays with localized ErrorBoundaries */}
            {chartMode === 'tv_pro' ? (
              <ErrorBoundary compact title="TradingView Chart Rendering Error">
                <TradingViewWidget
                  symbol={activeTicker}
                  interval={timeframe === '1d' ? 'D' : timeframe === '1wk' ? 'W' : timeframe}
                  height={600}
                  theme="dark"
                />
              </ErrorBoundary>
            ) : chartMode === 'option_chart' ? (
              <ErrorBoundary compact title="Option Candlestick Viewer Error">
                <OptionChartViewer
                  initialUnderlying={
                    activeTicker.includes('SENSEX') || activeTicker.includes('BSESN') ? 'SENSEX' :
                    activeTicker.includes('BANK') ? 'BANKNIFTY' :
                    activeTicker.includes('FIN') ? 'FINNIFTY' :
                    activeTicker.includes('MID') ? 'MIDCPNIFTY' :
                    'NIFTY'
                  }
                  height={600}
                />
              </ErrorBoundary>
            ) : (
              <ErrorBoundary compact title="AI Overlay Chart Error">
                {chartData.length > 0 ? (
                  <ChartWidget data={chartData} height={600} ticker={activeTicker} timeframe={timeframe} />
                ) : !loading && !error ? (
                  <div className="chart-state p-8 text-center text-gray-400" role="status">
                    <p className="mb-2">No candle data available for {activeTicker} on {timeframe.toUpperCase()}.</p>
                    <button
                      type="button"
                      onClick={() => fetchData(activeTicker, timeframe)}
                      className="px-3.5 py-1.5 bg-blue-600 hover:bg-blue-500 text-xs text-white rounded transition"
                    >
                      Fetch Market Data
                    </button>
                  </div>
                ) : null}
              </ErrorBoundary>
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
            <ErrorBoundary compact title="Technical Gauge Error">
              <TradingViewTASummary symbol={activeTicker} interval={timeframe} height={320} />
            </ErrorBoundary>
          </div>

          {/* Real-Time Indian Market News & Sentiment */}
          <div className="bg-gray-900/70 border border-gray-800 rounded-lg p-3">
            <div className="flex items-center justify-between mb-2">
              <span className="eyebrow">Market News Pulse</span>
              <span className="text-xs text-purple-400 font-semibold flex items-center gap-1">
                <Newspaper className="w-3.5 h-3.5" /> Sentiment Engine
              </span>
            </div>

            <ErrorBoundary compact title="News Sentiment Engine Error">
              {loadingNews ? (
                <div className="text-xs text-gray-500 py-3 text-center flex items-center justify-center gap-2">
                  <RefreshCw className="w-3 h-3 animate-spin" /> Analyzing live Indian news...
                </div>
              ) : newsSentiment ? (
                <div className="space-y-2.5">
                  <div className="flex items-center justify-between bg-gray-950/60 p-2 rounded border border-gray-800/80">
                    <div className="flex items-center gap-2">
                      <span className={`text-[10px] px-2 py-0.5 rounded font-bold uppercase ${
                        newsSentiment.overall_sentiment === 'BULLISH' ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' :
                        newsSentiment.overall_sentiment === 'BEARISH' ? 'bg-red-950 text-red-400 border border-red-800' :
                        'bg-gray-800 text-gray-300 border border-gray-700'
                      }`}>
                        {newsSentiment.overall_sentiment}
                      </span>
                      <span className="text-[11px] text-gray-400 font-mono">
                        Score: {Number(newsSentiment.mean_score || 0) > 0 ? '+' : ''}{Number(newsSentiment.mean_score || 0).toFixed(2)}
                      </span>
                    </div>
                    <div className="flex items-center gap-1.5 text-[10px]">
                      <span className="text-emerald-400 font-semibold">+{newsSentiment.bullish_count} Bull</span>
                      <span className="text-gray-500">•</span>
                      <span className="text-red-400 font-semibold">-{newsSentiment.bearish_count} Bear</span>
                    </div>
                  </div>

                  <div className="space-y-1.5 max-h-56 overflow-y-auto pr-1">
                    {newsSentiment.headlines && newsSentiment.headlines.slice(0, 4).map((h, i) => (
                      <a
                        key={i}
                        href={h.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="block p-2 rounded bg-gray-950/40 hover:bg-gray-800/60 border border-gray-800/50 hover:border-gray-700 transition group text-left"
                      >
                        <div className="flex items-start justify-between gap-1.5">
                          <p className="text-xs text-gray-300 group-hover:text-white line-clamp-2 leading-snug">
                            {h.title}
                          </p>
                          <ExternalLink className="w-3 h-3 text-gray-500 group-hover:text-blue-400 shrink-0 mt-0.5" />
                        </div>
                        <div className="flex items-center justify-between mt-1 text-[10px] text-gray-500">
                          <span>{h.source}</span>
                          <span className={
                            h.sentiment_label === 'BULLISH' ? 'text-emerald-400 font-semibold' :
                            h.sentiment_label === 'BEARISH' ? 'text-red-400 font-semibold' : 'text-gray-500'
                          }>
                            {h.sentiment_label}
                          </span>
                        </div>
                      </a>
                    ))}
                    {(!newsSentiment.headlines || newsSentiment.headlines.length === 0) && (
                      <p className="text-xs text-gray-500 py-1 text-center">No recent news for {activeTicker}.</p>
                    )}
                  </div>
                </div>
              ) : (
                <div className="text-xs text-gray-500 py-3 text-center space-y-1.5">
                  <p>News feed currently unavailable for {activeTicker}.</p>
                  <button
                    type="button"
                    onClick={() => fetchNewsSentiment(activeTicker)}
                    className="text-[11px] text-blue-400 hover:underline inline-flex items-center gap-1"
                  >
                    <RefreshCw className="w-3 h-3" /> Retry news feed
                  </button>
                </div>
              )}
            </ErrorBoundary>
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
            <ErrorBoundary compact title="Signals Panel Error">
              <div className="signals-list">
                {signals.map((setup, idx) => (
                  <div key={idx} className="signal-card">
                    <div className="signal-card-top">
                      <span className="signal-name">{(setup.name || '').replace(/_/g, ' ').toUpperCase()}</span>
                      <span className={`signal-pill ${
                        setup.signal === 'bullish' ? 'bg-emerald-950 text-emerald-300 border border-emerald-800' :
                        setup.signal === 'bearish' ? 'bg-rose-950 text-rose-300 border border-rose-800' : 'bg-gray-800 text-gray-200 border border-gray-700'
                      }`}>
                        {setup.signal === 'bullish' ? 'BULLISH' : setup.signal === 'bearish' ? 'BEARISH' : 'NEUTRAL'}
                      </span>
                    </div>
                    {setup.reasoning && <p className="signal-reasoning">{setup.reasoning}</p>}
                  </div>
                ))}
                {signals.length === 0 && !loading && (
                  <div className="empty-signal">
                    No active setups on this timeframe.
                    <button
                      type="button"
                      onClick={() => fetchData(activeTicker, timeframe)}
                      className="block text-xs text-blue-400 hover:underline mt-1.5"
                    >
                      Re-scan setups
                    </button>
                  </div>
                )}
              </div>
            </ErrorBoundary>
          </div>
        </aside>
      </div>
    </div>
  );
};

export default Dashboard;
