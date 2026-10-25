import { useState, useEffect, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { RefreshCw, Play, TrendingUp, AlertTriangle } from 'lucide-react';
import ErrorBoundary from '../components/ErrorBoundary';
import { formatIndianCurrency } from '../utils/formatters';
import { formatContractSymbol, getExchangeLotSize } from '../utils/foUtils';

interface Insight {
  type: string;
  severity: string;
  setup: string;
  regime: string;
  metric: string;
  value: number;
  recommendation: string;
  action: string;
}

interface RecentTrade {
  trade_id: string;
  ticker: string;
  direction: string;
  exit_reason: string;
  pnl_pct: number | null;
  bars_held: number;
  regime: string;
}

interface JournalData {
  summary: {
    total_trades?: number;
    win_rate?: number;
    total_cash_pnl?: number;
    avg_pnl_pct?: number;
    sharpe_ratio?: number;
    max_drawdown_pct?: number;
  };
  insights?: Insight[];
  profitability_matrix?: Record<string, Record<string, { win_rate?: number; avg_pnl?: number; trade_count?: number; sharpe?: number }>>;
  rl_weights?: Record<string, number>;
  rl_diagnostics?: { version?: number; last_update?: string; n_setup_regime_pairs?: number };
  recent_trades?: RecentTrade[];
}

const severityColors: Record<string, string> = {
  critical: 'bg-red-900/50 border-red-500 text-red-300',
  warning: 'bg-yellow-900/50 border-yellow-500 text-yellow-300',
  info: 'bg-blue-900/50 border-blue-500 text-blue-300',
};

const formatUpdateDate = (dateVal?: string | number) => {
  if (!dateVal) return 'Never';
  let parsed: Date;
  if (typeof dateVal === 'number') {
    parsed = new Date(dateVal < 1e11 ? dateVal * 1000 : dateVal);
  } else {
    const trimmed = String(dateVal).trim();
    if (!trimmed) return 'Never';
    if (/^\d+$/.test(trimmed)) {
      const num = parseInt(trimmed, 10);
      parsed = new Date(num < 1e11 ? num * 1000 : num);
    } else {
      parsed = new Date(trimmed.replace(' ', 'T'));
    }
  }
  return isNaN(parsed.getTime()) ? 'Never' : parsed.toLocaleString('en-IN');
};

const AIJournal = () => {
  const [data, setData] = useState<JournalData | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const abortControllerRef = useRef<AbortController | null>(null);

  const fetchJournal = useCallback(async (isManualRefresh = false) => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;

    if (isManualRefresh) {
      setRefreshing(true);
      setError('');
    }

    try {
      const res = await axios.get('/api/v1/dashboard/ai-journal', {
        signal: controller.signal,
      });
      setData(res.data);
    } catch (err: any) {
      if (axios.isCancel(err)) return;
      const status = err?.response?.status;
      setError(status ? `AI Journal is unavailable (HTTP ${status}).` : 'Backend is offline. Start the API server and retry.');
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    let ignore = false;
    const controller = new AbortController();
    abortControllerRef.current = controller;

    axios.get('/api/v1/dashboard/ai-journal', { signal: controller.signal })
      .then(res => {
        if (!ignore) {
          setData(res.data);
          setLoading(false);
        }
      })
      .catch((err: any) => {
        if (!ignore && !axios.isCancel(err)) {
          const status = err?.response?.status;
          setError(status ? `AI Journal is unavailable (HTTP ${status}).` : 'Backend is offline. Start the API server and retry.');
          setLoading(false);
        }
      });

    return () => {
      ignore = true;
      controller.abort();
    };
  }, []);

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="flex flex-col items-center gap-3 text-gray-400">
          <RefreshCw className="w-6 h-6 animate-spin text-blue-500" />
          <span className="text-sm font-medium">Loading AI Self-Play Journal...</span>
        </div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="state-panel" role="alert">
        <strong>{error}</strong>
        <p className="text-xs text-gray-400 mt-1">Unable to load journal telemetry.</p>
        <button className="retry-button mt-3" onClick={() => void fetchJournal(true)}>Retry connection</button>
      </div>
    );
  }

  if (!data) return <div className="text-gray-400 p-8">No data available.</div>;

  const summary = data.summary || {};
  const insights = Array.isArray(data.insights) ? data.insights : [];
  const profitability_matrix = data.profitability_matrix || {};
  const rl_weights = data.rl_weights || {};
  const rl_diagnostics = data.rl_diagnostics || {};
  const recent_trades = Array.isArray(data.recent_trades) ? data.recent_trades : [];

  const totalTrades = Number(summary.total_trades) || 0;
  const winRate = Number(summary.win_rate) || 0;
  const totalCashPnl = Number(summary.total_cash_pnl) || 0;
  const avgPnlPct = Number(summary.avg_pnl_pct) || 0;
  const sharpeRatio = Number(summary.sharpe_ratio) || 0;
  const maxDrawdownPct = Math.abs(Number(summary.max_drawdown_pct) || 0);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            🧠 AI Self-Play Journal &amp; Meta-Learner
          </h1>
          <div className="text-xs text-gray-400 mt-1 font-mono">
            RL Version: <span className="text-blue-400 font-bold">{rl_diagnostics.version ?? 0}</span> | Last Updated: {formatUpdateDate(rl_diagnostics.last_update)}
          </div>
        </div>
        <button
          type="button"
          className="icon-button"
          onClick={() => void fetchJournal(true)}
          disabled={loading || refreshing}
          aria-label="Refresh AI Journal"
          title="Refresh AI Journal"
        >
          <RefreshCw className={refreshing ? 'spin' : ''} />
        </button>
      </div>

      {error && (
        <div className="state-panel compact" role="alert">
          <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 inline mr-2" />
          <strong>{error}</strong>
          <button className="retry-button ml-3" onClick={() => void fetchJournal(true)}>Retry</button>
        </div>
      )}

      {/* Summary Cards */}
      <ErrorBoundary compact title="AI Journal Metrics Error">
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 sm:gap-4">
          <div className="bg-gray-900 p-4 rounded-lg border border-gray-800">
            <p className="text-gray-400 text-xs font-semibold uppercase">Total Trades</p>
            <p className="text-xl sm:text-2xl font-bold text-white mt-1">{totalTrades}</p>
          </div>
          <div className="bg-gray-900 p-4 rounded-lg border border-gray-800">
            <p className="text-gray-400 text-xs font-semibold uppercase">Win Rate</p>
            <p className={`text-xl sm:text-2xl font-bold mt-1 ${
              totalTrades === 0
                ? 'text-gray-400'
                : winRate >= 0.5
                  ? 'text-emerald-400'
                  : 'text-red-400'
            }`}>
              {totalTrades === 0 ? '0.0%' : `${(winRate * 100).toFixed(1)}%`}
            </p>
          </div>
          <div className="bg-gray-900 p-4 rounded-lg border border-gray-800">
            <p className="text-gray-400 text-xs font-semibold uppercase">Total Return</p>
            <p className={`text-xl sm:text-2xl font-bold mt-1 ${
              totalTrades === 0
                ? 'text-gray-400'
                : totalCashPnl >= 0
                  ? 'text-emerald-400'
                  : 'text-red-400'
            }`}>
              {totalTrades === 0 ? '₹0.00' : formatIndianCurrency(totalCashPnl, { showSign: true })}
            </p>
          </div>
          <div className="bg-gray-900 p-4 rounded-lg border border-gray-800">
            <p className="text-gray-400 text-xs font-semibold uppercase">Avg Return / Trade</p>
            <p className={`text-xl sm:text-2xl font-bold mt-1 ${
              totalTrades === 0
                ? 'text-gray-400'
                : avgPnlPct >= 0
                  ? 'text-emerald-400'
                  : 'text-red-400'
            }`}>
              {totalTrades === 0 ? '0.00%' : `${avgPnlPct >= 0 ? '+' : ''}${avgPnlPct.toFixed(2)}%`}
            </p>
          </div>
          <div className="bg-gray-900 p-4 rounded-lg border border-gray-800">
            <p className="text-gray-400 text-xs font-semibold uppercase">Sharpe Ratio</p>
            <p className={`text-xl sm:text-2xl font-bold mt-1 ${totalTrades === 0 ? 'text-gray-400' : 'text-blue-400'}`}>
              {sharpeRatio.toFixed(2)}
            </p>
          </div>
          <div className="bg-gray-900 p-4 rounded-lg border border-gray-800">
            <p className="text-gray-400 text-xs font-semibold uppercase">Max Drawdown</p>
            <p className={`text-xl sm:text-2xl font-bold mt-1 ${totalTrades === 0 || maxDrawdownPct === 0 ? 'text-gray-400' : 'text-red-400'}`}>
              {maxDrawdownPct === 0 ? '0.0%' : `-${maxDrawdownPct.toFixed(1)}%`}
            </p>
          </div>
        </div>
      </ErrorBoundary>

      {/* AI Insights */}
      {insights.length > 0 && (
        <ErrorBoundary compact title="Insights Panel Error">
          <div className="bg-gray-900 p-6 rounded-lg border border-gray-800">
            <h2 className="text-lg font-bold text-white mb-4">🔍 AI Self-Review Insights</h2>
            <div className="space-y-3">
              {insights.map((insight, idx) => (
                <div
                  key={idx}
                  className={`p-3 rounded border ${severityColors[insight.severity] || severityColors.info}`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-mono uppercase opacity-75">{insight.severity}</span>
                    <span className="text-xs opacity-50">|</span>
                    <span className="text-xs opacity-75">{insight.setup} → {insight.regime}</span>
                  </div>
                  <p className="text-sm">{insight.recommendation}</p>
                </div>
              ))}
            </div>
          </div>
        </ErrorBoundary>
      )}

      {/* Setup Scorecard (RL Weights) */}
      {Object.keys(rl_weights).length > 0 && (
        <ErrorBoundary compact title="RL Weights Error">
          <div className="bg-gray-900 p-6 rounded-lg border border-gray-800">
            <h2 className="text-lg font-bold text-white mb-4">⚖️ Setup Scorecard (RL-Learned Weights)</h2>
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
              {Object.entries(rl_weights)
                .sort(([, a], [, b]) => Number(b) - Number(a))
                .map(([setup, weight]) => {
                  const w = Number(weight) || 0;
                  const barWidth = Math.max(5, Math.min(100, w * 100));
                  const color = w >= 0.6 ? 'bg-emerald-500' : w >= 0.4 ? 'bg-yellow-500' : 'bg-red-500';
                  return (
                    <div key={setup} className="bg-gray-800 p-3 rounded">
                      <div className="text-xs text-gray-400 truncate mb-1" title={setup}>{setup}</div>
                      <div className="flex items-center gap-2">
                        <div className="flex-1 bg-gray-700 rounded-full h-2 overflow-hidden">
                          <div className={`${color} h-2 rounded-full`} style={{ width: `${barWidth}%` }} />
                        </div>
                        <span className="text-xs font-mono text-gray-300">{(w * 100).toFixed(0)}%</span>
                      </div>
                    </div>
                  );
                })}
            </div>
          </div>
        </ErrorBoundary>
      )}

      {/* Profitability Matrix */}
      {Object.keys(profitability_matrix).length > 0 && (
        <ErrorBoundary compact title="Profitability Matrix Error">
          <div className="bg-gray-900 p-6 rounded-lg border border-gray-800 overflow-x-auto">
            <h2 className="text-lg font-bold text-white mb-4">📊 Setup × Regime Profitability Matrix</h2>
            <table className="w-full text-sm min-w-[600px]">
              <caption className="sr-only">Setup and Regime Profitability Matrix</caption>
              <thead>
                <tr className="text-gray-400 border-b border-gray-700">
                  <th scope="col" className="text-left p-2">Setup</th>
                  <th scope="col" className="text-left p-2">Regime</th>
                  <th scope="col" className="text-right p-2">Trades</th>
                  <th scope="col" className="text-right p-2">Win Rate</th>
                  <th scope="col" className="text-right p-2">Avg PnL</th>
                  <th scope="col" className="text-right p-2">Sharpe</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(profitability_matrix).flatMap(([setup, regimes]) =>
                  Object.entries(regimes || {}).map(([regime, stats]) => {
                    const sWinRate = stats?.win_rate ?? 0;
                    const sAvgPnl = stats?.avg_pnl ?? 0;
                    const sSharpe = stats?.sharpe ?? 0;
                    const sCount = stats?.trade_count ?? 0;
                    return (
                      <tr key={`${setup}-${regime}`} className="border-b border-gray-800 hover:bg-gray-800/50">
                        <td className="p-2 text-white font-mono text-xs">{setup}</td>
                        <td className="p-2 text-gray-300 text-xs">{regime}</td>
                        <td className="p-2 text-right text-gray-300">{sCount}</td>
                        <td className={`p-2 text-right font-bold ${sCount === 0 ? 'text-gray-400' : sWinRate >= 0.5 ? 'text-emerald-400' : 'text-red-400'}`}>
                          {sCount === 0 ? '0%' : `${(sWinRate * 100).toFixed(0)}%`}
                        </td>
                        <td className={`p-2 text-right ${sCount === 0 ? 'text-gray-400' : sAvgPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                          {sCount === 0 ? '0.00%' : `${(sAvgPnl * 100).toFixed(2)}%`}
                        </td>
                        <td className="p-2 text-right text-blue-400">{sSharpe.toFixed(2)}</td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </ErrorBoundary>
      )}

      {/* Recent Trades */}
      {recent_trades.length > 0 && (
        <ErrorBoundary compact title="Recent Trades Error">
          <div className="bg-gray-900 p-6 rounded-lg border border-gray-800">
            <h2 className="text-lg font-bold text-white mb-4">📋 Recent Trades</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm min-w-[720px]">
                <caption className="sr-only">Recent simulated and paper trades</caption>
                <thead>
                  <tr className="text-gray-400 border-b border-gray-700">
                    <th scope="col" className="text-left p-2">Contract / Ticker</th>
                    <th scope="col" className="text-left p-2">Direction</th>
                    <th scope="col" className="text-left p-2">Exit Reason</th>
                    <th scope="col" className="text-right p-2">PnL %</th>
                    <th scope="col" className="text-right p-2">Bars</th>
                    <th scope="col" className="text-left p-2">Regime</th>
                  </tr>
                </thead>
                <tbody>
                  {recent_trades.map((trade, idx) => {
                    const pnl = trade.pnl_pct;
                    const dirUpper = String(trade.direction || '').toUpperCase();
                    const isLong = dirUpper === 'LONG' || dirUpper === 'BULLISH' || dirUpper === 'BUY';
                    const isShort = dirUpper === 'SHORT' || dirUpper === 'BEARISH' || dirUpper === 'SELL' || dirUpper.includes('SPREAD') || dirUpper.includes('WRITING');
                    const canonicalSymbol = formatContractSymbol(trade.ticker);
                    const lotSize = getExchangeLotSize(trade.ticker);
                    return (
                      <tr key={trade.trade_id || idx} className="border-b border-gray-800 hover:bg-gray-800/50">
                        <td className="p-2 text-white font-mono text-xs">
                          <div className="font-semibold">{canonicalSymbol}</div>
                          <div className="text-[10px] text-gray-400 font-sans">Lot: {lotSize}</div>
                        </td>
                        <td className="p-2 font-semibold">
                          <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-bold font-mono ${
                            isLong
                              ? 'bg-emerald-950 text-emerald-300 border border-emerald-800'
                              : isShort
                                ? 'bg-amber-950 text-amber-300 border border-amber-800'
                                : 'bg-red-950 text-red-300 border border-red-800'
                          }`}>
                            {trade.direction}
                          </span>
                        </td>
                        <td className="p-2 text-gray-300 text-xs">{trade.exit_reason || '—'}</td>
                        <td className={`p-2 text-right font-bold ${pnl == null ? 'text-gray-400' : pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                          {pnl == null ? '—' : `${pnl >= 0 ? '+' : ''}${Number(pnl).toFixed(2)}%`}
                        </td>
                        <td className="p-2 text-right text-gray-300">{trade.bars_held ?? '—'}</td>
                        <td className="p-2 text-gray-400 text-xs">{trade.regime || '—'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </ErrorBoundary>
      )}

      {/* Empty State */}
      {totalTrades === 0 && (
        <div className="bg-gray-900 p-8 sm:p-12 rounded-lg border border-gray-800 text-center">
          <p className="text-gray-300 text-lg font-semibold mb-2">No Trades in the AI Journal Yet</p>
          <p className="text-gray-400 text-sm max-w-lg mx-auto mb-6">
            Run the Historical Replay Engine to learn from past market cycles or start the Paper Trader to log live executions and regime adaptations.
          </p>
          <div className="flex flex-wrap gap-3 justify-center mb-6">
            <Link
              to="/training"
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold rounded-lg transition inline-flex items-center gap-1.5"
            >
              <Play className="w-3.5 h-3.5 fill-white" /> Start Paper Trader / Replay
            </Link>
            <Link
              to="/backtest"
              className="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 border border-gray-700 text-xs font-semibold rounded-lg transition inline-flex items-center gap-1.5"
            >
              <TrendingUp className="w-3.5 h-3.5" /> Run Setup Backtest
            </Link>
          </div>
          <p className="text-gray-500 text-xs font-mono bg-gray-950 p-2.5 rounded border border-gray-800 max-w-md mx-auto">
            python -m ml.replay_engine --ticker ^NSEI --period 5y
          </p>
        </div>
      )}
    </div>
  );
};

export default AIJournal;
