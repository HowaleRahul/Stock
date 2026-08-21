import { useState, useEffect } from 'react';
import axios from 'axios';

const Portfolio = () => {
  const [data, setData] = useState<{account: any, open_trades: any[]}>({ account: {}, open_trades: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchPortfolio = async () => {
      try {
        const res = await axios.get('/api/v1/dashboard/portfolio');
        setData(res.data);
      } catch (err) {
        console.error('Failed to load portfolio:', err);
        setError('Portfolio data is unavailable. Please try again later.');
      } finally {
        setLoading(false);
      }
    };
    fetchPortfolio();
  }, []);

  if (loading) return <div className="text-gray-400">Loading Portfolio...</div>;
  if (error) return <div role="alert" className="text-red-400">{error}</div>;

  const { account, open_trades } = data;

  return (
    <div className="space-y-6">
      <div className="bg-gray-900 p-6 rounded-lg border border-gray-800">
        <h3 className="text-xl font-bold text-blue-400 mb-4">Account Summary</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div>
                <p className="text-gray-400 text-sm">Capital</p>
                <p className="text-2xl font-bold">₹{(account.capital || 0).toLocaleString()}</p>
            </div>
            <div>
                <p className="text-gray-400 text-sm">Peak Capital</p>
                <p className="text-2xl font-bold text-emerald-400">₹{(account.peak_capital || 0).toLocaleString()}</p>
            </div>
            <div>
                <p className="text-gray-400 text-sm">Status</p>
                <p className="text-lg font-medium text-gray-300">{account.status || 'ACTIVE'}</p>
            </div>
        </div>
      </div>

      <div className="bg-gray-900 p-6 rounded-lg border border-gray-800">
        <h3 className="text-xl font-bold text-blue-400 mb-4">Open Paper Trades</h3>
        {open_trades.length === 0 ? (
            <p className="text-gray-500">No open trades.</p>
        ) : (
            <div className="overflow-x-auto">
                <table className="w-full text-left">
                    <thead className="border-b border-gray-800 text-gray-400 text-sm uppercase">
                        <tr>
                            <th className="py-3 px-4">Ticker</th>
                            <th className="py-3 px-4">Direction</th>
                            <th className="py-3 px-4">Entry Price</th>
                            <th className="py-3 px-4">Quantity</th>
                            <th className="py-3 px-4">Invested</th>
                            <th className="py-3 px-4">Take Profit</th>
                            <th className="py-3 px-4">Stop Loss</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-800">
                        {open_trades.map((t, idx) => (
                            <tr key={idx} className="hover:bg-gray-800/50">
                                <td className="py-3 px-4 font-bold">{t.ticker}</td>
                                <td className={`py-3 px-4 font-bold ${t.direction === 'bullish' ? 'text-emerald-400' : 'text-red-400'}`}>
                                    {t.direction.toUpperCase()}
                                </td>
                                <td className="py-3 px-4">₹{t.entry_price}</td>
                                <td className="py-3 px-4">{t.quantity}</td>
                                <td className="py-3 px-4">₹{t.invested}</td>
                                <td className="py-3 px-4 text-emerald-400">₹{t.take_profit}</td>
                                <td className="py-3 px-4 text-red-400">₹{t.stop_loss}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        )}
      </div>
    </div>
  );
};

export default Portfolio;
