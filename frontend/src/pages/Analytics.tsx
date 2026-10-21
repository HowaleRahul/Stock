import { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';
import { createChart, ColorType, LineSeries } from 'lightweight-charts';
import type { Time } from 'lightweight-charts';
import { RefreshCw } from 'lucide-react';

interface AnalyticsData {
  win_rate?: number;
  total_trades?: number;
  probability_of_ruin?: number;
  equity_curve?: Array<{ time: number; value: number }>;
  win_by_day?: Record<string, number>;
}

const Analytics = () => {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);
  const abortRef = useRef<AbortController | null>(null);

  const fetchAnalytics = useCallback(async (isManual = false) => {
    if (abortRef.current) {
      abortRef.current.abort();
    }
    const controller = new AbortController();
    abortRef.current = controller;

    if (isManual) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(null);

    try {
      const res = await axios.get('/api/v1/dashboard/analytics', {
        signal: controller.signal,
      });
      setData(res.data);
    } catch (err: any) {
      if (axios.isCancel(err)) return;
      console.error('Failed to load analytics:', err);
      setError('Analytics are unavailable. Please check that the backend is running and retry.');
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    fetchAnalytics();
    return () => {
      if (abortRef.current) {
        abortRef.current.abort();
      }
    };
  }, [fetchAnalytics]);

  useEffect(() => {
    if (!loading && data && chartContainerRef.current) {
      const chart = createChart(chartContainerRef.current, {
        layout: {
          background: { type: ColorType.Solid, color: 'transparent' },
          textColor: '#68757a',
        },
        grid: {
          vertLines: { color: '#eeeae1' },
          horzLines: { color: '#eeeae1' },
        },
        rightPriceScale: { borderColor: '#dfdcd3' },
        timeScale: { borderColor: '#dfdcd3' },
        width: chartContainerRef.current.clientWidth,
        height: 400,
        localization: {
          priceFormatter: (val: number) => `₹${val.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`,
        },
      });

      const lineSeries = chart.addSeries(LineSeries, {
        color: '#2962FF',
        lineWidth: 2,
      });

      // Ensure unique, sorted times in O(N)
      const rawCurve = Array.isArray(data.equity_curve) ? data.equity_curve : [];
      const seenTimes = new Set<number>();
      const uniqueData = rawCurve
        .map(d => ({ time: Number(d.time) as Time, value: Number(d.value) }))
        .filter(d => {
          const t = d.time as number;
          if (!Number.isFinite(t) || !Number.isFinite(d.value)) return false;
          if (seenTimes.has(t)) return false;
          seenTimes.add(t);
          return true;
        })
        .sort((a, b) => (a.time as number) - (b.time as number));

      lineSeries.setData(uniqueData);
      chart.timeScale().fitContent();
      
      chartRef.current = chart;

      const handleResize = () => {
        if (chartContainerRef.current) {
          chart.applyOptions({ width: chartContainerRef.current.clientWidth });
        }
      };
      const resizeObserver = new ResizeObserver(handleResize);
      resizeObserver.observe(chartContainerRef.current);
      handleResize();
      
      return () => {
        resizeObserver.disconnect();
        chart.remove();
        if (chartRef.current === chart) {
          chartRef.current = null;
        }
      };
    }
  }, [data, loading]);

  if (loading && !data) return <div className="text-gray-400 p-8">Loading Analytics...</div>;
  if (error && !data) {
    return (
      <div className="state-panel" role="alert">
        <strong>{error}</strong>
        <button className="retry-button" onClick={() => fetchAnalytics()}>Retry connection</button>
      </div>
    );
  }

  const winRate = Number(data?.win_rate ?? 0);
  const totalTrades = Number(data?.total_trades ?? 0);
  const probRuin = Number(data?.probability_of_ruin ?? 0);
  const equityCurve = Array.isArray(data?.equity_curve) ? data.equity_curve : [];
  const winByDay = data?.win_by_day || {};
  const currentEquity = equityCurve.length > 0 ? equityCurve[equityCurve.length - 1].value : 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <span className="eyebrow">Performance surface / 03</span>
          <h2 className="text-2xl font-bold text-white">Risk & Analytics Dashboard</h2>
        </div>
        <button
          className="icon-button"
          onClick={() => fetchAnalytics(true)}
          disabled={loading || refreshing}
          aria-label="Refresh analytics"
          title="Refresh analytics"
        >
          <RefreshCw className={refreshing ? 'spin' : ''} />
        </button>
      </div>

      {error && (
        <div className="state-panel compact" role="alert">
          <strong>{error}</strong>
          <button className="retry-button" onClick={() => fetchAnalytics(true)}>Retry</button>
        </div>
      )}
      
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-gray-900 p-6 rounded-lg border border-gray-800">
          <p className="text-gray-400 text-sm">Overall Win Rate</p>
          <p className="text-3xl font-bold text-emerald-400">{winRate.toFixed(1)}%</p>
          <p className="text-sm text-gray-500 mt-2">Across {totalTrades} historical closed trades</p>
        </div>
        <div className="bg-gray-900 p-6 rounded-lg border border-gray-800">
          <p className="text-gray-400 text-sm">Probability of Ruin</p>
          <p className={`text-3xl font-bold ${probRuin > 30 ? 'text-red-400' : 'text-emerald-400'}`}>
            {probRuin.toFixed(1)}%
          </p>
          <p className="text-sm text-gray-500 mt-2">Risk model hitting 0 capital</p>
        </div>
        <div className="bg-gray-900 p-6 rounded-lg border border-gray-800">
          <p className="text-gray-400 text-sm">Current Equity</p>
          <p className="text-3xl font-bold text-blue-400">
            {currentEquity > 0 ? `₹${Number(currentEquity).toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—'}
          </p>
          <p className="text-sm text-gray-500 mt-2">Simulated portfolio equity balance</p>
        </div>
      </div>

      <div className="bg-gray-900 p-6 rounded-lg border border-gray-800">
        <h3 className="text-lg font-bold text-white mb-4">Equity Curve</h3>
        {equityCurve.length > 0 ? (
          <div ref={chartContainerRef} className="w-full" />
        ) : (
          <div className="text-gray-500 py-8 text-center">Not enough closed trades to plot an equity curve.</div>
        )}
      </div>

      {Object.keys(winByDay).length > 0 && (
        <div className="bg-gray-900 p-6 rounded-lg border border-gray-800">
          <h3 className="text-lg font-bold text-white mb-4">Win Rate by Day of Week</h3>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-4">
            {Object.entries(winByDay).map(([day, rate]) => {
              const numRate = Number(rate) || 0;
              return (
                <div key={day} className="bg-gray-800 p-4 rounded text-center">
                  <div className="text-gray-400 text-sm">{day}</div>
                  <div className="text-xl font-bold mt-1 text-blue-400">{numRate.toFixed(0)}%</div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};

export default Analytics;
