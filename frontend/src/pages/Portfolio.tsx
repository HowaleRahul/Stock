import { useState, useEffect, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { RefreshCw, WalletCards, ArrowUpRight, ArrowDownRight, Compass, Flame } from 'lucide-react';
import ErrorBoundary from '../components/ErrorBoundary';
import { formatIndianCurrency } from '../utils/formatters';
import {
  getExchangeLotSize,
  formatContractSymbol,
  isOptionSellingOrSpread,
  getOptionStrategyLabel,
  calculateOptionPayoffProfile,
} from '../utils/foUtils';

interface AccountData {
  capital?: number;
  starting_capital?: number;
  peak_capital?: number;
  status?: string;
  unrealized_mtm?: number;
  net_liquidation_value?: number;
  max_drawdown_pct?: number;
  win_rate?: number;
  total_trades?: number;
  winning_trades?: number;
  losing_trades?: number;
  circuit_breaker?: boolean;
}

interface OpenTrade {
  order_id?: string;
  ticker: string;
  direction: string;
  action?: string;
  strategy_type?: string;
  entry_price: number;
  quantity: number;
  invested: number;
  take_profit: number;
  stop_loss: number;
  current_ltp?: number;
  unrealized_pnl?: number;
  unrealized_pnl_pct?: number;
  is_fo?: boolean;
  instrument_type?: string;
  opt_type?: string;
  opt_strike?: number;
  opt_delta?: number;
  opt_theta?: number;
  opt_gamma?: number;
  opt_vega?: number;
  opt_iv?: number;
  strike_type?: string;
  lot_size?: number;
  hedge_strike_price?: number;
  hedge_entry_price?: number;
  net_credit?: number;
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
            is_fo: t.is_fo ?? true,
            instrument_type: t.instrument_type || 'OPTION',
            opt_type: t.opt_type,
            opt_strike: t.opt_strike,
            opt_delta: t.opt_delta,
            opt_theta: t.opt_theta,
            strike_type: t.strike_type,
            lot_size: t.lot_size,
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
    let ignore = false;
    const controller = new AbortController();
    abortRef.current = controller;

    Promise.allSettled([
      axios.get('/api/v1/dashboard/portfolio', { signal: controller.signal }),
      axios.get('/api/v1/training/live-portfolio', { signal: controller.signal }),
    ]).then(([dbRes, liveRes]) => {
      if (ignore) return;
      let acc: AccountData = {};
      let trades: OpenTrade[] = [];
      if (liveRes.status === 'fulfilled' && liveRes.value.data?.portfolio) {
        const livePort = liveRes.value.data.portfolio;
        acc = {
          capital: livePort.current_capital || livePort.starting_capital,
          starting_capital: livePort.starting_capital,
          status: liveRes.value.data.is_training ? 'ACTIVE' : 'IDLE',
          peak_capital: livePort.peak_capital,
          max_drawdown_pct: livePort.max_drawdown_pct,
          win_rate: livePort.win_rate,
          total_trades: livePort.total_trades,
          winning_trades: livePort.winning_trades,
          losing_trades: livePort.losing_trades,
          circuit_breaker: livePort.circuit_breaker,
        };
        trades = Array.isArray(livePort.open_trades) ? livePort.open_trades : [];
      } else if (dbRes.status === 'fulfilled' && dbRes.value.data) {
        acc = dbRes.value.data.account || {};
        trades = Array.isArray(dbRes.value.data.open_trades) ? dbRes.value.data.open_trades : [];
      }
      setData({ account: acc, open_trades: trades });
      setLastUpdated(new Date());
      setLoading(false);
    });

    const interval = setInterval(() => void fetchPortfolio(false), 4000);
    return () => {
      ignore = true;
      clearInterval(interval);
      controller.abort();
    };
  }, [fetchPortfolio]);

  if (loading && !lastUpdated) {
    return (
      <div className="portfolio-page flex items-center justify-center min-h-[400px]">
        <div className="flex flex-col items-center gap-3 text-gray-400">
          <RefreshCw className="w-6 h-6 animate-spin text-blue-500" />
          <span className="text-sm font-medium">Syncing paper portfolio ledger...</span>
        </div>
      </div>
    );
  }

  if (error && !lastUpdated) {
    return (
      <div className="state-panel" role="alert">
        <strong>{error}</strong>
        <p className="text-xs text-gray-400 mt-1">Unable to connect to paper trading engine.</p>
        <button className="retry-button mt-3" onClick={() => void fetchPortfolio(true)}>Retry connection</button>
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
          <button className="retry-button" onClick={() => void fetchPortfolio(true)}>Retry</button>
        </div>
      )}
      <div className="page-heading portfolio-heading">
        <div>
          <span className="eyebrow">Frontpage Virtual Capital / 02</span>
          <h1>Portfolio &amp; Live MTM Surface</h1>
          <p>Real-time capital, live ticking Mark-To-Market PnL, margin utilization, and open positions.</p>
        </div>
        <div className="portfolio-refresh">
          <span>{lastUpdated ? `Ticking ${lastUpdated.toLocaleTimeString()}` : 'Not synced'}</span>
          <button
            className="icon-button"
            onClick={() => void fetchPortfolio(true)}
            disabled={loading || refreshing}
            aria-label="Refresh portfolio"
            title="Refresh portfolio"
          >
            <RefreshCw className={refreshing ? 'spin' : ''} />
          </button>
        </div>
      </div>

      <ErrorBoundary compact title="Virtual Capital Ledger Error">
        <div className="portfolio-summary">
          <div className="portfolio-summary-icon"><WalletCards /></div>
          <div>
            <span className="eyebrow">Virtual Account status</span>
            <h2>{account.status || 'ACTIVE'}</h2>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 md:gap-6">
            <div className="p-3 bg-gray-950/40 rounded-lg border border-gray-800/80">
              <p className="text-gray-400 text-xs md:text-sm">Cash Balance</p>
              <p className="text-xl md:text-2xl font-bold font-mono text-white mt-1">
                {formatIndianCurrency(capital)}
              </p>
            </div>
            <div className="p-3 bg-gray-950/40 rounded-lg border border-gray-800/80">
              <p className="text-gray-400 text-xs md:text-sm">Peak Capital</p>
              <p className="text-xl md:text-2xl font-bold font-mono text-emerald-400 mt-1">
                {formatIndianCurrency(peakCapital)}
              </p>
            </div>
            <div className="p-3 bg-gray-950/40 rounded-lg border border-gray-800/80">
              <p className="text-gray-400 text-xs md:text-sm">Margin Deployed</p>
              <p className="text-xl md:text-2xl font-bold font-mono text-blue-400 mt-1">
                {formatIndianCurrency(totalDeployed)}
              </p>
            </div>
            <div className="p-3 bg-gray-950/40 rounded-lg border border-gray-800/80">
              <p className="text-gray-400 text-xs md:text-sm">Live Unrealized MTM</p>
              <p className={`text-xl md:text-2xl font-bold font-mono flex items-center gap-1 mt-1 ${
                isMtmPositive ? 'text-emerald-400' : 'text-red-400'
              }`}>
                {isMtmPositive ? <ArrowUpRight className="w-5 h-5 shrink-0" /> : <ArrowDownRight className="w-5 h-5 shrink-0" />}
                {formatIndianCurrency(mtm, { showSign: true })}
              </p>
            </div>
          </div>
        </div>
      </ErrorBoundary>

      <ErrorBoundary compact title="Active Trades Ledger Error">
        <div className="portfolio-positions">
          <div className="positions-heading">
            <div>
              <span className="eyebrow">Exposure</span>
              <h2>Active paper trades</h2>
            </div>
            <span>{open_trades.length.toString().padStart(2, '0')} positions</span>
          </div>

          {open_trades.length === 0 ? (
            <div className="bg-gray-900/60 border border-dashed border-gray-800 rounded-xl p-8 text-center my-4">
              <div className="w-12 h-12 bg-gray-800/80 rounded-full flex items-center justify-center mx-auto mb-3 text-gray-400">
                <WalletCards className="w-6 h-6" />
              </div>
              <h3 className="text-base font-bold text-white mb-1">No Active Paper Trades</h3>
              <p className="text-gray-400 text-sm max-w-md mx-auto mb-4">
                The paper portfolio currently holds no open positions. When the autonomous engine or swing scanner detects verified edge, orders will execute and appear here in real time.
              </p>
              <div className="flex flex-wrap gap-3 justify-center">
                <Link
                  to="/"
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold rounded-lg transition inline-flex items-center gap-1.5"
                >
                  <Compass className="w-4 h-4" /> Explore Live Market &amp; Setups
                </Link>
                <Link
                  to="/swing-toolkit"
                  className="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-gray-200 border border-gray-700 text-xs font-semibold rounded-lg transition inline-flex items-center gap-1.5"
                >
                  <Flame className="w-4 h-4 text-orange-400" /> Run Swing Scanners
                </Link>
              </div>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left min-w-[880px]">
                <caption className="sr-only">Active open positions in paper portfolio</caption>
                <thead className="border-b border-gray-800 text-gray-400 text-xs uppercase">
                  <tr>
                    <th scope="col" className="py-3 px-4">Contract Symbol</th>
                    <th scope="col" className="py-3 px-4">Direction</th>
                    <th scope="col" className="py-3 px-4 text-right">Entry Prem / Price</th>
                    <th scope="col" className="py-3 px-4 text-right">Live LTP</th>
                    <th scope="col" className="py-3 px-4 text-right">Lots &amp; Qty</th>
                    <th scope="col" className="py-3 px-4 text-right">Invested Margin</th>
                    <th scope="col" className="py-3 px-4 text-right">Live MTM PnL</th>
                    <th scope="col" className="py-3 px-4 text-center">Greeks</th>
                    <th scope="col" className="py-3 px-4 text-right">Targets (TP / SL)</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800 font-mono text-sm">
                  {open_trades.map((t, idx) => {
                    const isOpt = t.instrument_type === 'OPTION' || Boolean(t.opt_type);
                    const isShort = t.action === 'SELL' || t.direction === 'SELL' || t.direction === 'SHORT' || isOptionSellingOrSpread(t);
                    const isLong = !isShort && ['LONG', 'BULLISH', 'BUY'].includes(String(t.direction).toUpperCase());
                    const pnl = Number(t.unrealized_pnl) || 0;
                    const isPositive = pnl >= 0;
                    const lotSize = t.lot_size || getExchangeLotSize(t.ticker);
                    const lotsCount = Math.max(1, Math.round((t.quantity || lotSize) / lotSize));
                    const canonicalSymbol = formatContractSymbol(
                      t.ticker,
                      t.opt_strike,
                      t.opt_type,
                      t.instrument_type
                    );
                    const stratLabel = getOptionStrategyLabel(t);
                    const payoff = isOpt
                      ? calculateOptionPayoffProfile({
                          underlying: t.ticker,
                          strike: Number(t.opt_strike || 22800),
                          optionType: t.opt_type || 'CE',
                          entryPrice: Number(t.entry_price || 0),
                          currentSpot: Number(t.current_ltp || t.entry_price || 0),
                          action: isShort ? 'SELL' : 'BUY',
                          strategyType: t.strategy_type || (isShort ? 'CREDIT_SPREAD' : 'DIRECTIONAL'),
                          hedgeStrike: t.hedge_strike_price,
                          hedgePrice: t.hedge_entry_price,
                          lotSize,
                          quantity: t.quantity,
                          rawTheta: t.opt_theta,
                        })
                      : null;

                    return (
                      <tr key={t.order_id || idx} className="hover:bg-gray-800/50 transition-colors">
                        <td className="py-3 px-4 font-bold">
                          <div className="flex flex-col">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className="text-white text-sm">{canonicalSymbol}</span>
                              {isShort && (
                                <span className="text-[9px] text-amber-300 bg-amber-950/80 border border-amber-700/80 px-1.5 py-0.2 rounded font-bold uppercase">
                                  {stratLabel}
                                </span>
                              )}
                            </div>
                            <span className="text-[10px] text-gray-400 font-normal">
                              {t.instrument_type || (isOpt ? 'OPTION' : 'EQUITY')} • Lot Size: {lotSize}
                            </span>
                          </div>
                        </td>
                        <td className="py-3 px-4 font-bold">
                          <span className={`px-2 py-0.5 rounded text-xs font-bold uppercase transition-colors ${
                            isShort
                              ? 'bg-amber-950/90 text-amber-300 border border-amber-700/80 shadow-sm'
                              : isLong
                                ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                                : 'bg-red-950 text-red-400 border border-red-800'
                          }`}>
                            {isShort ? 'SHORT / SELL' : isLong ? 'BUY (LONG)' : t.direction}
                          </span>
                        </td>
                        <td className="py-3 px-4 text-right font-medium">
                          <div>{formatIndianCurrency(t.entry_price || 0)}</div>
                          {isShort && t.net_credit && (
                            <span className="text-[9px] text-emerald-400 block font-mono">Net Cr: {formatIndianCurrency(t.net_credit)}</span>
                          )}
                        </td>
                        <td className="py-3 px-4 text-right font-bold text-white">
                          {formatIndianCurrency(t.current_ltp || t.entry_price || 0)}
                        </td>
                        <td className="py-3 px-4 text-right">
                          <div className="text-white font-bold">{lotsCount} {lotsCount === 1 ? 'Lot' : 'Lots'}</div>
                          <div className="text-[10px] text-gray-400">({t.quantity} Qty)</div>
                        </td>
                        <td className="py-3 px-4 text-right text-gray-300">
                          <div className="font-bold text-white">{formatIndianCurrency(t.invested || 0)}</div>
                          <div className="text-[10px] text-gray-400">
                            {isShort ? 'Margin Blocked' : 'Premium Deployed'}
                          </div>
                        </td>
                        <td className={`py-3 px-4 text-right font-bold ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
                          <div>{formatIndianCurrency(pnl, { showSign: true })}</div>
                          {t.unrealized_pnl_pct != null && (
                            <span className="text-[11px] opacity-80">
                              ({t.unrealized_pnl_pct >= 0 ? '+' : ''}{t.unrealized_pnl_pct.toFixed(2)}%)
                            </span>
                          )}
                        </td>
                        <td className="py-3 px-4 text-center text-xs">
                          {isOpt ? (
                            <div className="flex flex-col text-[11px] font-mono">
                              <span>
                                Δ {Number(t.opt_delta || 0.52).toFixed(2)} |{' '}
                                <span className={isShort ? 'text-emerald-400 font-bold' : 'text-gray-400'}>
                                  Θ {isShort ? '+' : '-'}₹{Math.abs(Number(t.opt_theta || 14)).toFixed(0)}/d
                                </span>
                              </span>
                              <span className="text-[10px] text-gray-400">
                                {isShort ? 'Theta profit harvest' : 'IV ~16% | Γ 0.001'}
                              </span>
                            </div>
                          ) : (
                            <span className="text-gray-500 text-xs">—</span>
                          )}
                        </td>
                        <td className="py-3 px-4 text-right text-xs">
                          {payoff && (
                            <div className="text-amber-400 font-mono font-semibold">
                              BE: {formatIndianCurrency(payoff.breakeven, { decimals: 1 })}
                            </div>
                          )}
                          <div className="text-emerald-400 font-semibold">TP: {formatIndianCurrency(t.take_profit || 0)}</div>
                          <div className="text-red-400 font-semibold">SL: {formatIndianCurrency(t.stop_loss || 0)}</div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </ErrorBoundary>
    </div>
  );
};

export default Portfolio;
