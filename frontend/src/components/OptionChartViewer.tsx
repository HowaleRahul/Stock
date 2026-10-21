import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { createChart, CandlestickSeries, LineSeries } from 'lightweight-charts';
import type { Time } from 'lightweight-charts';
import {
  TrendingUp,
  Activity,
  Layers,
  Zap,
  Percent,
  RefreshCw,
  Compass,
  ArrowUpRight,
  ArrowDownRight
} from 'lucide-react';

interface OptionChartProps {
  initialUnderlying?: string;
  initialStrike?: number;
  initialOptionType?: 'CE' | 'PE';
  entryPrice?: number;
  targetPrice?: number;
  stopLossPrice?: number;
  height?: number;
}

export const OptionChartViewer: React.FC<OptionChartProps> = ({
  initialUnderlying = 'NIFTY',
  initialStrike = 22800,
  initialOptionType = 'CE',
  entryPrice,
  targetPrice,
  stopLossPrice,
  height = 360,
}) => {
  const [underlying, setUnderlying] = useState<string>(initialUnderlying);
  const [strike, setStrike] = useState<number>(initialStrike);
  const [optionType, setOptionType] = useState<'CE' | 'PE'>(initialOptionType);
  const [timeframe, setTimeframe] = useState<string>('1h');

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [chartData, setChartData] = useState<any>(null);

  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);
  const candleSeriesRef = useRef<any>(null);
  const vwapSeriesRef = useRef<any>(null);

  // Sync state if props change
  useEffect(() => {
    if (initialUnderlying) setUnderlying(initialUnderlying);
    if (initialStrike) setStrike(initialStrike);
    if (initialOptionType) setOptionType(initialOptionType);
  }, [initialUnderlying, initialStrike, initialOptionType]);

  const fetchOptionData = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axios.get('/api/v1/market/option-chart', {
        params: {
          underlying,
          strike,
          option_type: optionType,
          timeframe,
          limit: 100,
        },
      });
      setChartData(res.data);
    } catch {
      setError('Option chart data currently unavailable.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchOptionData();
    const interval = setInterval(fetchOptionData, 12000); // 12s full candle history refresh
    return () => clearInterval(interval);
  }, [underlying, strike, optionType, timeframe]);

  // Live 2s Option Tick Loop: moves the option candle & Greeks in real time
  useEffect(() => {
    let isMounted = true;
    const fetchOptionTick = async () => {
      try {
        const res = await axios.get('/api/v1/market/option-tick', {
          params: { underlying, strike, option_type: optionType }
        });
        if (!isMounted || !res.data) return;

        // Update live Greeks and indicators in chartData state
        setChartData((prev: any) => {
          if (!prev) return prev;
          return {
            ...prev,
            current_premium: res.data.premium,
            greeks: {
              delta: res.data.delta,
              theta: res.data.theta,
              gamma: res.data.gamma,
              vega: res.data.vega,
              iv: res.data.iv,
            }
          };
        });

        // Update last candlestick in lightweight charts
        if (candleSeriesRef.current && chartData?.candles && chartData.candles.length > 0) {
          const lastCandle = chartData.candles[chartData.candles.length - 1];
          const newHigh = Math.max(lastCandle.high, res.data.premium);
          const newLow = Math.min(lastCandle.low, res.data.premium);
          const candleTime = (new Date(lastCandle.time).getTime() / 1000) as Time;
          candleSeriesRef.current.update({
            time: candleTime,
            open: lastCandle.open,
            high: newHigh,
            low: newLow,
            close: res.data.premium,
          });
        }
      } catch {
        // Silently ignore tick timeout
      }
    };

    const tickInterval = setInterval(fetchOptionTick, 2000);
    return () => {
      isMounted = false;
      clearInterval(tickInterval);
    };
  }, [underlying, strike, optionType, chartData?.candles]);


  // Setup lightweight-chart
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      height,
      layout: {
        background: { color: '#090d16' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: '#1e293b55' },
        horzLines: { color: '#1e293b55' },
      },
      rightPriceScale: {
        borderColor: '#334155',
        scaleMargins: { top: 0.1, bottom: 0.15 },
      },
      timeScale: {
        borderColor: '#334155',
        timeVisible: true,
      },
      localization: {
        priceFormatter: (price: number) => `₹${price.toFixed(2)}`,
      },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981',
      downColor: '#ef4444',
      borderVisible: false,
      wickUpColor: '#10b981',
      wickDownColor: '#ef4444',
    });

    const vwapSeries = chart.addSeries(LineSeries, {
      color: '#f59e0b',
      lineWidth: 2,
      lineStyle: 2, // Dashed
      title: 'Option VWAP',
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    vwapSeriesRef.current = vwapSeries;

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };
    const observer = new ResizeObserver(handleResize);
    observer.observe(chartContainerRef.current);
    handleResize();

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      vwapSeriesRef.current = null;
    };
  }, [height]);

  // Update chart series data
  useEffect(() => {
    if (!candleSeriesRef.current || !chartData?.candles) return;

    const formattedCandles = chartData.candles.map((c: any) => ({
      time: (new Date(c.time).getTime() / 1000) as Time,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));

    const formattedVwap = chartData.candles.map((c: any) => ({
      time: (new Date(c.time).getTime() / 1000) as Time,
      value: c.vwap,
    }));

    candleSeriesRef.current.setData(formattedCandles);
    if (vwapSeriesRef.current) {
      vwapSeriesRef.current.setData(formattedVwap);
    }
  }, [chartData]);

  const intervalStep = underlying === 'BANKNIFTY' ? 100 : 50;

  return (
    <div className="bg-gray-950 rounded-xl border border-gray-800 p-4 shadow-xl">
      {/* Header & Contract Switcher */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-800 pb-3 mb-3">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-purple-950 border border-purple-800 flex items-center justify-center text-purple-400">
            <Zap className="w-4 h-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-base font-bold text-white tracking-wide font-mono">
                {chartData?.option_symbol || `${underlying} ${strike} ${optionType}`}
              </h3>
              <span className={`text-[10px] px-2 py-0.5 rounded font-bold ${
                optionType === 'CE' ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : 'bg-red-950 text-red-400 border border-red-800'
              }`}>
                {optionType === 'CE' ? 'CALL OPTION (CE)' : 'PUT OPTION (PE)'}
              </span>
            </div>
            <div className="text-xs text-gray-400 mt-0.5">
              Spot: <span className="text-white font-mono">₹{chartData?.current_spot || '—'}</span> | 
              Lot: <span className="text-white font-mono">{chartData?.lot_size || 25}</span>
            </div>
          </div>
        </div>

        {/* Live Premium & VWAP Indicator */}
        <div className="flex items-center gap-4">
          <div className="text-right">
            <span className="text-[11px] text-gray-400 block">Premium LTP</span>
            <div className="text-lg font-mono font-bold text-emerald-400 flex items-center justify-end gap-1">
              ₹{chartData?.current_premium?.toFixed(2) || '0.00'}
            </div>
          </div>

          <div className="text-right">
            <span className="text-[11px] text-gray-400 block">Option VWAP</span>
            <div className={`text-base font-mono font-bold ${
              chartData?.indicators?.is_above_vwap ? 'text-amber-400' : 'text-gray-400'
            }`}>
              ₹{chartData?.indicators?.vwap?.toFixed(2) || '0.00'}
            </div>
          </div>

          <button
            type="button"
            onClick={fetchOptionData}
            className="p-2 rounded-lg bg-gray-900 border border-gray-800 text-gray-400 hover:text-white"
            title="Refresh option chart"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Strike & Parameter Selection Bar */}
      <div className="flex flex-wrap items-center justify-between gap-2.5 mb-3 text-xs bg-gray-900/60 p-2.5 rounded-lg border border-gray-800/80">
        <div className="flex items-center gap-2">
          <span className="text-gray-400 font-semibold">Underlying:</span>
          {['NIFTY', 'BANKNIFTY', 'FINNIFTY'].map(u => (
            <button
              key={u}
              type="button"
              onClick={() => {
                setUnderlying(u);
                setStrike(u === 'BANKNIFTY' ? 55000 : 22800);
              }}
              className={`px-2.5 py-1 rounded text-[11px] font-bold border ${
                underlying === u
                  ? 'bg-blue-600 border-blue-500 text-white'
                  : 'bg-gray-800 border-gray-700 text-gray-300 hover:border-gray-600'
              }`}
            >
              {u}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <span className="text-gray-400 font-semibold">Type:</span>
          <button
            type="button"
            onClick={() => setOptionType('CE')}
            className={`px-2.5 py-1 rounded text-[11px] font-bold border ${
              optionType === 'CE'
                ? 'bg-emerald-600 border-emerald-500 text-white'
                : 'bg-gray-800 border-gray-700 text-gray-300'
            }`}
          >
            CE (Calls)
          </button>
          <button
            type="button"
            onClick={() => setOptionType('PE')}
            className={`px-2.5 py-1 rounded text-[11px] font-bold border ${
              optionType === 'PE'
                ? 'bg-red-600 border-red-500 text-white'
                : 'bg-gray-800 border-gray-700 text-gray-300'
            }`}
          >
            PE (Puts)
          </button>
        </div>

        {/* Quick Strike Adjusters */}
        <div className="flex items-center gap-1.5">
          <span className="text-gray-400 font-semibold mr-1">Strike:</span>
          <button
            type="button"
            onClick={() => setStrike(s => s - intervalStep)}
            className="px-2 py-0.5 rounded bg-gray-800 border border-gray-700 text-white hover:bg-gray-700 font-mono text-xs"
          >
            -{intervalStep}
          </button>
          <span className="font-mono font-bold text-white px-2 py-0.5 bg-gray-950 rounded border border-gray-800">
            {strike}
          </span>
          <button
            type="button"
            onClick={() => setStrike(s => s + intervalStep)}
            className="px-2 py-0.5 rounded bg-gray-800 border border-gray-700 text-white hover:bg-gray-700 font-mono text-xs"
          >
            +{intervalStep}
          </button>
        </div>

        <div className="flex items-center gap-1.5 ml-auto">
          {['5m', '15m', '1h', '1d'].map(tf => (
            <button
              key={tf}
              type="button"
              onClick={() => setTimeframe(tf)}
              className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                timeframe === tf ? 'bg-purple-600 text-white' : 'text-gray-400 hover:text-white'
              }`}
            >
              {tf.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {/* Real-Time Option Greeks Bar */}
      {chartData?.greeks && (
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-2.5 mb-3 text-xs font-mono">
          <div className="p-2 rounded bg-gray-900/80 border border-gray-800 text-center">
            <span className="text-[10px] text-gray-400 block uppercase">Delta (Δ)</span>
            <span className="text-emerald-400 font-bold">{chartData.greeks.delta}</span>
          </div>
          <div className="p-2 rounded bg-gray-900/80 border border-gray-800 text-center">
            <span className="text-[10px] text-gray-400 block uppercase">Theta Decay (Θ)</span>
            <span className="text-red-400 font-bold">₹{chartData.greeks.theta}/day</span>
          </div>
          <div className="p-2 rounded bg-gray-900/80 border border-gray-800 text-center">
            <span className="text-[10px] text-gray-400 block uppercase">Gamma (Γ)</span>
            <span className="text-blue-400 font-bold">{chartData.greeks.gamma}</span>
          </div>
          <div className="p-2 rounded bg-gray-900/80 border border-gray-800 text-center">
            <span className="text-[10px] text-gray-400 block uppercase">Implied Vol (IV)</span>
            <span className="text-purple-400 font-bold">{chartData.greeks.iv}%</span>
          </div>
          <div className="p-2 rounded bg-gray-900/80 border border-gray-800 text-center">
            <span className="text-[10px] text-gray-400 block uppercase">1 Lot Premium Cost</span>
            <span className="text-white font-bold">
              ₹{((chartData.current_premium || 0) * (chartData.lot_size || 25)).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
            </span>
          </div>
        </div>
      )}

      {/* Main Lightweight Option Candlestick Chart */}
      <div className="relative">
        <div ref={chartContainerRef} className="w-full rounded-lg overflow-hidden border border-gray-800/80" />
        {loading && (
          <div className="absolute inset-0 bg-gray-950/60 backdrop-blur-sm flex items-center justify-center text-xs text-gray-300">
            <RefreshCw className="w-4 h-4 animate-spin mr-2 text-purple-400" /> Calculating Black-Scholes Option Candlesticks...
          </div>
        )}
      </div>

      <div className="flex items-center justify-between text-[11px] text-gray-500 mt-2 px-1">
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-0.5 bg-amber-400 inline-block" /> Intraday Option VWAP Benchmark Line
        </span>
        <span>
          High: ₹{chartData?.indicators?.day_high?.toFixed(2) || '—'} | Low: ₹{chartData?.indicators?.day_low?.toFixed(2) || '—'}
        </span>
      </div>
    </div>
  );
};

export default OptionChartViewer;
