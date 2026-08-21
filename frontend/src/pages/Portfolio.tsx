import { useState, useEffect } from 'react';
import axios from 'axios';
import { RefreshCw, WalletCards } from 'lucide-react';

const Portfolio = () => {
  const [data, setData] = useState<{account: any, open_trades: any[]}>({ account: {}, open_trades: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const fetchPortfolio = async () => {
    setLoading(true);
    setError(null);
      try {
        const res = await axios.get('/api/v1/dashboard/portfolio');
        setData({ account: res.data.account || {}, open_trades: Array.isArray(res.data.open_trades) ? res.data.open_trades : [] });
        setLastUpdated(new Date());
      } catch (err: any) {
        const status = err?.response?.status;
        setError(status ? `Portfolio service unavailable (HTTP ${status}).` : 'Backend is offline. Start the API server and retry.');
      } finally {
        setLoading(false);
      }
  };

  useEffect(() => {
    fetchPortfolio();
  }, []);

  if (loading) return <div className="text-gray-400">Loading Portfolio...</div>;
  if (error) return <div className="state-panel" role="alert"><strong>{error}</strong><button className="retry-button" onClick={fetchPortfolio}>Retry connection</button></div>;

  const { account, open_trades } = data;

  return (
    <div className="portfolio-page">
      <div className="page-heading portfolio-heading"><div><span className="eyebrow">Risk surface / 02</span><h1>Portfolio</h1><p>Capital, exposure, and the positions currently held by the paper account.</p></div><div className="portfolio-refresh"><span>{lastUpdated ? `Updated ${lastUpdated.toLocaleTimeString()}` : 'Not synced'}</span><button className="icon-button" onClick={fetchPortfolio} aria-label="Refresh portfolio" title="Refresh portfolio"><RefreshCw className={loading ? 'spin' : ''} /></button></div></div>
      <div className="portfolio-summary">
        <div className="portfolio-summary-icon"><WalletCards /></div><div><span className="eyebrow">Account summary</span><h2>{account.status || 'ACTIVE'}</h2></div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div>
                <p className="text-gray-400 text-sm">Capital</p>
                <p className="text-2xl font-bold">₹{(account.capital || 0).toLocaleString()}</p>
            </div>
            <div>
                <p className="text-gray-400 text-sm">Peak Capital</p>
                <p className="text-2xl font-bold text-emerald-400">₹{(account.peak_capital || 0).toLocaleString()}</p>
            </div>
        </div>
      </div>

      <div className="portfolio-positions">
        <div className="positions-heading"><div><span className="eyebrow">Exposure</span><h2>Open paper trades</h2></div><span>{open_trades.length.toString().padStart(2, '0')} positions</span></div>
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
                            <tr key={t.order_id || idx} className="hover:bg-gray-800/50">
                                <td className="py-3 px-4 font-bold">{t.ticker}</td>
                              <td className={`py-3 px-4 font-bold ${['LONG', 'BULLISH'].includes(String(t.direction).toUpperCase()) ? 'text-emerald-400' : 'text-red-400'}`}>
                                {String(t.direction || 'UNKNOWN').toUpperCase()}
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
