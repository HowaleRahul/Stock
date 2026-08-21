import { useState, useEffect } from 'react';
import axios from 'axios';
import ChartWidget from '../components/ChartWidget';

const Dashboard = () => {
  const [ticker, setTicker] = useState('^NSEI');
  const [timeframe, setTimeframe] = useState('1d');
  const [chartData, setChartData] = useState<any[]>([]);
  const [signals, setSignals] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  const loadData = async () => {
    setLoading(true);
    try {
      const period = timeframe === '1d' ? '5y' : '60d';
      const ohlcvRes = await axios.get('/api/v1/data/ohlcv', {
        params: { ticker, timeframe, period }
      });
      
      const df = ohlcvRes.data.data || [];
      const formattedDf = df.map((row: any) => ({
          time: row.timestamp || row.Date || row.Datetime,
          open: row.open,
          high: row.high,
          low: row.low,
          close: row.close
      }));
      setChartData(formattedDf);

      const signalsRes = await axios.get('/api/v1/data/signals', {
        params: { ticker, timeframe }
      });
      setSignals(signalsRes.data.setups || []);

    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [ticker, timeframe]);

  return (
    <div className="flex gap-6 h-[calc(100vh-100px)]">
      <div className="flex-grow flex flex-col gap-4">
        <div className="flex justify-between items-center bg-gray-900 p-4 rounded-lg border border-gray-800">
            <div className="flex gap-4">
                <input 
                    type="text" 
                    value={ticker} 
                    onChange={e => setTicker(e.target.value.toUpperCase())}
                    onBlur={loadData}
                    onKeyDown={e => e.key === 'Enter' && loadData()}
                    className="bg-gray-800 border border-gray-700 rounded px-3 py-1 text-white font-bold"
                />
            </div>
            <div className="flex gap-2 bg-gray-800 p-1 rounded-lg border border-gray-700">
                {['1h', '1d', '1wk'].map(tf => (
                    <button 
                        key={tf}
                        onClick={() => setTimeframe(tf)}
                        className={`px-3 py-1 rounded ${timeframe === tf ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white'}`}
                    >
                        {tf.toUpperCase()}
                    </button>
                ))}
            </div>
        </div>
        
        <div className="flex-grow bg-gray-900 rounded-lg border border-gray-800 relative">
            {loading && (
                <div className="absolute inset-0 z-10 flex items-center justify-center bg-gray-900/50 rounded-lg">
                    <div className="text-blue-400 animate-pulse">Loading Chart Data...</div>
                </div>
            )}
            {chartData.length > 0 && <ChartWidget data={chartData} height={600} />}
        </div>
      </div>

      <div className="w-80 bg-gray-900 rounded-lg border border-gray-800 p-4 overflow-y-auto">
        <h2 className="text-xl font-bold mb-4 border-b border-gray-800 pb-2">Setup Signals</h2>
        <div className="space-y-4">
            {signals.map((setup, idx) => (
                <div key={idx} className="bg-gray-800 p-3 rounded border border-gray-700">
                    <div className="flex justify-between items-center mb-2">
                        <span className="font-semibold text-gray-200">{setup.name.replace(/_/g, ' ').toUpperCase()}</span>
                        <span className={`px-2 py-1 rounded text-xs font-bold ${
                            setup.signal === 1 ? 'bg-emerald-900 text-emerald-400' :
                            setup.signal === -1 ? 'bg-red-900 text-red-400' : 'bg-gray-700 text-gray-400'
                        }`}>
                            {setup.signal === 1 ? 'BULLISH' : setup.signal === -1 ? 'BEARISH' : 'NEUTRAL'}
                        </span>
                    </div>
                    {setup.description && <p className="text-sm text-gray-400">{setup.description}</p>}
                </div>
            ))}
            {signals.length === 0 && !loading && (
                <div className="text-gray-500 text-center py-4">No active setups on this timeframe.</div>
            )}
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
