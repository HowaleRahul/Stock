import { useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';
import { RefreshCw, WalletCards, ArrowUpRight, ArrowDownRight } from 'lucide-react';

interface AccountData {
  capital?: number;
  peak_capital?: number;
  status?: string;
  unrealized_mtm?: number;
  net_liquidation_value?: number;
}

interface OpenTrade {
  order_id?: string;
  ticker: string;
  direction: string;
  entry_price: number;
  quantity: number;
  invested: number;
  take_profit: number;
  stop_loss: number;
  current_ltp?: number;
  unrealized_pnl?: number;
  unrealized_pnl_pct?: number;
}

const Portfolio = () => {
  const [data, setData] = useState<{ account: AccountData; open_trades: OpenTrade[] }>({
    account: {},
    open_trades: [],
  });
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const fetchPortfolio = useCallback(async (isManual = false) => {
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
      const [dbRes, liveRes] = await Promise.allSettled([
        axios.get('/api/v1/dashboard/portfolio', { signal: controller.signal }),
        axios.get('/api/v1/training/live-portfolio', { signal: controller.signal }),
      ]);

      let acc: AccountData = {};
      let trades: OpenTrade[] = [];

      // Check live training portfolio first
      if (liveRes.status === 'fulfilled' && liveRes.value.data?.portfolio) {
        const p = liveRes.value.data.portfolio;
        acc = {
          capital: p.cash_balance,
          peak_capital: p.peak_capital,
          status: 'ACTIVE (LIVE FEED)',
          unrealized_mtm: p.unrealized_mtm,
          net_liquidation_value: p.net_liquidation_value,
        };
        if (Array.isArray(p.open_trades) && p.open_trades.length > 0) {
          trades = p.open_trades.map((t: any) => ({
            order_id: t.id,
            ticker: t.ticker,
            direction: t.direction,
            entry_price: t.entry_price,
            quantity: t.quantity,
            invested: t.invested,
            take_profit: t.tp,
            stop_loss: t.sl,
            current_ltp: t.current_ltp,
            unrealized_pnl: t.unrealized_pnl,
            unrealized_pnl_pct: t.unrealized_pnl_pct,
          }));
        }
      }

      // Fallback or merge with database portfolio if live has no positions
      if (trades.length === 0 && dbRes.status === 'fulfilled') {
        const dbAcc = dbRes.value.data?.account || {};
        acc = {
          capital: acc.capital || dbAcc.capital || 1000000.0,
          peak_capital: acc.peak_capital || dbAcc.peak_capital || 1000000.0,
          status: acc.status || dbAcc.status || 'ACTIVE',
          unrealized_mtm: acc.unrealized_mtm || 0.0,
          net_liquidation_value: acc.net_liquidation_value || dbAcc.capital || 1000000.0,
        };
        trades = Array.isArray(dbRes.value.data?.open_trades) ? dbRes.value.data.open_trades : [];
      }

      setData({
        account: acc,
        open_trades: trades,
      });
      setLastUpdated(new Date());
    } catch (err: any) {
      if (axios.isCancel(err)) return;
      setError('Backend is offline. Start the API server and retry.');
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    fetchPortfolio();
    const interval = setInterval(() => fetchPortfolio(), 4000);
    return () => {
      clearInterval(interval);
      if (abortRef.current) {
        abortRef.current.abort();
      }
    };
  }, [fetchPortfolio]);

  if (loading && !lastUpdated) return <div className="text-gray-400 p-8">Loading Portfolio...</div>;
  if (error && !lastUpdated) {
    return (
      <div className="state-panel" role="alert">
        <strong>{error}</strong>
        <button className="retry-button" onClick={() => fetchPortfolio()}>Retry connection</button>
      </div>
    );
  }

  const { account, open_trades } = data;
  const capital = account.capital ?? 1000000.0;
  const peakCapital = account.peak_capital ?? 1000000.0;
  const totalDeployed = open_trades.reduce((sum, t) => sum + (Number(t.invested) || 0), 0);
  const mtm = account.unrealized_mtm || 0;
  const isMtmPositive = mtm >= 0;

  return (
    <div className="portfolio-page">
      {error && (
        <div className="state-panel compact mb-4" role="alert">
          <strong>{error}</strong>
          <button className="retry-button" onClick={() => fetchPortfolio(true)}>Retry</button>
        </div>
      )}
      <div className="page-heading portfolio-heading">
        <div>
          <span className="eyebrow">Frontpage Virtual Capital / 02</span>
          <h1>Portfolio & Live MTM Surface</h1>
          <p>Real-time capital, live ticking Mark-To-Market PnL, margin utilization, and open positions.</p>
        </div>
        <div className="portfolio-refresh">
          <span>{lastUpdated ? `Ticking ${lastUpdated.toLocaleTimeString()}` : 'Not synced'}</span>
          <button
            className="icon-button"
            onClick={() => fetchPortfolio(true)}
            disabled={loading || refreshing}
            aria-label="Refresh portfolio"
            title="Refresh portfolio"
          >
            <RefreshCw className={refreshing ? 'spin' : ''} />
          </button>
        </div>
      </div>

      <div className="portfolio-summary">
        <div className="portfolio-summary-icon"><WalletCards /></div>
        <div>
          <span className="eyebrow">Virtual Account status</span>
          <h2>{account.status || 'ACTIVE'}</h2>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
          <div>
            <p className="text-gray-400 text-sm">Cash Balance</p>
            <p className="text-2xl font-bold font-mono">₹{Number(capital).toLocaleString('en-IN', { maximumFractionDigits: 2 })}</p>
          </div>
          <div>
            <p className="text-gray-400 text-sm">Peak Capital</p>
            <p className="text-2xl font-bold font-mono text-emerald-400">₹{Number(peakCapital).toLocaleString('en-IN', { maximumFractionDigits: 2 })}</p>
          </div>
          <div>
            <p className="text-gray-400 text-sm">Margin Deployed</p>
            <p className="text-2xl font-bold font-mono text-blue-400">
              ₹{Number(totalDeployed).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
            </p>
          </div>
          <div>
            <p className="text-gray-400 text-sm">Live Unrealized MTM</p>
            <p className={`text-2xl font-bold font-mono flex items-center gap-1 ${
              isMtmPositive ? 'text-emerald-400' : 'text-red-400'
            }`}>
              {isMtmPositive ? <ArrowUpRight className="w-5 h-5" /> : <ArrowDownRight className="w-5 h-5" />}
              {isMtmPositive ? '+' : ''}₹{mtm.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </p>
          </div>
        </div>
      </div>

      <div className="portfolio-positions">
        <div className="positions-heading">
          <div>
            <span className="eyebrow">Exposure</span>
            <h2>Active paper trades</h2>
          </div>
          <span>{open_trades.length.toString().padStart(2, '0')} positions</span>
        </div>
        {open_trades.length === 0 ? (
          <p className="text-gray-500 py-6">No open trades in the paper account.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <caption className="sr-only">Active open positions in paper portfolio</caption>
              <thead className="border-b border-gray-800 text-gray-400 text-sm uppercase">
                <tr>
                  <th scope="col" className="py-3 px-4">Ticker</th>
                  <th scope="col" className="py-3 px-4">Direction</th>
                  <th scope="col" className="py-3 px-4 text-right">Entry Price</th>
                  <th scope="col" className="py-3 px-4 text-right">Live LTP</th>
                  <th scope="col" className="py-3 px-4 text-right">Quantity</th>
                  <th scope="col" className="py-3 px-4 text-right">Invested</th>
                  <th scope="col" className="py-3 px-4 text-right">Live MTM PnL</th>
                  <th scope="col" className="py-3 px-4 text-right">Take Profit</th>
                  <th scope="col" className="py-3 px-4 text-right">Stop Loss</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800 font-mono">
                {open_trades.map((t, idx) => {
                  const isLong = ['LONG', 'BULLISH'].includes(String(t.direction).toUpperCase());
                  const cleanSym = String(t.ticker || '').toUpperCase().trim();
                  const isIndian = cleanSym.endsWith('.NS') || cleanSym.endsWith('.BO') || cleanSym.includes('NSE') || cleanSym.includes('NIFTY') || cleanSym.includes('BANKNIFTY') || cleanSym.includes('SENSEX') || cleanSym === '^BSESN' || cleanSym === '^NSEI';
                  const currSym = isIndian ? '₹' : '$';
                  const loc = isIndian ? 'en-IN' : 'en-US';
                  const pnl = t.unrealized_pnl || 0;
                  const isPositive = pnl >= 0;

                  return (
                    <tr key={t.order_id || idx} className="hover:bg-gray-800/50">
                      <td className="py-3 px-4 font-bold">{t.ticker}</td>
                      <td className={`py-3 px-4 font-bold ${isLong ? 'text-emerald-400' : 'text-red-400'}`}>
                        {String(t.direction || 'UNKNOWN').toUpperCase()}
                      </td>
                      <td className="py-3 px-4 text-right">{currSym}{Number(t.entry_price || 0).toLocaleString(loc, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                      <td className="py-3 px-4 text-right font-bold text-white">
                        {currSym}{Number(t.current_ltp || t.entry_price || 0).toLocaleString(loc, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </td>
                      <td className="py-3 px-4 text-right">{t.quantity}</td>
                      <td className="py-3 px-4 text-right">{currSym}{Number(t.invested || 0).toLocaleString(loc, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                      <td className={`py-3 px-4 text-right font-bold ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
                        {isPositive ? '+' : ''}{currSym}{Number(pnl).toLocaleString(loc, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        {t.unrealized_pnl_pct != null && (
                          <span className="text-xs ml-1 opacity-80">({t.unrealized_pnl_pct.toFixed(2)}%)</span>
                        )}
                      </td>
                      <td className="py-3 px-4 text-right text-emerald-400">{currSym}{Number(t.take_profit || 0).toLocaleString(loc, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                      <td className="py-3 px-4 text-right text-red-400">{currSym}{Number(t.stop_loss || 0).toLocaleString(loc, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};

export default Portfolio;
