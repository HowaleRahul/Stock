import React, { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { CandlestickSeries, createChart, createSeriesMarkers } from 'lightweight-charts';
import type { Time } from 'lightweight-charts';

interface ChartWidgetProps {
  data: any[];
  trades?: any[];
  height?: number;
  ticker?: string;
  timeframe?: string;
}

const ChartWidget: React.FC<ChartWidgetProps> = ({
  data,
  trades = [],
  height = 400,
  ticker,
  timeframe = '1h'
}) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);
  const seriesRef = useRef<any>(null);
  const markersRef = useRef<any>(null);
  const [chartInstance, setChartInstance] = useState<any>(null);

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
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      timeScale: {
        borderColor: '#334155',
        timeVisible: true,
      },
      localization: {
        priceFormatter: (price: number) => `₹${price.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`,
      },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981',
      downColor: '#ef4444',
      borderVisible: false,
      wickUpColor: '#10b981',
      wickDownColor: '#ef4444',
    });

    chartRef.current = chart;
    seriesRef.current = candleSeries;
    markersRef.current = createSeriesMarkers(candleSeries, []);
    setChartInstance(chart);

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
      try {
        if (typeof markersRef.current?.detach === 'function') {
          markersRef.current.detach();
        }
        chart.remove();
      } catch (err) {
        console.warn('Error cleaning up chart instance:', err);
      }
      chartRef.current = null;
      seriesRef.current = null;
      markersRef.current = null;
      setChartInstance(null);
    };
  }, [height]);

  useEffect(() => {
    if (!seriesRef.current || !chartInstance) return;

    if (!Array.isArray(data) || data.length === 0) {
      seriesRef.current.setData([]);
      markersRef.current?.setMarkers([]);
      return;
    }

    // Format data for lightweight-charts
    const formattedData = data.map(d => {
      const parsedTime = typeof d.time === 'number' && d.time < 2000000000
        ? d.time
        : new Date(d.time).getTime() / 1000;
      const time = parsedTime as Time;
      return {
        time,
        open: Number(d.open),
        high: Number(d.high),
        low: Number(d.low),
        close: Number(d.close),
      };
    });

    // Sort and remove duplicates
    const seenTimes = new Set<number>();
    const uniqueData = formattedData
      .filter(v => {
        const timeNum = v.time as number;
        if (!Number.isFinite(timeNum) || ![v.open, v.high, v.low, v.close].every(Number.isFinite)) {
          return false;
        }
        if (seenTimes.has(timeNum)) {
          return false;
        }
        seenTimes.add(timeNum);
        return true;
      })
      .sort((a, b) => (a.time as number) - (b.time as number));

    seriesRef.current.setData(uniqueData);

    if (trades.length > 0) {
      const markers: any[] = [];
      trades.forEach(trade => {
        const entryTime = (new Date(trade.entry_time).getTime() / 1000) as Time;
        const exitTime = (new Date(trade.exit_time).getTime() / 1000) as Time;

        if (!Number.isFinite(entryTime as number) || !Number.isFinite(exitTime as number)) return;

        markers.push({
          time: entryTime,
          position: trade.direction === 'bullish' ? 'belowBar' : 'aboveBar',
          color: trade.direction === 'bullish' ? '#10b981' : '#ef4444',
          shape: trade.direction === 'bullish' ? 'arrowUp' : 'arrowDown',
          text: 'ENTRY'
        });

        const pnlText = trade.pnl_pct != null ? `${Number(trade.pnl_pct).toFixed(2)}%` : '0.00%';
        markers.push({
          time: exitTime,
          position: trade.direction === 'bullish' ? 'aboveBar' : 'belowBar',
          color: (trade.pnl_pct || 0) > 0 ? '#10b981' : '#ef4444',
          shape: trade.direction === 'bullish' ? 'arrowDown' : 'arrowUp',
          text: `EXIT (${pnlText})`
        });
      });

      markers.sort((a, b) => (a.time as number) - (b.time as number));
      markersRef.current?.setMarkers(markers);
    } else {
      markersRef.current?.setMarkers([]);
    }
  }, [data, trades, chartInstance]);

  // Live Ticking Subscription: updates the last candle in real-time like broker charts
  useEffect(() => {
    if (!ticker) return;

    let isMounted = true;
    const fetchLiveTick = async () => {
      try {
        const res = await axios.get(`/api/v1/market/live-tick/${encodeURIComponent(ticker)}`, {
          params: { timeframe }
        });
        if (!isMounted || !seriesRef.current || !res.data?.candle) return;
        const c = res.data.candle;
        const parsedTime = typeof c.time === 'number' && c.time < 2000000000
          ? c.time
          : new Date(c.time).getTime() / 1000;
        if (!Number.isFinite(parsedTime as number)) return;
        const o = Number(c.open);
        const h = Number(c.high);
        const l = Number(c.low);
        const cl = Number(c.close);
        if ([o, h, l, cl].every(Number.isFinite)) {
          seriesRef.current.update({
            time: parsedTime as Time,
            open: o,
            high: h,
            low: l,
            close: cl
          });
        }
      } catch {
        // Fail silently on tick timeout
      }
    };

    const intervalId = setInterval(fetchLiveTick, 2000); // 2s live candle movement
    return () => {
      isMounted = false;
      clearInterval(intervalId);
    };
  }, [ticker, timeframe]);

  return <div ref={chartContainerRef} className="w-full rounded-lg overflow-hidden border border-gray-800" />;
};

export default ChartWidget;
