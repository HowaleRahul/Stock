import React, { useEffect, useRef } from 'react';
import { createChart } from 'lightweight-charts';
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

  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      height,
      layout: {
        background: { color: '#131722' },
        textColor: '#d1d4dc',
      },
      grid: {
        vertLines: { color: '#1e222d' },
        horzLines: { color: '#1e222d' },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
      }
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: '#26a69a',
      downColor: '#ef5350',
      borderVisible: false,
      wickUpColor: '#26a69a',
      wickDownColor: '#ef5350',
    });

    chartRef.current = chart;
    seriesRef.current = candleSeries;

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [height]);

  useEffect(() => {
    if (seriesRef.current && data.length > 0) {
      // Format data for lightweight-charts
      const formattedData = data.map(d => {
        let time: Time = (new Date(d.time).getTime() / 1000) as Time;
        return {
          time,
          open: d.open,
          high: d.high,
          low: d.low,
          close: d.close,
        };
      });
      // Sort and remove duplicates based on time
      const uniqueData = formattedData.filter((v, i, a) => a.findIndex(t => (t.time === v.time)) === i).sort((a, b) => (a.time as number) - (b.time as number));
      
      seriesRef.current.setData(uniqueData);

      if (trades.length > 0) {
        const markers: any[] = [];
        trades.forEach(trade => {
            const entryTime = (new Date(trade.entry_time).getTime() / 1000) as Time;
            const exitTime = (new Date(trade.exit_time).getTime() / 1000) as Time;

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
        seriesRef.current.setMarkers(markers);
      }
    }
  }, [data, trades]);

  return <div ref={chartContainerRef} className="w-full rounded-lg overflow-hidden border border-gray-800" />;
};

export default ChartWidget;
