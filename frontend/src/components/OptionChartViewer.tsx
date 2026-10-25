import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import axios from 'axios';
import { createChart, CandlestickSeries, LineSeries, LineStyle } from 'lightweight-charts';
import type { Time } from 'lightweight-charts';
import {
  Zap,
  RefreshCw
} from 'lucide-react';
import { formatIndianCurrency } from '../utils/formatters';
import {
  getExchangeLotSize,
  formatContractSymbol,
  calculateOptionPayoffProfile,
} from '../utils/foUtils';

interface OptionChartProps {
  initialUnderlying?: string;
  initialStrike?: number;
  initialOptionType?: 'CE' | 'PE';
  initialAction?: 'BUY' | 'SELL';
  strategyType?: string;
  hedgeStrike?: number;
  hedgePrice?: number;
  netCredit?: number;
  entryPrice?: number;
  targetPrice?: number;
  stopLossPrice?: number;
  height?: number;
}

export const OptionChartViewer: React.FC<OptionChartProps> = ({
  initialUnderlying = 'NIFTY',
  initialStrike = 22800,
  initialOptionType = 'CE',
  initialAction,
  strategyType = 'DIRECTIONAL',
  hedgeStrike,
  hedgePrice,
  entryPrice,
  targetPrice,
  stopLossPrice,
  height = 360,
}) => {
  const [underlying, setUnderlying] = useState<string>(initialUnderlying);
  const [strike, setStrike] = useState<number>(initialStrike);
  const [optionType, setOptionType] = useState<'CE' | 'PE'>(initialOptionType);
  const [action, setAction] = useState<'BUY' | 'SELL'>(
    initialAction || (strategyType.toUpperCase().includes('CREDIT') || strategyType.toUpperCase().includes('WRITING') ? 'SELL' : 'BUY')
  );
  const [activeStrategy, setActiveStrategy] = useState<string>(strategyType);
  const [timeframe, setTimeframe] = useState<string>('1h');

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [chartData, setChartData] = useState<any>(null);
  const [candles, setCandles] = useState<any[]>([]);
  const [chartInstance, setChartInstance] = useState<any>(null);

  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);
  const candleSeriesRef = useRef<any>(null);
  const vwapSeriesRef = useRef<any>(null);
  const priceLinesRef = useRef<any[]>([]);
  const optionRequestRef = useRef<AbortController | null>(null);

  const fetchOptionData = useCallback(async (isManual = false) => {
    optionRequestRef.current?.abort();
    const controller = new AbortController();
    optionRequestRef.current = controller;
    if (isManual) setLoading(true);
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
        signal: controller.signal,
      });
      if (!controller.signal.aborted) {
        setChartData(res.data);
        if (Array.isArray(res.data?.candles)) {
          setCandles(res.data.candles);
        }
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        console.error('Unable to load option chart data.', error);
        setError('Option chart data currently unavailable.');
      }
    } finally {
      if (optionRequestRef.current === controller) {
        optionRequestRef.current = null;
        setLoading(false);
      }
    }
  }, [underlying, strike, optionType, timeframe]);

  useEffect(() => {
    let ignore = false;
    const controller = new AbortController();
    optionRequestRef.current = controller;

    axios.get('/api/v1/market/option-chart', {
      params: {
        underlying,
        strike,
        option_type: optionType,
        timeframe,
        limit: 100,
      },
      signal: controller.signal,
    }).then(res => {
      if (!ignore) {
        setChartData(res.data);
        if (Array.isArray(res.data?.candles)) {
          setCandles(res.data.candles);
        }
      }
    }).catch(err => {
      if (!ignore && !axios.isCancel(err)) {
        setError('Option chart data currently unavailable.');
      }
    });

    const interval = setInterval(() => { void fetchOptionData(false); }, 12000);
    return () => {
      ignore = true;
      clearInterval(interval);
      controller.abort();
    };
  }, [underlying, strike, optionType, timeframe, fetchOptionData]);

  // Live 2s Option Tick Loop: moves the option candle & Greeks in real time
  useEffect(() => {
    let isMounted = true;
    let tickController: AbortController | null = null;
    const fetchOptionTick = async () => {
      tickController?.abort();
      const controller = new AbortController();
      tickController = controller;
      try {
        const res = await axios.get('/api/v1/market/option-tick', {
          params: { underlying, strike, option_type: optionType },
          signal: controller.signal,
        });
        if (!isMounted || controller.signal.aborted || !res.data) return;

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
        if (candleSeriesRef.current && candles.length > 0) {
          const lastCandle = candles[candles.length - 1];
          const newHigh = Math.max(lastCandle.high, res.data.premium);
          const newLow = Math.min(lastCandle.low, res.data.premium);
          const candleTime = (typeof lastCandle.time === 'number' && lastCandle.time < 2000000000
            ? lastCandle.time
            : new Date(lastCandle.time).getTime() / 1000) as Time;
          candleSeriesRef.current.update({
            time: candleTime,
            open: lastCandle.open,
            high: newHigh,
            low: newLow,
            close: res.data.premium,
          });
        }
      } catch (error) {
        if (isMounted && !controller.signal.aborted) {
          console.warn('Unable to refresh live option tick.', error);
        }
      }
    };

    const tickInterval = setInterval(fetchOptionTick, 2000);
    return () => {
      isMounted = false;
      tickController?.abort();
      clearInterval(tickInterval);
    };
  }, [underlying, strike, optionType, candles]);


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
    setChartInstance(chart);

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
      priceLinesRef.current = [];
      setChartInstance(null);
    };
  }, [height]);

  // Update chart series data
  useEffect(() => {
    const candleSeries = candleSeriesRef.current;
    if (!candleSeries || !chartInstance || !candles || candles.length === 0) return;

    const formattedCandles = candles.map((c: any) => ({
      time: (typeof c.time === 'number' && c.time < 2000000000 ? c.time : new Date(c.time).getTime() / 1000) as Time,
      open: Number(c.open),
      high: Number(c.high),
      low: Number(c.low),
      close: Number(c.close),
    }));

    const formattedVwap = candles.map((c: any) => ({
      time: (typeof c.time === 'number' && c.time < 2000000000 ? c.time : new Date(c.time).getTime() / 1000) as Time,
      value: Number(c.vwap || c.close),
    }));

    candleSeries.setData(formattedCandles);
    if (vwapSeriesRef.current) {
      vwapSeriesRef.current.setData(formattedVwap);
    }
  }, [candles, chartInstance]);

  const lotSize = chartData?.lot_size || getExchangeLotSize(underlying);
  const contractTitle = formatContractSymbol(underlying, strike, optionType);
  const intervalStep = (underlying === 'BANKNIFTY' || underlying === 'SENSEX') ? 100 : (underlying === 'MIDCPNIFTY' ? 25 : 50);

  const payoff = useMemo(() => {
    return calculateOptionPayoffProfile({
      underlying,
      strike,
      optionType,
      entryPrice: entryPrice || Number(chartData?.current_premium) || 120,
      currentSpot: chartData?.current_spot,
      action,
      strategyType: activeStrategy,
      hedgeStrike,
      hedgePrice,
      lotSize,
      rawTheta: chartData?.greeks?.theta,
    });
  }, [underlying, strike, optionType, entryPrice, chartData?.current_premium, chartData?.current_spot, chartData?.greeks?.theta, action, activeStrategy, hedgeStrike, hedgePrice, lotSize]);

  useEffect(() => {
    const candleSeries = candleSeriesRef.current;
    if (!candleSeries) return;
    priceLinesRef.current.forEach(line => candleSeries.removePriceLine(line));
    priceLinesRef.current = [
      { price: entryPrice, color: '#60a5fa', title: 'Entry' },
      { price: targetPrice, color: '#34d399', title: action === 'SELL' ? 'Target (Decay)' : 'Target' },
      { price: stopLossPrice, color: '#f87171', title: 'Stop Loss' },
      { price: payoff.breakeven, color: '#f59e0b', title: `BE ₹${payoff.breakeven}` },
    ]
      .filter((level): level is { price: number; color: string; title: string } =>
        typeof level.price === 'number' && Number.isFinite(level.price) && level.price > 0
      )
      .map(level => candleSeries.createPriceLine({
        price: level.price,
        color: level.color,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: level.title,
      }));
  }, [entryPrice, targetPrice, stopLossPrice, payoff.breakeven, action, height]);

  return (
    <div className="bg-gray-950 rounded-xl border border-gray-800 p-4 shadow-xl">
      {/* Header & Contract Switcher */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-800 pb-3 mb-3">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-purple-950 border border-purple-800 flex items-center justify-center text-purple-400">
            <Zap className="w-4 h-4" />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-base font-bold text-white tracking-wide font-mono">
                {contractTitle}
              </h3>
              <span className={`text-[10px] px-2 py-0.5 rounded font-bold ${
                optionType === 'CE' ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : 'bg-red-950 text-red-400 border border-red-800'
              }`}>
                {optionType === 'CE' ? 'CALL OPTION (CE)' : 'PUT OPTION (PE)'}
              </span>
              <span className={`text-[10px] px-2 py-0.5 rounded font-bold uppercase transition-colors ${
                action === 'SELL'
                  ? 'bg-amber-950/90 text-amber-300 border border-amber-700/80 shadow-sm'
                  : 'bg-blue-950/90 text-blue-300 border border-blue-700/80'
              }`}>
                {action === 'SELL' ? 'SHORT / SELL' : 'LONG / BUY'}
              </span>
              {payoff.isCredit && (
                <span className="text-[10px] px-2 py-0.5 rounded font-bold bg-rose-950/80 text-rose-300 border border-rose-700/80 uppercase">
                  {payoff.strategyName}
                </span>
              )}
            </div>
            <div className="text-xs text-gray-400 mt-0.5">
              Spot: <span className="text-white font-mono">{formatIndianCurrency(chartData?.current_spot || 0)}</span> | 
              Lot: <span className="text-white font-mono">{lotSize} Qty</span> | 
              Mode: <span className={action === 'SELL' ? 'text-amber-300 font-bold' : 'text-blue-300 font-bold'}>{action === 'SELL' ? 'Option Writing / Spread' : 'Option Buying'}</span>
            </div>
          </div>
        </div>

        {/* Live Premium & VWAP Indicator */}
        <div className="flex items-center gap-4">
          <div className="text-right">
            <span className="text-[11px] text-gray-400 block">{action === 'SELL' ? 'Net Credit LTP' : 'Premium LTP'}</span>
            <div className="text-lg font-mono font-bold text-emerald-400 flex items-center justify-end gap-1">
              {formatIndianCurrency(chartData?.current_premium || 0)}
            </div>
          </div>

          <div className="text-right">
            <span className="text-[11px] text-gray-400 block">Option VWAP</span>
            <div className={`text-base font-mono font-bold ${
              chartData?.indicators?.is_above_vwap ? 'text-amber-400' : 'text-gray-400'
            }`}>
              {formatIndianCurrency(chartData?.indicators?.vwap || 0)}
            </div>
          </div>

          <button
            type="button"
            onClick={() => void fetchOptionData(true)}
            aria-label="Refresh option chart"
            className="p-2 rounded-lg bg-gray-900 border border-gray-800 text-gray-400 hover:text-white"
            title="Refresh option chart"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Strike & Parameter Selection Bar */}
      <div className="flex flex-wrap items-center justify-between gap-2.5 mb-3 text-xs bg-gray-900/60 p-2.5 rounded-lg border border-gray-800/80">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-gray-400 font-semibold">Underlying:</span>
          {[
            { id: 'NIFTY', defaultStrike: 24500 },
            { id: 'BANKNIFTY', defaultStrike: 52000 },
            { id: 'SENSEX', defaultStrike: 80000 },
            { id: 'FINNIFTY', defaultStrike: 23500 },
            { id: 'MIDCPNIFTY', defaultStrike: 12500 },
          ].map(u => (
            <button
              key={u.id}
              type="button"
              onClick={() => {
                setUnderlying(u.id);
                setStrike(u.defaultStrike);
              }}
              className={`px-2.5 py-1 rounded text-[11px] font-bold border transition-colors ${
                underlying === u.id
                  ? 'bg-blue-600 border-blue-500 text-white shadow'
                  : 'bg-gray-800 border-gray-700 text-gray-300 hover:border-gray-600'
              }`}
            >
              {u.id}
            </button>
          ))}
        </div>

        {/* Action Toggle (BUY vs SELL / Credit Spread) */}
        <div className="flex items-center gap-1.5 bg-gray-950/80 p-1 rounded-md border border-gray-800">
          <span className="text-gray-400 font-semibold text-[11px] px-1">Action:</span>
          <button
            type="button"
            onClick={() => {
              setAction('BUY');
              setActiveStrategy('DIRECTIONAL');
            }}
            className={`px-2.5 py-1 rounded text-[11px] font-bold border transition-colors ${
              action === 'BUY'
                ? 'bg-blue-600 border-blue-500 text-white shadow-sm'
                : 'bg-gray-800 border-gray-700 text-gray-300 hover:text-white'
            }`}
          >
            BUY (Long)
          </button>
          <button
            type="button"
            onClick={() => {
              setAction('SELL');
              setActiveStrategy(optionType === 'PE' ? 'BULL_PUT_SPREAD' : 'BEAR_CALL_SPREAD');
            }}
            className={`px-2.5 py-1 rounded text-[11px] font-bold border transition-colors ${
              action === 'SELL'
                ? 'bg-amber-600 border-amber-500 text-white shadow-sm'
                : 'bg-gray-800 border-gray-700 text-gray-300 hover:text-white'
            }`}
          >
            SELL / SHORT (Credit)
          </button>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-gray-400 font-semibold">Type:</span>
          <button
            type="button"
            onClick={() => setOptionType('CE')}
            className={`px-2.5 py-1 rounded text-[11px] font-bold border transition-colors ${
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
            className={`px-2.5 py-1 rounded text-[11px] font-bold border transition-colors ${
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

      {/* Accurate Breakeven and Payoff Representation Card */}
      <div className="mb-3 p-3 bg-gray-900/90 rounded-lg border border-gray-800 text-xs font-mono">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-gray-400 uppercase text-[10px] font-bold">Breakeven Spot:</span>
            <span className="text-amber-400 font-bold text-sm bg-gray-950 px-2 py-0.5 rounded border border-gray-800">
              ₹{payoff.breakeven.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
            </span>
            <span className="text-[10px] text-gray-400">
              ({payoff.safetyBufferPct}% {optionType === 'CE' ? 'below ceiling' : 'cushion to spot'})
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-4">
            <div>
              <span className="text-gray-400 uppercase text-[10px] mr-1">
                {action === 'SELL' ? 'Max Profit (Net Credit):' : 'Max Profit:'}
              </span>
              <span className="text-emerald-400 font-bold text-xs">
                +{formatIndianCurrency(payoff.maxProfit)}
              </span>
            </div>
            <div>
              <span className="text-gray-400 uppercase text-[10px] mr-1">
                {action === 'SELL' && activeStrategy.includes('SPREAD') ? 'Max Risk (Spread Width - Credit):' : 'Max Risk:'}
              </span>
              <span className="text-red-400 font-bold text-xs">
                -{formatIndianCurrency(payoff.maxLoss)}
              </span>
            </div>
            {payoff.riskRewardRatio != null && (
              <div>
                <span className="text-gray-400 uppercase text-[10px] mr-1">R:R:</span>
                <span className="text-blue-400 font-bold text-xs">1:{payoff.riskRewardRatio}</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Real-Time Option Greeks Bar (Full 5 Greeks + Margin vs Premium Labels) */}
      {chartData?.greeks && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 mb-3 text-xs font-mono">
          <div className="p-2 rounded bg-gray-900/80 border border-gray-800 text-center">
            <span className="text-[10px] text-gray-400 block uppercase">Delta (Δ)</span>
            <span className="text-emerald-400 font-bold">{Number(chartData.greeks.delta || 0.5).toFixed(3)}</span>
          </div>

          {/* Positive Theta notation for sellers (+₹Theta/day representing time decay profit) */}
          <div className="p-2 rounded bg-gray-900/80 border border-gray-800 text-center">
            <span className={`text-[10px] block uppercase font-bold ${action === 'SELL' ? 'text-emerald-400' : 'text-gray-400'}`}>
              {action === 'SELL' ? 'Theta Gain (Θ)' : 'Theta Decay (Θ)'}
            </span>
            <span className={`font-bold ${action === 'SELL' ? 'text-emerald-400' : 'text-red-400'}`}>
              {payoff.thetaFormatted}
            </span>
            <span className="text-[9px] text-gray-400 block">
              {action === 'SELL' ? 'Decay income' : 'Decay cost'}
            </span>
          </div>

          <div className="p-2 rounded bg-gray-900/80 border border-gray-800 text-center">
            <span className="text-[10px] text-gray-400 block uppercase">Gamma (Γ)</span>
            <span className="text-blue-400 font-bold">{Number(chartData.greeks.gamma || 0.0012).toFixed(4)}</span>
          </div>
          <div className="p-2 rounded bg-gray-900/80 border border-gray-800 text-center">
            <span className="text-[10px] text-gray-400 block uppercase">Vega (ν)</span>
            <span className="text-amber-400 font-bold">
              {formatIndianCurrency(chartData.greeks.vega || 14.20)} / 1% IV
            </span>
          </div>
          <div className="p-2 rounded bg-gray-900/80 border border-gray-800 text-center">
            <span className="text-[10px] text-gray-400 block uppercase">Implied Vol (IV)</span>
            <span className="text-purple-400 font-bold">{Number(chartData.greeks.iv || 15.2).toFixed(1)}%</span>
          </div>

          {/* Margin vs Premium Block */}
          <div className="p-2 rounded bg-gray-900/80 border border-gray-800 text-center">
            <span className="text-[10px] text-amber-400 block uppercase font-bold">
              {action === 'SELL' ? 'Margin Req (1L)' : '1 Lot Premium'}
            </span>
            <span className="text-white font-bold">
              {formatIndianCurrency(action === 'SELL' ? payoff.marginEstimated : (chartData.current_premium || 0) * lotSize)}
            </span>
            <span className={`text-[9px] block ${action === 'SELL' ? 'text-emerald-400 font-semibold' : 'text-gray-400'}`}>
              {action === 'SELL' ? `+${formatIndianCurrency((chartData.current_premium || 0) * lotSize)} Credit` : `${lotSize} Qty Outlay`}
            </span>
          </div>
        </div>
      )}

      {/* Main Lightweight Option Candlestick Chart */}
      {error && (
        <div className="mb-3 flex items-center justify-between gap-3 rounded-lg border border-red-800 bg-red-950/50 p-3 text-sm text-red-200" role="alert">
          <span>{error}</span>
          <button type="button" onClick={() => void fetchOptionData(true)} className="shrink-0 underline">
            Retry
          </button>
        </div>
      )}
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
