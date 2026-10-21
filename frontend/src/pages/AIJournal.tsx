import { useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';
import { RefreshCw } from 'lucide-react';

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
    fetchJournal();
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [fetchJournal]);

  if (loading && !data) return <div className="text-gray-400 p-8">Loading AI Journal...</div>;
  if (error && !data) return (
    <div className="state-panel" role="alert">
      <strong>{error}</strong>
      <button className="retry-button" onClick={() => fetchJournal()}>Retry connection</button>
    </div>
  );
  if (!data) return <div className="text-gray-400 p-8">No data available.</div>;

  const summary = data.summary || {};
  const insights = Array.isArray(data.insights) ? data.insights : [];
  const profitability_matrix = data.profitability_matrix || {};
  const rl_weights = data.rl_weights || {};
  const rl_diagnostics = data.rl_diagnostics || {};
  const recent_trades = Array.isArray(data.recent_trades) ? data.recent_trades : [];

  const totalTrades = summary.total_trades ?? 0;
  const winRate = summary.win_rate ?? 0;
  const totalCashPnl = summary.total_cash_pnl ?? 0;
  const avgPnlPct = summary.avg_pnl_pct ?? 0;
  const sharpeRatio = summary.sharpe_ratio ?? 0;
  const maxDrawdownPct = summary.max_drawdown_pct ?? 0;

  const formatUpdateDate = (dateStr?: string) => {
    if (!dateStr) return 'Never';
    const parsed = new Date(dateStr);
    return isNaN(parsed.getTime()) ? 'Never' : parsed.toLocaleString();
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">🧠 AI Self-Play Journal</h2>
          <div className="text-sm text-gray-500 mt-1">
            RL Version: {rl_diagnostics.version ?? 0} | Last Update: {formatUpdateDate(rl_diagnostics.last_update)}
          </div>
        </div>
        <button
          className="icon-button"
          onClick={() => fetchJournal(true)}
          disabled={loading || refreshing}
          aria-label="Refresh AI Journal"
          title="Refresh AI Journal"
        >
          <RefreshCw className={refreshing ? 'spin' : ''} />
        </button>
      </div>

      {error && (
        <div className="state-panel compact" role="alert">
          <strong>{error}</strong>
          <button className="retry-button" onClick={() => fetchJournal(true)}>Retry</button>
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <div className="bg-gray-900 p-4 rounded-lg border border-gray-800">
          <p className="text-gray-400 text-xs">Total Trades</p>
          <p className="text-2xl font-bold text-white">{totalTrades}</p>
        </div>
        <div className="bg-gray-900 p-4 rounded-lg border border-gray-800">
          <p className="text-gray-400 text-xs">Win Rate</p>
          <p className={`text-2xl font-bold ${winRate >= 0.5 ? 'text-emerald-400' : 'text-red-400'}`}>
            {(winRate * 100).toFixed(1)}%
          </p>
        </div>
        <div className="bg-gray-900 p-4 rounded-lg border border-gray-800">
          <p className="text-gray-400 text-xs">Total P&L</p>
          <p className={`text-2xl font-bold ${totalCashPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
            ₹{Number(totalCashPnl).toLocaleString('en-IN', { maximumFractionDigits: 2 })}
          </p>
        </div>
        <div className="bg-gray-900 p-4 rounded-lg border border-gray-800">
          <p className="text-gray-400 text-xs">Avg PnL</p>
          <p className={`text-2xl font-bold ${avgPnlPct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
            {avgPnlPct.toFixed(2)}%
          </p>
        </div>
        <div className="bg-gray-900 p-4 rounded-lg border border-gray-800">
          <p className="text-gray-400 text-xs">Sharpe Ratio</p>
          <p className="text-2xl font-bold text-blue-400">{sharpeRatio.toFixed(2)}</p>
        </div>
        <div className="bg-gray-900 p-4 rounded-lg border border-gray-800">
          <p className="text-gray-400 text-xs">Max Drawdown</p>
          <p className="text-2xl font-bold text-red-400">-{Math.abs(maxDrawdownPct).toFixed(1)}%</p>
        </div>
      </div>

      {/* AI Insights */}
      {insights.length > 0 && (
        <div className="bg-gray-900 p-6 rounded-lg border border-gray-800">
          <h3 className="text-lg font-bold text-white mb-4">🔍 AI Self-Review Insights</h3>
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
      )}

      {/* Setup Scorecard (RL Weights) */}
      {Object.keys(rl_weights).length > 0 && (
        <div className="bg-gray-900 p-6 rounded-lg border border-gray-800">
          <h3 className="text-lg font-bold text-white mb-4">⚖️ Setup Scorecard (RL-Learned Weights)</h3>
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
      )}

      {/* Profitability Matrix */}
      {Object.keys(profitability_matrix).length > 0 && (
        <div className="bg-gray-900 p-6 rounded-lg border border-gray-800 overflow-x-auto">
          <h3 className="text-lg font-bold text-white mb-4">📊 Setup × Regime Profitability Matrix</h3>
          <table className="w-full text-sm">
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
                      <td className={`p-2 text-right font-bold ${sWinRate >= 0.5 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {(sWinRate * 100).toFixed(0)}%
                      </td>
                      <td className={`p-2 text-right ${sAvgPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {(sAvgPnl * 100).toFixed(2)}%
                      </td>
                      <td className="p-2 text-right text-blue-400">{sSharpe.toFixed(2)}</td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Recent Trades */}
      {recent_trades.length > 0 && (
        <div className="bg-gray-900 p-6 rounded-lg border border-gray-800">
          <h3 className="text-lg font-bold text-white mb-4">📋 Recent Trades</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">Recent simulated and paper trades</caption>
              <thead>
                <tr className="text-gray-400 border-b border-gray-700">
                  <th scope="col" className="text-left p-2">Ticker</th>
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
                  const isLong = String(trade.direction).toUpperCase() === 'LONG' || String(trade.direction).toUpperCase() === 'BULLISH';
                  return (
                    <tr key={trade.trade_id || idx} className="border-b border-gray-800 hover:bg-gray-800/50">
                      <td className="p-2 text-white font-mono text-xs">{trade.ticker}</td>
                      <td className={`p-2 ${isLong ? 'text-emerald-400' : 'text-red-400'}`}>
                        {trade.direction}
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
      )}

      {/* Empty State */}
      {totalTrades === 0 && (
        <div className="bg-gray-900 p-12 rounded-lg border border-gray-800 text-center">
          <p className="text-gray-400 text-lg mb-2">No trades in the journal yet.</p>
          <p className="text-gray-500 text-sm">
            Run the Historical Replay Engine or start the Paper Trader to generate trade data.
          </p>
          <p className="text-gray-600 text-xs mt-4 font-mono">
            python -m ml.replay_engine --ticker ^NSEI --period 5y
          </p>
        </div>
      )}
    </div>
  );
};

export default AIJournal;
