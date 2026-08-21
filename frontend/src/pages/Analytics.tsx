import { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { createChart, ColorType } from 'lightweight-charts';
import type { IChartApi, ISeriesApi, Time } from 'lightweight-charts';

const Analytics = () => {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);

  useEffect(() => {
    const fetchAnalytics = async () => {
      try {
        const res = await axios.get('/api/v1/dashboard/analytics');
        setData(res.data);
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    };
    fetchAnalytics();
  }, []);

  useEffect(() => {
    if (!loading && data && chartContainerRef.current) {
        if (chartRef.current) {
            chartRef.current.remove();
        }

        const chart = createChart(chartContainerRef.current, {
            layout: {
                background: { type: ColorType.Solid, color: 'transparent' },
                textColor: '#d1d4dc',
            },
            grid: {
                vertLines: { color: 'rgba(42, 46, 57, 0.5)' },
                horzLines: { color: 'rgba(42, 46, 57, 0.5)' },
            },
            width: chartContainerRef.current.clientWidth,
            height: 400,
        });

        const lineSeries = chart.addLineSeries({
            color: '#2962FF',
            lineWidth: 2,
        });

        // Ensure unique, sorted times
        const uniqueData = data.equity_curve
            .filter((v: any, i: number, a: any[]) => a.findIndex((t: any) => (t.time === v.time)) === i)
            .sort((a: any, b: any) => a.time - b.time);
            
        lineSeries.setData(uniqueData.map((d: any) => ({ time: d.time as Time, value: d.value })));
        chart.timeScale().fitContent();
        
        chartRef.current = chart;

        const handleResize = () => {
            if (chartContainerRef.current && chartRef.current) {
                chartRef.current.applyOptions({ width: chartContainerRef.current.clientWidth });
            }
        };
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }
  }, [data, loading]);

  if (loading) return <div className="text-gray-400">Loading Analytics...</div>;

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-white mb-6">Risk & Analytics Dashboard</h2>
      
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-gray-900 p-6 rounded-lg border border-gray-800">
            <p className="text-gray-400 text-sm">Overall Win Rate</p>
            <p className="text-3xl font-bold text-emerald-400">{data.win_rate.toFixed(1)}%</p>
            <p className="text-sm text-gray-500 mt-2">Across {data.total_trades} historical trades</p>
        </div>
        <div className="bg-gray-900 p-6 rounded-lg border border-gray-800">
            <p className="text-gray-400 text-sm">Probability of Ruin</p>
            <p className={`text-3xl font-bold ${data.probability_of_ruin > 30 ? 'text-red-400' : 'text-emerald-400'}`}>
                {data.probability_of_ruin.toFixed(1)}%
            </p>
            <p className="text-sm text-gray-500 mt-2">Risk of hitting 0 capital</p>
        </div>
      </div>

      <div className="bg-gray-900 p-6 rounded-lg border border-gray-800">
        <h3 className="text-lg font-bold text-white mb-4">Equity Curve</h3>
        {data.equity_curve.length > 0 ? (
             <div ref={chartContainerRef} className="w-full" />
        ) : (
            <div className="text-gray-500">Not enough closed trades to plot an equity curve.</div>
        )}
      </div>

      <div className="bg-gray-900 p-6 rounded-lg border border-gray-800">
        <h3 className="text-lg font-bold text-white mb-4">Win Rate by Day of Week</h3>
        <div className="grid grid-cols-5 gap-4">
            {Object.entries(data.win_by_day).map(([day, rate]: any) => (
                <div key={day} className="bg-gray-800 p-4 rounded text-center">
                    <div className="text-gray-400 text-sm">{day}</div>
                    <div className="text-xl font-bold mt-1 text-blue-400">{rate.toFixed(0)}%</div>
                </div>
            ))}
        </div>
      </div>
    </div>
  );
};

export default Analytics;
