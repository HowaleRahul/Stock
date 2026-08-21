import React, { useEffect, useRef } from 'react';
import { CandlestickSeries, createChart, createSeriesMarkers } from 'lightweight-charts';
import type { Time } from 'lightweight-charts';

interface ChartWidgetProps {
  data: any[];
  trades?: any[];
  height?: number;
}

const ChartWidget: React.FC<ChartWidgetProps> = ({ data, trades = [], height = 400 }) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);
  const seriesRef = useRef<any>(null);
  const markersRef = useRef<any>(null);

  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      height,
      layout: {
        background: { color: '#fffdfa' },
        textColor: '#68757a',
      },
      grid: {
        vertLines: { color: '#eeeae1' },
        horzLines: { color: '#eeeae1' },
      },
      rightPriceScale: { borderColor: '#dfdcd3' },
      timeScale: { borderColor: '#dfdcd3' },
      localization: { priceFormatter: (price: number) => price.toLocaleString('en-IN', { maximumFractionDigits: 2 }) },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#4a9b70',
      downColor: '#e06a57',
      borderVisible: false,
      wickUpColor: '#4a9b70',
      wickDownColor: '#e06a57',
    });

    chartRef.current = chart;
    seriesRef.current = candleSeries;
    markersRef.current = createSeriesMarkers(candleSeries, []);

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
      markersRef.current?.detach();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      markersRef.current = null;
    };
  }, [height]);

  useEffect(() => {
    if (seriesRef.current && data.length > 0) {
      // Format data for lightweight-charts
      const formattedData = data.map(d => {
        const parsedTime = new Date(d.time).getTime();
        const time = (parsedTime / 1000) as Time;
        return {
          time,
          open: Number(d.open),
          high: Number(d.high),
          low: Number(d.low),
          close: Number(d.close),
        };
      });
      // Sort and remove duplicates based on time
      const uniqueData = formattedData
        .filter(v => Number.isFinite(v.time as number) && [v.open, v.high, v.low, v.close].every(Number.isFinite))
        .filter((v, i, a) => a.findIndex(t => (t.time === v.time)) === i)
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
                color: trade.direction === 'bullish' ? '#26a69a' : '#ef5350',
                shape: trade.direction === 'bullish' ? 'arrowUp' : 'arrowDown',
                text: 'ENTRY'
            });

            markers.push({
                time: exitTime,
                position: trade.direction === 'bullish' ? 'aboveBar' : 'belowBar',
                color: trade.pnl_pct > 0 ? '#26a69a' : '#ef5350',
                shape: trade.direction === 'bullish' ? 'arrowDown' : 'arrowUp',
                text: `EXIT (${trade.pnl_pct.toFixed(2)}%)`
            });
        });
        
        // Sort markers by time
        markers.sort((a, b) => (a.time as number) - (b.time as number));
        markersRef.current?.setMarkers(markers);
      } else {
        markersRef.current?.setMarkers([]);
      }
    }
  }, [data, trades]);

  return <div ref={chartContainerRef} className="w-full rounded-lg overflow-hidden border border-gray-800" />;
};

export default ChartWidget;
