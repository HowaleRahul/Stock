import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import axios from 'axios';
import {
  Play,
  Square,
  Terminal,
  Activity,
  BrainCircuit,
  RefreshCw,
  Wallet,
  Sparkles,
  Radio,
  Layers,
  ArrowUpRight,
  ArrowDownRight,
  ShieldCheck,
  CheckCircle2,
  Coins,
  TrendingUp,
  Cpu,
  Zap,
  Compass,
  Eye,
  X,
  History,
  Search,
} from 'lucide-react';
import { OptionChartViewer } from '../components/OptionChartViewer';
import TradingViewWidget from '../components/TradingViewWidget';
import ErrorBoundary from '../components/ErrorBoundary';
import { formatIndianCurrency } from '../utils/formatters';
import {
  getExchangeLotSize,
  formatContractSymbol,
  isOptionSellingOrSpread,
  getOptionStrategyLabel,
  calculateOptionPayoffProfile,
} from '../utils/foUtils';


interface PortfolioState {
  starting_capital: number;
  cash_balance: number;
  peak_capital: number;
  margin_deployed: number;
  unrealized_mtm: number;
  net_liquidation_value: number;
  total_realized_pnl: number;
  total_realized_pnl_pct: number;
  open_positions_count: number;
  closed_trades_count: number;
  win_rate: number;
  target_index?: string;
  derivative_type?: string;
  strike_preference?: string;
  fo_summary?: {
    total_fo_trades: number;
    options_win_rate: number;
    options_total: number;
    futures_win_rate: number;
    futures_total: number;
    last_update?: string;
  };
  open_trades?: any[];
  closed_trades?: any[];
}

const CAPITAL_PRESETS = [
  { label: '₹10k (Micro)', value: 10000 },
  { label: '₹25k', value: 25000 },
  { label: '₹50k', value: 50000 },
  { label: '₹1 Lakh', value: 100000 },
  { label: '₹10 Lakh', value: 1000000 },
];

const INDEX_PRESETS = [
  { id: 'ALL', label: 'All F&O Indices', desc: 'NIFTY, BANKNIFTY, SENSEX, FINNIFTY, MIDCPNIFTY' },
  { id: 'NIFTY', label: 'NIFTY 50', desc: 'Lot: 25 | Interval: 50 | Expiry: Thu' },
  { id: 'BANKNIFTY', label: 'BANK NIFTY', desc: 'Lot: 15 | Interval: 100 | Expiry: Wed' },
  { id: 'SENSEX', label: 'BSE SENSEX', desc: 'Lot: 10 | Interval: 100 | Expiry: Fri' },
  { id: 'FINNIFTY', label: 'FIN NIFTY', desc: 'Lot: 25 | Interval: 50 | Expiry: Tue' },
  { id: 'MIDCPNIFTY', label: 'MIDCAP NIFTY', desc: 'Lot: 50 | Interval: 25 | Expiry: Mon' },
];

const DERIVATIVE_PRESETS = [
  { id: 'AUTO', label: 'Auto (Budget-Optimized)', desc: 'Routes to Options (<₹1.2L) or Futures (≥₹1.2L)' },
  { id: 'OPTIONS', label: 'Options Only (CE / PE)', desc: 'Directional Call & Put Buying' },
  { id: 'SPREADS', label: 'Credit Spreads & Selling', desc: 'Bull Put / Bear Call Spreads & Hedged Writing (Theta Harvesting)' },
  { id: 'FUTURES', label: 'Futures Only', desc: 'Index Futures (Requires Margin)' },
];

const STRIKE_PRESETS = [
  { id: 'AUTO', label: 'AI Auto (Learned)', desc: 'F&O Bandit optimal strike for regime' },
  { id: 'ITM', label: 'In-The-Money (ITM)', desc: 'High Delta (~0.65) | Lower Theta drag' },
  { id: 'ATM', label: 'At-The-Money (ATM)', desc: 'Highest Gamma & Liquidity (Delta ~0.50)' },
  { id: 'OTM', label: 'Out-of-The-Money (OTM)', desc: 'Budget-friendly lower premium cost' },
];

const TrainingUI = () => {
  const [isTraining, setIsTraining] = useState(false);
  const [trainingMode, setTrainingMode] = useState<string>('auto');
  const [selectedStartMode, setSelectedStartMode] = useState<string>('auto');
  const [userCapital, setUserCapital] = useState<number>(10000);
  const [customCapitalInput, setCustomCapitalInput] = useState<string>('10000');

  // F&O and Target Selection States
  const [selectedIndex, setSelectedIndex] = useState<string>('ALL');
  const [selectedDerivative, setSelectedDerivative] = useState<string>('AUTO');
  const [selectedStrikePref, setSelectedStrikePref] = useState<string>('AUTO');

  // Option Chart Inspection State
  const [chartViewMode, setChartViewMode] = useState<'option' | 'spot'>('option');
  const [focusedOption, setFocusedOption] = useState<{
    underlying: string;
    strike: number;
    optionType: 'CE' | 'PE';
    action?: 'BUY' | 'SELL';
    strategyType?: string;
    hedgeStrike?: number;
    hedgePrice?: number;
    netCredit?: number;
    entryPrice?: number;
    targetPrice?: number;
    stopLossPrice?: number;
  } | null>(null);

  // Trade Specification Dossier Inspection Modal
  const [inspectedTrade, setInspectedTrade] = useState<any | null>(null);
  const [replayTelemetry, setReplayTelemetry] = useState<any | null>(null);
  const [capitalError, setCapitalError] = useState<string | null>(null);
  const [logDisplayCount, setLogDisplayCount] = useState<number>(300);
  const [logFilter, setLogFilter] = useState<string>('');
  const modalRef = useRef<HTMLDivElement>(null);
  const modalCloseBtnRef = useRef<HTMLButtonElement>(null);
  const triggerElementRef = useRef<HTMLElement | null>(null);

  const openTradeDossier = (trade: any) => {
    triggerElementRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setInspectedTrade(trade);
  };

  const closeTradeDossier = () => {
    setInspectedTrade(null);
    if (triggerElementRef.current) {
      triggerElementRef.current.focus();
      triggerElementRef.current = null;
    }
  };

  const [marketStatus, setMarketStatus] = useState<any>(null);
  const [portfolio, setPortfolio] = useState<PortfolioState | null>(null);
  const [cycles, setCycles] = useState<number>(0);
  const [logs, setLogs] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [actionPending, setActionPending] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const logsContainerRef = useRef<HTMLDivElement>(null);
  const logsEndRef = useRef<HTMLDivElement>(null);
  const isFetchingRef = useRef(false);

  // Fetch initial config to load any saved capital & F&O preferences
  useEffect(() => {
    const loadConfig = async () => {
      try {
        const res = await axios.get('/api/v1/dashboard/config');
        if (res.data?.capital) {
          const cap = Number(res.data.capital);
          setUserCapital(cap);
          setCustomCapitalInput(String(cap));
        }
        if (res.data?.target_index) setSelectedIndex(res.data.target_index);
        if (res.data?.derivative_type) setSelectedDerivative(res.data.derivative_type);
        if (res.data?.strike_preference) setSelectedStrikePref(res.data.strike_preference);
      } catch {
        // Fallback default
      }
    };
    loadConfig();
  }, []);

  const fetchStatus = useCallback(async (isManual = false) => {
    if (isFetchingRef.current) return;
    isFetchingRef.current = true;
    if (isManual) setIsRefreshing(true);
    try {
      const res = await axios.get('/api/v1/training/status');
      setIsTraining(Boolean(res.data.is_training));
      setTrainingMode(res.data.mode || 'IDLE');
      setMarketStatus(res.data.market_status || null);
      if (res.data.portfolio) {
        setPortfolio(res.data.portfolio);
        if (res.data.portfolio.starting_capital) {
          setUserCapital(res.data.portfolio.starting_capital);
        }
        if (res.data.target_index) setSelectedIndex(res.data.target_index);
        if (res.data.derivative_type) setSelectedDerivative(res.data.derivative_type);
        if (res.data.strike_preference) setSelectedStrikePref(res.data.strike_preference);
      }
      if (res.data.replay_telemetry) {
        setReplayTelemetry(res.data.replay_telemetry);
      }
      setCycles(res.data.cycles || 0);
      setLogs(Array.isArray(res.data.logs) ? res.data.logs : []);
      setError(null);
    } catch {
      setError("Training service is offline. Start the API server and retry.");
    } finally {
      isFetchingRef.current = false;
      setIsRefreshing(false);
    }
  }, [setLogs]);

  useEffect(() => {
    let ignore = false;
    axios.get('/api/v1/training/status')
      .then(res => {
        if (ignore) return;
        setIsTraining(Boolean(res.data.is_training));
        setTrainingMode(res.data.mode || 'IDLE');
        setMarketStatus(res.data.market_status || null);
        if (res.data.portfolio) {
          setPortfolio(res.data.portfolio);
          if (res.data.portfolio.starting_capital) {
            setUserCapital(res.data.portfolio.starting_capital);
          }
          if (res.data.target_index) setSelectedIndex(res.data.target_index);
          if (res.data.derivative_type) setSelectedDerivative(res.data.derivative_type);
          if (res.data.strike_preference) setSelectedStrikePref(res.data.strike_preference);
        }
        if (res.data.replay_telemetry) {
          setReplayTelemetry(res.data.replay_telemetry);
        }
        setCycles(res.data.cycles || 0);
        setLogs(Array.isArray(res.data.logs) ? res.data.logs : []);
        setError(null);
      })
      .catch(() => {
        if (!ignore) {
          setError("Training service is offline. Start the API server and retry.");
        }
      });

    const pollInterval = isTraining ? 2000 : 6000;
    const interval = setInterval(() => void fetchStatus(false), pollInterval);
    return () => {
      ignore = true;
      clearInterval(interval);
    };
  }, [fetchStatus, isTraining]);

  useEffect(() => {
    if (autoScroll && logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, autoScroll]);

  const handleScroll = () => {
    if (!logsContainerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = logsContainerRef.current;
    const atBottom = scrollHeight - scrollTop - clientHeight < 40;
    setAutoScroll(atBottom);
  };

  useEffect(() => {
    if (!inspectedTrade) return;
    const timer = setTimeout(() => {
      modalCloseBtnRef.current?.focus();
    }, 50);

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        closeTradeDossier();
        return;
      }
      if (e.key === 'Tab' && modalRef.current) {
        const focusables = modalRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        );
        if (focusables.length === 0) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      clearTimeout(timer);
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [inspectedTrade]);

  const handleSelectCapitalPreset = (val: number) => {
    setUserCapital(val);
    setCustomCapitalInput(String(val));
    setCapitalError(null);
  };

  const handleCustomCapitalChange = (valStr: string) => {
    setCustomCapitalInput(valStr);
    const trimmed = valStr.trim();
    if (!trimmed) {
      setCapitalError('Capital amount cannot be empty.');
      return;
    }
    const parsed = parseFloat(trimmed);
    if (!Number.isFinite(parsed) || parsed < 1000 || parsed > 100000000) {
      setCapitalError('Capital must be between ₹1,000 and ₹10,00,00,000.');
    } else {
      setUserCapital(parsed);
      setCapitalError(null);
    }
  };

  const handleCustomCapitalBlur = () => {
    const trimmed = customCapitalInput.trim();
    const parsed = parseFloat(trimmed);
    if (!trimmed || !Number.isFinite(parsed) || parsed < 1000) {
      setUserCapital(10000);
      setCustomCapitalInput('10000');
      setCapitalError(null);
    } else if (parsed > 100000000) {
      setUserCapital(100000000);
      setCustomCapitalInput('100000000');
      setCapitalError(null);
    }
  };

  const visibleLogs = useMemo(() => {
    let list = logs;
    if (logFilter.trim()) {
      const q = logFilter.toLowerCase();
      list = list.filter(l => l.toLowerCase().includes(q));
    }
    if (logDisplayCount > 0 && list.length > logDisplayCount) {
      return list.slice(-logDisplayCount);
    }
    return list;
  }, [logs, logFilter, logDisplayCount]);

  const handleStart = async () => {
    try {
      setActionPending(true);
      setError(null);
      await axios.post('/api/v1/training/start', {
        mode: selectedStartMode,
        capital: Number(userCapital) || 10000,
        target_index: selectedIndex,
        derivative_type: selectedDerivative,
        strike_preference: selectedStrikePref
      });
      await fetchStatus();
    } catch {
      setError("Training could not be started.");
    } finally {
      setActionPending(false);
    }
  };

  const handleStop = async () => {
    try {
      setActionPending(true);
      setError(null);
      setIsTraining(false);
      setTrainingMode('IDLE');
      await axios.post('/api/v1/training/stop');
      await fetchStatus();
    } catch {
      setError("Training could not be stopped.");
      await fetchStatus();
    } finally {
      setActionPending(false);
    }
  };

  const isMarketOpen = marketStatus?.is_open;
  const mtm = portfolio?.unrealized_mtm || 0;
  const isMtmPositive = mtm >= 0;

  // Dynamic Capital Tier calculations
  const isMicro = userCapital <= 25000;
  const isSmall = userCapital > 25000 && userCapital <= 100000;
  const tierName = isMicro ? 'MICRO' : isSmall ? 'SMALL' : 'GROWTH';
  const maxRiskPct = isMicro ? 0.015 : 0.02;
  const maxRiskAmount = userCapital * maxRiskPct;
  const minConfidence = isMicro ? 0.68 : isSmall ? 0.65 : 0.60;
  const minRR = isMicro ? 1.8 : 1.5;

  // Futures Margin estimates vs Options Premium estimates
  const futureMarginEstimate = selectedIndex === 'SENSEX'
    ? 80000 * 10 * 0.15 // ~₹1,20,000 for BSE SENSEX
    : selectedIndex === 'BANKNIFTY'
    ? 52000 * 15 * 0.15 // ~₹1,17,000 for BANKNIFTY
    : selectedIndex === 'FINNIFTY'
    ? 23500 * 25 * 0.15 // ~₹88,125 for FINNIFTY
    : 24500 * 25 * 0.15; // ~₹91,875 for NIFTY 50
  const canAffordFutures = userCapital >= futureMarginEstimate && (futureMarginEstimate <= userCapital * 0.60);

  return (
    <div className="training-page">
      {/* Top Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
        <div>
          <span className="eyebrow flex items-center gap-1.5 text-blue-400">
            <Sparkles className="w-3.5 h-3.5" /> High-Confluence AI Training & Derivative Execution
          </span>
          <h1 className="text-2xl font-bold text-white tracking-tight flex items-center gap-2">
            Frontpage Live Paper Trading & Continuous Brain
          </h1>
          <p className="text-sm text-gray-400">
            Real-time NSE ticks, Index F&O Derivative execution, smart strike selection & reinforcement learning
          </p>
        </div>

        <div className="flex items-center gap-3">
          <span className={`px-3 py-1 rounded-full text-xs font-semibold flex items-center gap-1.5 ${
            isMarketOpen
              ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
              : 'bg-gray-800 text-gray-300 border border-gray-700'
          }`}>
            <span className={`w-2 h-2 rounded-full ${isMarketOpen ? 'bg-emerald-400 animate-pulse' : 'bg-gray-400'}`} />
            {isMarketOpen ? 'NSE LIVE (09:15 - 15:30 IST)' : 'NSE CLOSED'}
          </span>
          <div className={`training-state ${isTraining ? 'running' : ''}`}>
            <span className="state-dot" /> {isTraining ? `RUNNING (${trainingMode})` : 'IDLE'}
          </div>
        </div>
      </div>

      {/* Capital Tier & Precision Tuning Surface */}
      <ErrorBoundary compact title="Capital Configuration Error">
        <section className="mb-6 p-5 rounded-xl border border-gray-800 bg-gray-900/80 shadow-lg">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-gray-800 pb-4 mb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-emerald-600/20 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
              <Coins className="w-5 h-5" />
            </div>
            <div>
              <span className="eyebrow">Account Capital Configuration</span>
              <h2 className="text-lg font-bold text-white flex items-center gap-2">
                Active Capital: ₹{userCapital.toLocaleString('en-IN')}
                <span className={`text-xs px-2 py-0.5 rounded font-bold uppercase ${
                  isMicro ? 'bg-purple-950 text-purple-300 border border-purple-800' :
                  isSmall ? 'bg-blue-950 text-blue-300 border border-blue-800' : 'bg-emerald-950 text-emerald-300 border border-emerald-800'
                }`}>
                  {tierName} TIER
                </span>
              </h2>
            </div>
          </div>

          {!isTraining && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-gray-400 font-semibold mr-1">Presets:</span>
              {CAPITAL_PRESETS.map(preset => (
                <button
                  key={preset.value}
                  type="button"
                  onClick={() => handleSelectCapitalPreset(preset.value)}
                  className={`px-3 py-1 text-xs font-semibold rounded-lg border transition-all ${
                    userCapital === preset.value
                      ? 'bg-blue-600 border-blue-500 text-white shadow-md shadow-blue-500/20'
                      : 'bg-gray-800/80 border-gray-700 text-gray-300 hover:border-gray-600'
                  }`}
                >
                  {preset.label}
                </button>
              ))}

              <div className="flex flex-col ml-2">
                <div className="flex items-center gap-1.5">
                  <span className="text-xs text-gray-400">Custom ₹:</span>
                  <input
                    type="number"
                    min="1000"
                    max="100000000"
                    step="1000"
                    value={customCapitalInput}
                    onChange={e => handleCustomCapitalChange(e.target.value)}
                    onBlur={handleCustomCapitalBlur}
                    aria-label="Custom capital in rupees"
                    className={`w-28 bg-gray-800 text-white font-mono text-xs px-2.5 py-1 rounded border ${
                      capitalError ? 'border-red-500 focus:border-red-500' : 'border-gray-700 focus:border-blue-500'
                    } focus:outline-none`}
                    placeholder="e.g. 10000"
                  />
                </div>
                {capitalError && (
                  <span className="text-[10px] text-red-400 mt-0.5" role="alert">{capitalError}</span>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Dynamic Risk & Confluence Quality Indicators */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 text-xs">
          <div className="p-3 rounded-lg bg-gray-950/60 border border-gray-800/80">
            <span className="text-gray-400 block mb-1">Max Risk Per Trade</span>
            <strong className="text-sm font-mono text-white">
              {(maxRiskPct * 100).toFixed(1)}% (₹{maxRiskAmount.toLocaleString('en-IN', { maximumFractionDigits: 0 })})
            </strong>
            <p className="text-[11px] text-gray-500 mt-1">Kelly-clamped to prevent account drawdown</p>
          </div>

          <div className="p-3 rounded-lg bg-gray-950/60 border border-gray-800/80">
            <span className="text-gray-400 block mb-1">AI Prediction Quality Gate</span>
            <strong className="text-sm font-mono text-emerald-400 flex items-center gap-1">
              <ShieldCheck className="w-4 h-4" /> {(minConfidence * 100).toFixed(0)}%+ Minimum Confidence
            </strong>
            <p className="text-[11px] text-gray-500 mt-1">High-confluence filter prevents low-edge trades</p>
          </div>

          <div className="p-3 rounded-lg bg-gray-950/60 border border-gray-800/80">
            <span className="text-gray-400 block mb-1">Min Risk-to-Reward</span>
            <strong className="text-sm font-mono text-blue-400">
              {minRR.toFixed(1)}:1 Asymmetric Edge
            </strong>
            <p className="text-[11px] text-gray-500 mt-1">Targets ₹{minRR.toFixed(1)} profit per ₹1 risked</p>
          </div>

          <div className="p-3 rounded-lg bg-gray-950/60 border border-gray-800/80">
            <span className="text-gray-400 block mb-1">Downside Protection</span>
            <strong className="text-sm font-mono text-purple-400 flex items-center gap-1">
              <CheckCircle2 className="w-4 h-4" /> {isMicro ? '0.8× ATR' : '1.0× ATR'} Breakeven Ratchet
            </strong>
            <p className="text-[11px] text-gray-500 mt-1">Locks stop-loss to entry on first favorable surge</p>
          </div>
        </div>
      </section>
      </ErrorBoundary>

      {/* Index & F&O Derivative Architecture Control Surface */}
      <ErrorBoundary compact title="F&O Instrument Configuration Error">
        <section className="mb-6 p-5 rounded-xl border border-gray-800 bg-gray-900/80 shadow-lg">
        <div className="border-b border-gray-800 pb-4 mb-4 flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-indigo-600/20 border border-indigo-500/30 flex items-center justify-center text-indigo-400">
              <Compass className="w-5 h-5" />
            </div>
            <div>
              <span className="eyebrow">Index & Derivative Specification (F&O)</span>
              <h2 className="text-lg font-bold text-white">
                Derivative Instrument & Smart Strike Routing
              </h2>
            </div>
          </div>

          {portfolio?.fo_summary && (
            <div className="flex items-center gap-4 text-xs font-mono bg-gray-950/80 px-3 py-1.5 rounded-lg border border-gray-800">
              <div className="flex items-center gap-1.5">
                <span className="text-gray-400">F&O Trades Learned:</span>
                <span className="text-white font-bold">{portfolio.fo_summary.total_fo_trades}</span>
              </div>
              <div className="flex items-center gap-1.5 border-l border-gray-800 pl-3">
                <span className="text-gray-400">Options WR:</span>
                <span className="text-emerald-400 font-bold">{portfolio.fo_summary.options_win_rate}%</span>
              </div>
              <div className="flex items-center gap-1.5 border-l border-gray-800 pl-3">
                <span className="text-gray-400">Futures WR:</span>
                <span className="text-blue-400 font-bold">{portfolio.fo_summary.futures_win_rate}%</span>
              </div>
            </div>
          )}
        </div>

        {/* 1. Target Index Selector */}
        <div className="mb-4">
          <label className="text-xs text-gray-400 uppercase font-semibold mb-2 block flex items-center gap-1.5">
            <TrendingUp className="w-3.5 h-3.5 text-blue-400" /> 1. Select Target Index:
          </label>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
            {INDEX_PRESETS.map(idx => (
              <button
                key={idx.id}
                type="button"
                disabled={isTraining}
                onClick={() => setSelectedIndex(idx.id)}
                className={`p-3 text-left rounded-lg border transition-all ${
                  selectedIndex === idx.id
                    ? 'bg-blue-950/60 border-blue-500 shadow-md shadow-blue-500/10'
                    : 'bg-gray-950/50 border-gray-800 hover:border-gray-700'
                } ${isTraining ? 'opacity-70 cursor-not-allowed' : ''}`}
              >
                <div className={`font-bold text-sm ${selectedIndex === idx.id ? 'text-blue-400' : 'text-gray-200'}`}>
                  {idx.label}
                </div>
                <div className="text-[11px] text-gray-500 mt-0.5">{idx.desc}</div>
              </button>
            ))}
          </div>
        </div>

        {/* 2. Derivative Instrument Selector */}
        <div className="mb-4">
          <label className="text-xs text-gray-400 uppercase font-semibold mb-2 block flex items-center gap-1.5">
            <Zap className="w-3.5 h-3.5 text-amber-400" /> 2. Derivative Execution Mode:
          </label>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
            {DERIVATIVE_PRESETS.map(deriv => (
              <button
                key={deriv.id}
                type="button"
                disabled={isTraining}
                onClick={() => setSelectedDerivative(deriv.id)}
                className={`p-3 text-left rounded-lg border transition-all ${
                  selectedDerivative === deriv.id
                    ? 'bg-amber-950/50 border-amber-500 shadow-md shadow-amber-500/10'
                    : 'bg-gray-950/50 border-gray-800 hover:border-gray-700'
                } ${isTraining ? 'opacity-70 cursor-not-allowed' : ''}`}
              >
                <div className={`font-bold text-sm ${selectedDerivative === deriv.id ? 'text-amber-400' : 'text-gray-200'}`}>
                  {deriv.label}
                </div>
                <div className="text-[11px] text-gray-500 mt-0.5">{deriv.desc}</div>
              </button>
            ))}
          </div>
        </div>

        {/* 3. Strike Preference (When Options, Spreads, or Auto active) */}
        {(selectedDerivative === 'AUTO' || selectedDerivative === 'OPTIONS' || selectedDerivative === 'SPREADS') && (
          <div className="mb-4">
            <label className="text-xs text-gray-400 uppercase font-semibold mb-2 block flex items-center gap-1.5">
              <Cpu className="w-3.5 h-3.5 text-purple-400" /> 3. Options Strike Selection Strategy:
            </label>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
              {STRIKE_PRESETS.map(stk => (
                <button
                  key={stk.id}
                  type="button"
                  disabled={isTraining}
                  onClick={() => setSelectedStrikePref(stk.id)}
                  className={`p-3 text-left rounded-lg border transition-all ${
                    selectedStrikePref === stk.id
                      ? 'bg-purple-950/50 border-purple-500 shadow-md shadow-purple-500/10'
                      : 'bg-gray-950/50 border-gray-800 hover:border-gray-700'
                  } ${isTraining ? 'opacity-70 cursor-not-allowed' : ''}`}
                >
                  <div className={`font-bold text-sm ${selectedStrikePref === stk.id ? 'text-purple-400' : 'text-gray-200'}`}>
                    {stk.label}
                  </div>
                  <div className="text-[11px] text-gray-500 mt-0.5">{stk.desc}</div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Dynamic Budget Advisory Banner */}
        <div className={`p-3 rounded-lg border text-xs flex items-start gap-2.5 ${
          selectedDerivative === 'FUTURES' && !canAffordFutures
            ? 'bg-red-950/40 border-red-800/80 text-red-200'
            : 'bg-indigo-950/40 border-indigo-800/80 text-indigo-200'
        }`}>
          <div className="mt-0.5">
            {selectedDerivative === 'FUTURES' && !canAffordFutures ? (
              <span className="text-red-400 font-bold">⚠️ Margin Notice:</span>
            ) : (
              <span className="text-indigo-400 font-bold">⚡ Budget-Optimized F&O Logic:</span>
            )}
          </div>
          <div>
            {selectedDerivative === 'FUTURES' && !canAffordFutures ? (
              <p>
                1 lot of Index Futures requires ~₹{Math.round(futureMarginEstimate).toLocaleString('en-IN')} margin. With ₹{userCapital.toLocaleString('en-IN')} capital,
                Futures orders will be rejected by Risk Gate 0 to protect your wallet. Please select <strong>Auto</strong> or <strong>Options Only</strong>.
              </p>
            ) : isMicro ? (
              <p>
                With ₹{userCapital.toLocaleString('en-IN')} Micro Capital, the system automatically buys <strong>Call (CE)</strong> or <strong>Put (PE) Options</strong> (1 lot ~₹2,500 - ₹3,500 premium).
                Futures margin requirement (~₹1.15L) is safely bypassed, downside is strictly limited to premium invested, and the F&O contextual bandit dynamically selects the optimal strike!
              </p>
            ) : (
              <p>
                With ₹{userCapital.toLocaleString('en-IN')} capital, both <strong>Index Futures</strong> and <strong>Index Options</strong> are eligible.
                In strong trend regimes (ADX &gt; 30), Futures offers linear 1.0 Delta without theta decay; in choppy regimes, Options limits downside to premium.
              </p>
            )}
          </div>
        </div>
      </section>
      </ErrorBoundary>

      {/* Frontpage-Style Virtual Wallet & Live MTM Bar */}
      <ErrorBoundary compact title="Virtual Account & Positions Error">
        <section className="mb-6 p-5 rounded-xl border border-gray-800 bg-gray-900/60 shadow-lg">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-gray-800 pb-4 mb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-blue-600/20 border border-blue-500/30 flex items-center justify-center text-blue-400">
              <Wallet className="w-5 h-5" />
            </div>
            <div>
              <span className="eyebrow">Frontpage Virtual Account</span>
              <h2 className="text-lg font-bold text-white flex items-center gap-2">
                ₹{userCapital.toLocaleString('en-IN')} Capital Portfolio
                <span className="text-xs font-normal text-gray-400">
                  ({portfolio ? `Cash: ₹${Number(portfolio.cash_balance || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : 'Ready'})
                </span>
              </h2>
            </div>
          </div>

          <div className="flex items-center gap-6">
            <div className="text-right">
              <span className="text-xs text-gray-400">Live MTM PnL</span>
              <div className={`text-xl font-mono font-bold flex items-center gap-1 justify-end ${
                isMtmPositive ? 'text-emerald-400' : 'text-red-400'
              }`}>
                {isMtmPositive ? <ArrowUpRight className="w-4 h-4" /> : <ArrowDownRight className="w-4 h-4" />}
                {isMtmPositive ? '+' : ''}₹{mtm.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
            </div>

            <div className="text-right">
              <span className="text-xs text-gray-400">Net Liquidation</span>
              <div className="text-xl font-mono font-bold text-white">
                ₹{(portfolio?.net_liquidation_value || userCapital).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
            </div>

            <div className="text-right">
              <span className="text-xs text-gray-400">Win Rate</span>
              <div className="text-xl font-mono font-bold text-blue-400">
                {(portfolio?.win_rate || 0).toFixed(1)}%
              </div>
            </div>
          </div>
        </div>

        {/* Active Open Positions Mini-Table */}
        {portfolio?.open_trades && portfolio.open_trades.length > 0 ? (
          <div>
            <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 flex items-center justify-between">
              <span>Active Live Derivative & Equity Positions ({portfolio.open_trades.length})</span>
              <span className="text-emerald-400">Ticking Real-Time</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs min-w-[850px]">
                <thead>
                  <tr className="border-b border-gray-800 text-gray-500 uppercase">
                    <th className="py-1.5 px-3">Contract / Symbol</th>
                    <th className="py-1.5 px-3">Type</th>
                    <th className="py-1.5 px-3">Direction</th>
                    <th className="py-1.5 px-3 text-right">Entry Prem / Price</th>
                    <th className="py-1.5 px-3 text-right">Live LTP</th>
                    <th className="py-1.5 px-3 text-right">Quantity (Lots)</th>
                    <th className="py-1.5 px-3 text-right">Invested</th>
                    <th className="py-1.5 px-3 text-right">Live MTM PnL</th>
                    <th className="py-1.5 px-3 text-center">Greeks & Specs</th>
                    <th className="py-1.5 px-3 text-center">Chart</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800/60 font-mono">
                  {portfolio.open_trades.map((pos: any, idx: number) => {
                    const isShort = pos.action === 'SELL' || pos.direction === 'SELL' || pos.direction === 'SHORT' || isOptionSellingOrSpread(pos);
                    const isLong = !isShort && (pos.direction === 'LONG' || pos.direction === 'bullish' || pos.direction === 'BUY');
                    const posPnl = pos.unrealized_pnl || 0;
                    const posPositive = posPnl >= 0;
                    const isOption = pos.instrument_type === 'OPTION' || Boolean(pos.option_type) || Boolean(pos.opt_type);
                    const isFuture = pos.instrument_type === 'FUTURE' || pos.instrument_type === 'FUT';
                    const canonicalSymbol = pos.contract_symbol || formatContractSymbol(pos.ticker, pos.opt_strike || pos.strike, pos.opt_type || pos.option_type, pos.instrument_type);
                    const stratLabel = getOptionStrategyLabel(pos);

                    return (
                      <tr key={pos.id || idx} className="hover:bg-gray-800/40">
                        <td className="py-2 px-3">
                          <div className="font-bold text-white flex flex-wrap items-center gap-1.5">
                            {canonicalSymbol}
                            {isOption && (
                              <span className="text-[10px] text-purple-400 bg-purple-950/60 px-1 rounded">
                                {pos.strike_type || 'ATM'} (Δ {pos.delta || 0.5})
                              </span>
                            )}
                            {isShort && (
                              <span className="text-[9px] text-amber-300 bg-amber-950/80 border border-amber-700/80 px-1.5 py-0.2 rounded font-bold uppercase">
                                {stratLabel}
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="py-2 px-3">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                            isOption
                              ? (pos.option_type === 'CE' ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : 'bg-red-950 text-red-400 border border-red-800')
                              : isFuture
                                ? 'bg-amber-950 text-amber-400 border border-amber-800'
                                : 'bg-blue-950 text-blue-400 border border-blue-800'
                          }`}>
                            {pos.option_type || (isFuture ? 'FUT' : 'EQ')}
                          </span>
                        </td>
                        <td className="py-2 px-3">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase transition-colors ${
                            isShort
                              ? 'bg-amber-950/90 text-amber-300 border border-amber-700/80 shadow-sm'
                              : isLong
                                ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                                : 'bg-red-950 text-red-400 border border-red-800'
                          }`}>
                            {isShort ? 'SHORT / SELL' : pos.direction}
                          </span>
                        </td>
                        <td className="py-2 px-3 text-right text-gray-300">
                          <div>₹{Number(pos.entry_price || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}</div>
                          {isShort && pos.net_credit && (
                            <span className="text-[9px] text-emerald-400 block font-mono">Net Cr: ₹{pos.net_credit}</span>
                          )}
                        </td>
                        <td className="py-2 px-3 text-right font-bold text-white">
                          ₹{Number(pos.current_ltp || pos.entry_price || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                        </td>
                        <td className="py-2 px-3 text-right text-gray-300">
                          {pos.quantity} {pos.lots ? `(${pos.lots}L)` : ''}
                        </td>
                        <td className="py-2 px-3 text-right text-gray-300">
                          <div className="font-bold text-white">
                            ₹{Number(pos.invested || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                          </div>
                          <div className="text-[10px] text-gray-400">
                            {isShort ? 'Margin Blocked' : 'Premium Deployed'}
                          </div>
                        </td>
                        <td className={`py-2 px-3 text-right font-bold ${posPositive ? 'text-emerald-400' : 'text-red-400'}`}>
                          {posPositive ? '+' : ''}₹{posPnl.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                          <span className="text-[10px] ml-1 opacity-80">({pos.unrealized_pnl_pct?.toFixed(2)}%)</span>
                        </td>
                        <td className="py-2 px-3 text-center">
                          <button
                            type="button"
                            onClick={() => openTradeDossier(pos)}
                            className="px-2 py-1 bg-purple-950/70 hover:bg-purple-900 text-purple-200 border border-purple-800 rounded text-[11px] font-semibold transition-all inline-flex items-center gap-1 shadow-sm"
                            title="Inspect Complete F&O Trade Specifications & Greeks"
                          >
                            <Eye className="w-3 h-3 text-purple-400" />
                            Specs
                          </button>
                        </td>
                        <td className="py-2 px-3 text-center">
                          {isOption ? (
                            <button
                              type="button"
                              onClick={() => {
                                setFocusedOption({
                                  underlying: pos.underlying || (pos.ticker?.includes('BANK') ? 'BANKNIFTY' : pos.ticker?.includes('FIN') ? 'FINNIFTY' : 'NIFTY'),
                                  strike: Number(pos.strike || pos.opt_strike || 22800),
                                  optionType: (pos.option_type === 'PE' || pos.opt_type === 'PE' ? 'PE' : 'CE'),
                                  action: isShort ? 'SELL' : 'BUY',
                                  strategyType: pos.strategy_type || (isShort ? 'CREDIT_SPREAD' : 'DIRECTIONAL'),
                                  hedgeStrike: pos.hedge_strike_price,
                                  hedgePrice: pos.hedge_entry_price,
                                  netCredit: pos.net_credit,
                                  entryPrice: Number(pos.entry_price || 0),
                                  targetPrice: Number(pos.target || pos.tp || 0),
                                  stopLossPrice: Number(pos.stop_loss || pos.sl || 0),
                                });
                                setChartViewMode('option');
                              }}
                              className="px-2 py-1 bg-purple-900/60 hover:bg-purple-800 text-purple-200 border border-purple-700 rounded text-[11px] font-semibold transition-all inline-flex items-center gap-1 shadow-sm"
                              title="Inspect Option Candlestick Chart, VWAP & Greeks"
                            >
                              <Zap className="w-3 h-3 text-purple-400" />
                              Chart
                            </button>
                          ) : (
                            <button
                              type="button"
                              onClick={() => setChartViewMode('spot')}
                              className="px-2 py-1 bg-gray-800 hover:bg-gray-700 text-gray-300 border border-gray-700 rounded text-[11px] font-semibold transition-all inline-flex items-center gap-1"
                              title="Inspect Spot Chart"
                            >
                              <TrendingUp className="w-3 h-3 text-blue-400" />
                              Spot
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          <div className="text-xs text-gray-400 py-2 flex items-center gap-2">
            <Radio className="w-4 h-4 text-gray-500 animate-pulse" />
            No active positions open. Scanner evaluating {selectedIndex} setups sized for ₹{userCapital.toLocaleString('en-IN')} capital ({tierName} Tier).
          </div>
        )}

        {/* Closed Trades & Reinforcement Learning History Table */}
        {portfolio?.closed_trades && portfolio.closed_trades.length > 0 && (
          <div className="mt-6 border-t border-gray-800 pt-4">
            <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-gray-300">
                <History className="w-3.5 h-3.5 text-blue-400" />
                Closed Derivative Trades & RL Learning History ({portfolio.closed_trades.length})
              </span>
              <span className="text-gray-500 font-mono text-[11px]">Last 50 Trades</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs min-w-[850px]">
                <thead>
                  <tr className="border-b border-gray-800 text-gray-500 uppercase">
                    <th className="py-1.5 px-3">Contract / Symbol</th>
                    <th className="py-1.5 px-3">Type</th>
                    <th className="py-1.5 px-3">Direction</th>
                    <th className="py-1.5 px-3 text-right">Entry</th>
                    <th className="py-1.5 px-3 text-right">Exit</th>
                    <th className="py-1.5 px-3 text-center">Exit Reason</th>
                    <th className="py-1.5 px-3 text-right">Realized PnL</th>
                    <th className="py-1.5 px-3 text-center">Specifications</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800/60 font-mono">
                  {portfolio.closed_trades.slice().reverse().map((trade: any, idx: number) => {
                    const isWin = (trade.cash_pnl || 0) > 0;
                    const isTradeShort = trade.action === 'SELL' || trade.direction === 'SHORT' || trade.direction === 'SELL' || isOptionSellingOrSpread(trade);
                    const isTradeLong = !isTradeShort && (trade.direction === 'BUY' || trade.direction === 'LONG' || trade.direction === 'bullish');
                    const isOption = trade.instrument_type === 'OPTION' || Boolean(trade.option_type) || Boolean(trade.opt_type);
                    const isFuture = trade.instrument_type === 'FUTURE' || trade.instrument_type === 'FUT';
                    const canonicalSymbol = trade.contract_symbol || formatContractSymbol(trade.ticker, trade.opt_strike || trade.strike, trade.opt_type || trade.option_type, trade.instrument_type);
                    const stratLabel = getOptionStrategyLabel(trade);
                    return (
                      <tr key={trade.id || idx} className="hover:bg-gray-800/40">
                        <td className="py-2 px-3">
                          <div className="font-bold text-white flex flex-wrap items-center gap-1.5">
                            {canonicalSymbol}
                            {isOption && trade.strike_type && (
                              <span className="text-[10px] text-purple-400 bg-purple-950/60 px-1 rounded">
                                {trade.strike_type}
                              </span>
                            )}
                            {isTradeShort && (
                              <span className="text-[9px] text-amber-300 bg-amber-950/80 border border-amber-700/80 px-1.5 py-0.2 rounded font-bold uppercase">
                                {stratLabel}
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="py-2 px-3">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                            isOption
                              ? (trade.option_type === 'CE' ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : 'bg-red-950 text-red-400 border border-red-800')
                              : isFuture
                                ? 'bg-amber-950 text-amber-400 border border-amber-800'
                                : 'bg-blue-950 text-blue-400 border border-blue-800'
                          }`}>
                            {trade.option_type || (isFuture ? 'FUT' : 'EQ')}
                          </span>
                        </td>
                        <td className="py-2 px-3">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase transition-colors ${
                            isTradeShort
                              ? 'bg-amber-950/90 text-amber-300 border border-amber-700/80 shadow-sm'
                              : isTradeLong
                                ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                                : 'bg-red-950 text-red-400 border border-red-800'
                          }`}>
                            {isTradeShort ? 'SHORT / SELL' : trade.direction}
                          </span>
                        </td>
                        <td className="py-2 px-3 text-right text-gray-300">
                          ₹{Number(trade.entry_price || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                        </td>
                        <td className="py-2 px-3 text-right font-bold text-white">
                          ₹{Number(trade.exit_price || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                        </td>
                        <td className="py-2 px-3 text-center">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                            trade.status === 'TAKE_PROFIT'
                              ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                              : trade.status === 'TRAILING_SL'
                                ? 'bg-blue-950 text-blue-400 border border-blue-800'
                                : 'bg-red-950 text-red-400 border border-red-800'
                          }`}>
                            {(trade.status || 'CLOSED').replace(/_/g, ' ')}
                          </span>
                        </td>
                        <td className={`py-2 px-3 text-right font-bold ${isWin ? 'text-emerald-400' : 'text-red-400'}`}>
                          {isWin ? '+' : ''}₹{Number(trade.cash_pnl || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                          <span className="text-[10px] ml-1 opacity-80">
                            ({(Number(trade.pnl_pct || 0) * 100).toFixed(2)}%)
                          </span>
                        </td>
                        <td className="py-2 px-3 text-center">
                          <button
                            type="button"
                            onClick={() => openTradeDossier(trade)}
                            className="px-2 py-1 bg-gray-800 hover:bg-gray-700 text-gray-200 border border-gray-700 rounded text-[11px] font-semibold transition-all inline-flex items-center gap-1 shadow-sm"
                            title="Inspect Complete Trade Specifications & Greeks"
                          >
                            <Eye className="w-3 h-3 text-blue-400" />
                            Specs
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>
      </ErrorBoundary>

      {/* Real-Time Option Candlestick & Spot Chart Surface */}
      <ErrorBoundary compact title="Market Charts Viewer Error">
        <section className="mb-6 rounded-xl border border-gray-800 bg-gray-900/70 p-4 shadow-xl">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-800 pb-3 mb-4">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-purple-950 border border-purple-800 flex items-center justify-center text-purple-400">
              <Zap className="w-4 h-4" />
            </div>
            <div>
              <span className="eyebrow">Real-Time Market Charts</span>
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                {chartViewMode === 'option' ? 'Option Premium Candlestick & VWAP Chart' : 'Underlying Spot Chart (Live Feed)'}
                <span className="text-xs px-2 py-0.5 rounded bg-emerald-950 border border-emerald-800 text-emerald-400 font-normal">
                  Live Market Analysis
                </span>
              </h3>
            </div>
          </div>

          {/* Toggle between Option Chart and Underlying Spot Chart */}
          <div className="flex items-center gap-1 bg-gray-950 p-1 rounded-lg border border-gray-800">
            <button
              type="button"
              onClick={() => setChartViewMode('option')}
              className={`px-3 py-1.5 text-xs font-semibold rounded-md flex items-center gap-1.5 transition-all ${
                chartViewMode === 'option'
                  ? 'bg-purple-600 text-white shadow-md shadow-purple-600/30'
                  : 'text-gray-400 hover:text-white'
              }`}
            >
              <Zap className="w-3.5 h-3.5" />
              Option Premium & Greeks Chart
            </button>
            <button
              type="button"
              onClick={() => setChartViewMode('spot')}
              className={`px-3 py-1.5 text-xs font-semibold rounded-md flex items-center gap-1.5 transition-all ${
                chartViewMode === 'spot'
                  ? 'bg-blue-600 text-white shadow-md shadow-blue-600/30'
                  : 'text-gray-400 hover:text-white'
              }`}
            >
              <TrendingUp className="w-3.5 h-3.5" />
              Underlying Spot Chart
            </button>
          </div>
        </div>

        {chartViewMode === 'option' ? (
          <OptionChartViewer
            initialUnderlying={focusedOption?.underlying || (selectedIndex === 'SENSEX' ? 'SENSEX' : selectedIndex === 'BANKNIFTY' ? 'BANKNIFTY' : selectedIndex === 'FINNIFTY' ? 'FINNIFTY' : 'NIFTY')}
            initialStrike={focusedOption?.strike || (selectedIndex === 'SENSEX' ? 80000 : selectedIndex === 'BANKNIFTY' ? 52000 : selectedIndex === 'FINNIFTY' ? 23500 : 24500)}
            initialOptionType={focusedOption?.optionType || 'CE'}
            initialAction={focusedOption?.action}
            strategyType={focusedOption?.strategyType}
            hedgeStrike={focusedOption?.hedgeStrike}
            hedgePrice={focusedOption?.hedgePrice}
            netCredit={focusedOption?.netCredit}
            entryPrice={focusedOption?.entryPrice}
            targetPrice={focusedOption?.targetPrice}
            stopLossPrice={focusedOption?.stopLossPrice}
            height={360}
          />
        ) : (
          <div className="h-[420px] rounded-lg overflow-hidden border border-gray-800">
            <TradingViewWidget
              symbol={selectedIndex === 'SENSEX' ? 'BSE:SENSEX' : selectedIndex === 'BANKNIFTY' ? 'NSE:BANKNIFTY' : selectedIndex === 'FINNIFTY' ? 'NSE:FINNIFTY' : 'NSE:NIFTY'}
              height={420}
            />

          </div>
        )}
      </section>
      </ErrorBoundary>

      {/* Command Control Bar */}
      <ErrorBoundary compact title="Execution Controller Error">
        <section className="training-command-bar">
        <div className="training-command-copy">
          <div className="training-icon"><BrainCircuit /></div>
          <div>
            <span className="eyebrow">Execution Controller</span>
            <h2>{isTraining ? `Training Active in ${trainingMode} Mode` : `Ready to Trade with ₹${userCapital.toLocaleString('en-IN')}`}</h2>
            <p>
              {isTraining
                ? (trainingMode === 'LIVE_MARKET' || trainingMode === 'SIMULATED_LIVE'
                    ? `Taking live F&O paper trades in ${selectedIndex} (${selectedDerivative}), monitoring real-time MTM, and adapting RL weights.`
                    : 'NSE market is closed. Training on historical backdata & AlphaZero replay engine.')
                : (isMarketOpen
                    ? `Market is OPEN! Starting will execute live F&O paper trades for ₹${userCapital.toLocaleString('en-IN')} and learn in real time.`
                    : `Market is CLOSED. Starting will run offline historical training and auto-engage live F&O trading for ₹${userCapital.toLocaleString('en-IN')} at 09:15 AM IST.`)}
            </p>
          </div>
        </div>

        <div className="training-actions flex items-center gap-3">
          {!isTraining && (
            <div className="flex flex-col">
              <label htmlFor="mode-select" className="text-[11px] text-gray-400 uppercase font-semibold mb-1">
                Execution Mode
              </label>
              <select
                id="mode-select"
                value={selectedStartMode}
                onChange={e => setSelectedStartMode(e.target.value)}
                className="bg-gray-800 text-gray-200 text-xs px-3 py-2 rounded-lg border border-gray-700 focus:outline-none focus:border-blue-500"
              >
                <option value="auto">Auto (Live in Market Hours, Replay when Closed)</option>
                <option value="simulate_live">Force Live Simulation (Trade Live Now)</option>
                <option value="offline_only">Offline Historical Replay Only</option>
              </select>
            </div>
          )}

          {isTraining ? (
            <button
              type="button"
              className="px-5 py-2.5 bg-red-600 hover:bg-red-500 text-white text-xs font-bold rounded-lg flex items-center gap-2 transition-all shadow-md shadow-red-600/30"
              onClick={handleStop}
              disabled={actionPending}
            >
              <Square className="w-4 h-4 fill-white" /> Stop Trading
            </button>
          ) : (
            <button
              type="button"
              className="px-5 py-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-700 disabled:cursor-not-allowed text-white text-xs font-bold rounded-lg flex items-center gap-2 transition-all shadow-md shadow-emerald-600/30"
              onClick={handleStart}
              disabled={actionPending || !!capitalError || !Number.isFinite(userCapital) || userCapital < 1000}
            >
              <Play className="w-4 h-4 fill-white" /> Start Trading & Learning
            </button>
          )}

          <button
            type="button"
            className="p-2.5 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg border border-gray-700"
            onClick={() => void fetchStatus(true)}
            title="Refresh status"
          >
            <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </section>
      </ErrorBoundary>

      {error && (
        <div className="training-banner error mb-4">
          {error}
        </div>
      )}

      {/* Metric Tiles */}
      <ErrorBoundary compact title="Training Metrics Error">
        <section className="training-metrics-grid">
        <div className="training-metric-card">
          <div className="metric-header">
            <span className="eyebrow">Cycles Completed</span>
            <Activity className="w-4 h-4 text-blue-400" />
          </div>
          <div className="metric-value font-mono">{cycles}</div>
          <span className="metric-subtitle">Live scans & updates executed</span>
        </div>

        <div className="training-metric-card">
          <div className="metric-header">
            <span className="eyebrow">Total Closed Trades</span>
            <Layers className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="metric-value font-mono">{portfolio?.closed_trades_count || 0}</div>
          <span className="metric-subtitle">{portfolio?.win_rate || 0}% Win Rate</span>
        </div>

        <div className="training-metric-card">
          <div className="metric-header">
            <span className="eyebrow">Realized PnL</span>
            <Wallet className="w-4 h-4 text-purple-400" />
          </div>
          <div className={`metric-value font-mono ${
            (portfolio?.total_realized_pnl || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'
          }`}>
            {(portfolio?.total_realized_pnl || 0) >= 0 ? '+' : ''}₹{(portfolio?.total_realized_pnl || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
          </div>
          <span className="metric-subtitle">{(portfolio?.total_realized_pnl_pct || 0).toFixed(2)}% net wallet return</span>
        </div>

        <div className="training-metric-card">
          <div className="metric-header">
            <span className="eyebrow">Current Target & F&O</span>
            <Compass className="w-4 h-4 text-amber-400" />
          </div>
          <div className="metric-value text-sm font-bold text-white mt-1">
            {selectedIndex} ({selectedDerivative})
          </div>
          <span className="metric-subtitle text-[11px]">
            Pref: {selectedStrikePref} | Ticking Real-Time
          </span>
        </div>
      </section>
      </ErrorBoundary>

      {/* Historical Replay & Neural Training Telemetry Surface */}
      {replayTelemetry && (
        <ErrorBoundary compact title="Historical Replay Telemetry Error">
          <section className="mb-6 p-4 rounded-xl border border-gray-800 bg-gray-900/60 shadow-lg">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-800 pb-3 mb-3">
              <div className="flex items-center gap-2">
                <BrainCircuit className="w-4 h-4 text-purple-400" />
                <span className="text-xs font-semibold text-gray-300 uppercase tracking-wider">
                  Offline Historical Replay &amp; Path-Dependent Simulation
                </span>
              </div>
              <span className="text-[11px] text-gray-500 font-mono">
                Cycle Updated: {replayTelemetry.last_updated}
              </span>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-3 text-xs font-mono">
              <div className="p-2.5 rounded bg-gray-950/70 border border-gray-800">
                <span className="text-gray-500 block text-[10px] uppercase">Replay Target</span>
                <strong className="text-white text-sm">{replayTelemetry.target}</strong>
                <span className="text-[10px] text-gray-400 block">{replayTelemetry.timeframe} timeframe</span>
              </div>
              <div className="p-2.5 rounded bg-gray-950/70 border border-gray-800">
                <span className="text-gray-500 block text-[10px] uppercase">Simulated Trades</span>
                <strong className="text-blue-400 text-sm">{replayTelemetry.total_simulated?.toLocaleString()}</strong>
                <span className="text-[10px] text-gray-400 block">Path-dependent</span>
              </div>
              <div className="p-2.5 rounded bg-gray-950/70 border border-gray-800">
                <span className="text-gray-500 block text-[10px] uppercase">Simulation Win Rate</span>
                <strong className="text-emerald-400 text-sm">{replayTelemetry.win_rate}%</strong>
                <span className="text-[10px] text-gray-400 block">{replayTelemetry.wins}W / {replayTelemetry.losses}L</span>
              </div>
              <div className="p-2.5 rounded bg-gray-950/70 border border-gray-800">
                <span className="text-gray-500 block text-[10px] uppercase">Timeouts (No Hit)</span>
                <strong className="text-gray-300 text-sm">{replayTelemetry.timeouts?.toLocaleString()}</strong>
                <span className="text-[10px] text-gray-400 block">Max hold expired</span>
              </div>
              <div className="p-2.5 rounded bg-gray-950/70 border border-gray-800">
                <span className="text-gray-500 block text-[10px] uppercase">Target / Stop ATR</span>
                <strong className="text-amber-400 text-sm">+{replayTelemetry.tp_atr} / -{replayTelemetry.sl_atr} ATR</strong>
                <span className="text-[10px] text-gray-400 block">Triple-barrier</span>
              </div>
              <div className="p-2.5 rounded bg-gray-950/70 border border-gray-800">
                <span className="text-gray-500 block text-[10px] uppercase">Max Hold Horizon</span>
                <strong className="text-purple-400 text-sm">{replayTelemetry.max_hold} bars</strong>
                <span className="text-[10px] text-gray-400 block">Time barrier</span>
              </div>
            </div>
          </section>
        </ErrorBoundary>
      )}

      {/* Terminal Logs Console */}
      <ErrorBoundary compact title="Autonomous Terminal Stream Error">
        <section className="training-terminal-section">
        <div className="terminal-header flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Terminal className="w-4 h-4 text-emerald-400" />
            <span className="font-mono text-xs text-gray-300">live_market_learner.log</span>
            <span className="text-[10px] text-gray-500 font-mono">
              ({logs.length} lines{logs.length > visibleLogs.length ? `, showing latest ${visibleLogs.length}` : ''})
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-3 text-xs">
            {/* Search filter */}
            <div className="flex items-center gap-1 bg-gray-900 border border-gray-800 px-2 py-0.5 rounded text-[11px]">
              <Search className="w-3 h-3 text-gray-500" />
              <input
                type="text"
                placeholder="Filter logs..."
                value={logFilter}
                onChange={e => setLogFilter(e.target.value)}
                aria-label="Filter terminal logs"
                className="bg-transparent border-none text-gray-300 placeholder-gray-600 text-[11px] focus:outline-none w-24 sm:w-32"
              />
              {logFilter && (
                <button
                  type="button"
                  onClick={() => setLogFilter('')}
                  aria-label="Clear filter"
                  className="text-gray-500 hover:text-white text-[10px]"
                >
                  ✕
                </button>
              )}
            </div>

            {/* Display limit buttons */}
            <div className="flex items-center gap-1 bg-gray-900 border border-gray-800 p-0.5 rounded text-[10px] font-mono">
              {[
                { label: '300', n: 300 },
                { label: '1k', n: 1000 },
                { label: 'All', n: 0 },
              ].map(opt => (
                <button
                  key={opt.label}
                  type="button"
                  onClick={() => setLogDisplayCount(opt.n)}
                  className={`px-1.5 py-0.5 rounded ${
                    logDisplayCount === opt.n ? 'bg-blue-600 text-white font-bold' : 'text-gray-400 hover:text-white'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>

            <label className="flex items-center gap-1.5 cursor-pointer text-gray-400">
              <input
                type="checkbox"
                checked={autoScroll}
                onChange={e => setAutoScroll(e.target.checked)}
                className="rounded border-gray-700 bg-gray-800 text-blue-500 text-xs"
              />
              Auto-scroll
            </label>
            <button
              type="button"
              onClick={() => setLogs([])}
              className="text-[11px] text-gray-500 hover:text-gray-300 underline"
            >
              Clear
            </button>
          </div>
        </div>

        <div
          ref={logsContainerRef}
          onScroll={handleScroll}
          className="terminal-body font-mono text-xs overflow-y-auto max-h-[380px] p-4 bg-gray-950 text-gray-300"
        >
          {visibleLogs.length === 0 ? (
            <div className="text-gray-600 italic py-8 text-center">
              {logs.length === 0
                ? 'No training events recorded yet. Click "Start Trading & Learning" to begin.'
                : 'No log lines match current filter.'}
            </div>
          ) : (
            visibleLogs.map((logLine, index) => {
              const isError = logLine.includes('🛑') || logLine.includes('ERROR') || logLine.includes('REJECTED');
              const isSuccess = logLine.includes('✅') || logLine.includes('CLOSED') || logLine.includes('Checkpoint');
              const isEntry = logLine.includes('ENTRY');
              const isMtm = logLine.includes('MTM TICK');
              const isDeriv = logLine.includes('F&O') || logLine.includes('DERIVATIVE');

              return (
                <div
                  key={`${index}-${logLine.slice(0, 20)}`}
                  className={`py-0.5 leading-relaxed ${
                    isError
                      ? 'text-red-400'
                      : isSuccess
                        ? 'text-emerald-400 font-semibold'
                        : isEntry
                          ? 'text-blue-300 font-semibold'
                          : isDeriv
                            ? 'text-purple-300 font-semibold'
                            : isMtm
                              ? 'text-amber-300/90'
                              : 'text-gray-300'
                  }`}
                >
                  {logLine}
                </div>
              );
            })
          )}
          <div ref={logsEndRef} />
        </div>
      </section>
      </ErrorBoundary>

      {/* Complete Trade Specification Dossier Modal */}
      {inspectedTrade && (() => {
        const isTradeSeller = inspectedTrade.action === 'SELL' || isOptionSellingOrSpread(inspectedTrade);
        const isTradeSpread = inspectedTrade.strategy_type?.includes('SPREAD') || inspectedTrade.instrument_type === 'SPREAD' || Boolean(inspectedTrade.hedge_strike_price);
        const tradeStratLabel = getOptionStrategyLabel(inspectedTrade);
        const isTradeOpt = inspectedTrade.instrument_type === 'OPTION' || Boolean(inspectedTrade.option_type) || Boolean(inspectedTrade.opt_type);
        const dossierPayoff = isTradeOpt || isTradeSeller
          ? calculateOptionPayoffProfile({
              underlying: inspectedTrade.underlying_ticker || inspectedTrade.underlying || inspectedTrade.ticker,
              strike: Number(inspectedTrade.strike || inspectedTrade.opt_strike || 22800),
              optionType: inspectedTrade.option_type || inspectedTrade.opt_type || 'CE',
              entryPrice: Number(inspectedTrade.entry_price || 0),
              currentSpot: Number(inspectedTrade.current_spot || inspectedTrade.entry_spot || inspectedTrade.strike || 0),
              action: isTradeSeller ? 'SELL' : 'BUY',
              strategyType: inspectedTrade.strategy_type || (isTradeSpread ? 'CREDIT_SPREAD' : isTradeSeller ? 'WRITING' : 'DIRECTIONAL'),
              hedgeStrike: inspectedTrade.hedge_strike_price,
              hedgePrice: inspectedTrade.hedge_entry_price,
              lotSize: inspectedTrade.lot_size || getExchangeLotSize(inspectedTrade.underlying_ticker || inspectedTrade.ticker),
              quantity: inspectedTrade.quantity,
              rawTheta: inspectedTrade.theta || inspectedTrade.opt_theta,
            })
          : null;

        return (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-fadeIn"
            role="dialog"
            aria-modal="true"
            aria-labelledby="dossier-modal-title"
            onClick={e => {
              if (e.target === e.currentTarget) closeTradeDossier();
            }}
          >
            <div
              ref={modalRef}
              tabIndex={-1}
              className="bg-gray-900 border border-gray-700 rounded-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto shadow-2xl p-6 text-gray-200 focus:outline-none"
            >
              {/* Modal Header */}
              <div className="flex items-start justify-between border-b border-gray-800 pb-4 mb-4">
                <div>
                  <div className="flex flex-wrap items-center gap-2 mb-1">
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                      isTradeOpt
                        ? (inspectedTrade.option_type === 'CE' ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : 'bg-red-950 text-red-400 border border-red-800')
                        : 'bg-amber-950 text-amber-400 border border-amber-800'
                    }`}>
                      {inspectedTrade.instrument_type || 'DERIVATIVE'} {inspectedTrade.option_type || ''}
                    </span>
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                      isTradeSeller
                        ? 'bg-amber-950/90 text-amber-300 border border-amber-700/80 shadow-sm'
                        : 'bg-blue-950/90 text-blue-300 border border-blue-700/80'
                    }`}>
                      {isTradeSeller ? 'SHORT / SELL' : 'LONG / BUY'}
                    </span>
                    {(isTradeSpread || isTradeSeller) && (
                      <span className="text-[10px] bg-rose-950 text-rose-300 border border-rose-800 px-2 py-0.5 rounded font-bold uppercase">
                        {tradeStratLabel}
                      </span>
                    )}
                    {inspectedTrade.strike_type && (
                      <span className="text-[10px] bg-purple-950 text-purple-300 border border-purple-800 px-2 py-0.5 rounded font-bold">
                        {inspectedTrade.strike_type}
                      </span>
                    )}
                    <span className={`text-[10px] px-2 py-0.5 rounded font-bold uppercase ${
                      inspectedTrade.status === 'OPEN'
                        ? 'bg-blue-950 text-blue-400 border border-blue-800 animate-pulse'
                        : inspectedTrade.status === 'TAKE_PROFIT'
                          ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                          : inspectedTrade.status === 'TRAILING_SL'
                            ? 'bg-blue-950 text-blue-400 border border-blue-800'
                            : 'bg-red-950 text-red-400 border border-red-800'
                    }`}>
                      {(inspectedTrade.status || 'ACTIVE').replace(/_/g, ' ')}
                    </span>
                  </div>
                  <h3 id="dossier-modal-title" className="text-xl font-bold text-white flex items-center gap-2">
                    {inspectedTrade.contract_symbol || inspectedTrade.ticker}
                  </h3>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Underlying: <span className="text-white font-semibold">{inspectedTrade.underlying_ticker || inspectedTrade.underlying || inspectedTrade.ticker}</span> • 
                    Direction: <span className={isTradeSeller ? 'text-amber-300 font-bold' : 'text-emerald-400 font-bold'}>{isTradeSeller ? 'SELL (Short)' : inspectedTrade.direction}</span>
                  </p>
                </div>
                <button
                  ref={modalCloseBtnRef}
                  type="button"
                  onClick={closeTradeDossier}
                  aria-label="Close Trade Dossier"
                  className="p-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-white transition focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              {/* Grid 1: Execution & Capital Specifications */}
              <div className="mb-4">
                <span className="text-[11px] font-bold text-gray-400 uppercase tracking-wider block mb-2">
                  1. Execution &amp; Capital Specifications
                </span>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-xs font-mono">
                  <div className="p-3 bg-gray-950/80 rounded-lg border border-gray-800">
                    <span className="text-gray-400 block text-[10px] uppercase font-semibold">
                      {isTradeSeller ? 'Premium Collected (Credit)' : 'Entry Premium/Price'}
                    </span>
                    <strong className="text-white text-sm">{formatIndianCurrency(inspectedTrade.entry_price || 0)}</strong>
                    {inspectedTrade.net_credit && (
                      <span className="text-[10px] text-emerald-400 block font-mono">Net: ₹{inspectedTrade.net_credit}/sh</span>
                    )}
                  </div>
                  <div className="p-3 bg-gray-950/80 rounded-lg border border-gray-800">
                    <span className="text-gray-400 block text-[10px] uppercase font-semibold">{inspectedTrade.status === 'OPEN' ? 'Live LTP' : 'Exit Price'}</span>
                    <strong className="text-white text-sm">{formatIndianCurrency(inspectedTrade.exit_price || inspectedTrade.current_ltp || inspectedTrade.entry_price || 0)}</strong>
                  </div>
                  <div className="p-3 bg-gray-950/80 rounded-lg border border-gray-800">
                    <span className="text-gray-400 block text-[10px] uppercase font-semibold">Quantity Traded</span>
                    <strong className="text-white text-sm">{inspectedTrade.quantity} ({inspectedTrade.lots || Math.max(1, Math.round(inspectedTrade.quantity / getExchangeLotSize(inspectedTrade.underlying_ticker || inspectedTrade.ticker)))} Lots)</strong>
                    <span className="text-[10px] text-gray-400 block">Lot Size: {inspectedTrade.lot_size || getExchangeLotSize(inspectedTrade.underlying_ticker || inspectedTrade.ticker)} Qty</span>
                  </div>
                  <div className="p-3 bg-gray-950/80 rounded-lg border border-gray-800">
                    <span className="text-gray-400 block text-[10px] uppercase font-semibold">
                      {isTradeSeller ? 'Margin Required (Blocked)' : 'Capital Deployed'}
                    </span>
                    <strong className="text-purple-400 text-sm">{formatIndianCurrency(inspectedTrade.invested || 0)}</strong>
                    <span className="text-[10px] text-gray-400 block">
                      {isTradeSpread ? 'Defined Spread Risk' : isTradeSeller ? 'SPAN + Exposure Margin' : 'Capped Premium Risk'}
                    </span>
                  </div>
                </div>
              </div>

              {/* Breakeven & Payoff Representation Card for Options & Spreads */}
              {dossierPayoff && (
                <div className="mb-4 p-3.5 bg-gray-950/90 rounded-xl border border-gray-800 font-mono text-xs">
                  <span className="text-[11px] font-bold text-gray-400 uppercase tracking-wider block mb-2 font-sans">
                    Payoff &amp; Breakeven Mechanics ({tradeStratLabel})
                  </span>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
                    <div className="p-2.5 bg-gray-900/90 rounded border border-gray-800">
                      <span className="text-gray-400 block text-[10px] uppercase font-bold">Breakeven Spot</span>
                      <strong className="text-amber-400 text-sm">
                        ₹{dossierPayoff.breakeven.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                      </strong>
                      <span className="text-[9px] text-gray-400 block mt-0.5">
                        {dossierPayoff.safetyBufferPct}% margin to spot
                      </span>
                    </div>
                    <div className="p-2.5 bg-gray-900/90 rounded border border-gray-800">
                      <span className="text-gray-400 block text-[10px] uppercase font-bold">Max Profit</span>
                      <strong className="text-emerald-400 text-sm">
                        +{formatIndianCurrency(dossierPayoff.maxProfit)}
                      </strong>
                      <span className="text-[9px] text-emerald-400 block mt-0.5">
                        {isTradeSeller ? 'Net credit capped' : 'Unlimited'}
                      </span>
                    </div>
                    <div className="p-2.5 bg-gray-900/90 rounded border border-gray-800">
                      <span className="text-gray-400 block text-[10px] uppercase font-bold">Max Risk</span>
                      <strong className="text-red-400 text-sm">
                        -{formatIndianCurrency(dossierPayoff.maxLoss)}
                      </strong>
                      <span className="text-[9px] text-gray-400 block mt-0.5">
                        {isTradeSpread ? 'Hedged wing barrier' : 'SL controlled'}
                      </span>
                    </div>
                    <div className="p-2.5 bg-gray-900/90 rounded border border-gray-800">
                      <span className="text-gray-400 block text-[10px] uppercase font-bold">Risk-to-Reward</span>
                      <strong className="text-blue-400 text-sm">
                        {dossierPayoff.riskRewardRatio != null ? `1 : ${dossierPayoff.riskRewardRatio}` : 'N/A'}
                      </strong>
                      <span className="text-[9px] text-gray-400 block mt-0.5">
                        {isTradeSeller ? 'High POP setup' : 'Asymmetric setup'}
                      </span>
                    </div>
                  </div>
                </div>
              )}

              {/* Grid 2: Risk Management & PnL */}
              <div className="mb-4">
                <span className="text-[11px] font-bold text-gray-400 uppercase tracking-wider block mb-2">
                  2. Risk Envelope &amp; Asymmetric Barriers
                </span>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-xs font-mono">
                  <div className="p-3 bg-gray-950/80 rounded-lg border border-gray-800">
                    <span className="text-gray-400 block text-[10px] uppercase font-semibold">Target Price (TP)</span>
                    <strong className="text-emerald-400 text-sm">₹{Number(inspectedTrade.tp || inspectedTrade.target || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}</strong>
                    <span className="text-[10px] text-emerald-400 block">{isTradeSeller ? 'Decay Target' : '2.0× ATR Barrier'}</span>
                  </div>
                  <div className="p-3 bg-gray-950/80 rounded-lg border border-gray-800">
                    <span className="text-gray-400 block text-[10px] uppercase font-semibold">Stop Loss (SL)</span>
                    <strong className="text-red-400 text-sm">₹{Number(inspectedTrade.sl || inspectedTrade.stop_loss || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}</strong>
                    <span className="text-[10px] text-red-400 block">1.0× ATR Barrier</span>
                  </div>
                  <div className="p-3 bg-gray-950/80 rounded-lg border border-gray-800">
                    <span className="text-gray-400 block text-[10px] uppercase font-semibold">Trailing Ratchet</span>
                    <strong className="text-blue-400 text-sm">₹{Number(inspectedTrade.trailing_stop || inspectedTrade.sl || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}</strong>
                    <span className="text-[10px] text-gray-400 block">Breakeven Lock</span>
                  </div>
                  <div className="p-3 bg-gray-950/80 rounded-lg border border-gray-800">
                    <span className="text-gray-400 block text-[10px] uppercase font-semibold">{inspectedTrade.status === 'OPEN' ? 'Unrealized MTM' : 'Realized PnL'}</span>
                    <strong className={`text-sm ${
                      Number(inspectedTrade.cash_pnl || inspectedTrade.unrealized_pnl || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'
                    }`}>
                      {Number(inspectedTrade.cash_pnl || inspectedTrade.unrealized_pnl || 0) >= 0 ? '+' : ''}₹{Number(inspectedTrade.cash_pnl || inspectedTrade.unrealized_pnl || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                    </strong>
                    <span className="text-[10px] opacity-80 block">
                      {Number(inspectedTrade.pnl_pct ? inspectedTrade.pnl_pct * 100 : inspectedTrade.unrealized_pnl_pct || 0).toFixed(2)}% net
                    </span>
                  </div>
                </div>
              </div>

              {/* Grid 3: F&O Greeks & Black-Scholes Analytics */}
              <div className="mb-4">
                <span className="text-[11px] font-bold text-gray-400 uppercase tracking-wider block mb-2">
                  3. Full Option Greeks &amp; Black-Scholes Derivatives Metrics
                </span>
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 text-xs font-mono">
                  <div className="p-2.5 bg-gray-950/80 rounded border border-gray-800 text-center">
                    <span className="text-gray-400 block text-[10px]">Delta (Δ)</span>
                    <strong className="text-blue-400 text-sm">{Number(inspectedTrade.delta || 0.5).toFixed(3)}</strong>
                    <span className="text-[10px] text-gray-400 block">{inspectedTrade.direction} exposure</span>
                  </div>

                  {/* Positive Theta notation for sellers */}
                  <div className="p-2.5 bg-gray-950/80 rounded border border-gray-800 text-center">
                    <span className={`block text-[10px] font-bold ${isTradeSeller ? 'text-emerald-400' : 'text-gray-400'}`}>
                      {isTradeSeller ? 'Theta Gain (Θ)' : 'Theta Decay (Θ)'}
                    </span>
                    <strong className={`text-sm ${isTradeSeller ? 'text-emerald-400 font-bold' : 'text-amber-400'}`}>
                      {isTradeSeller ? '+' : ''}{formatIndianCurrency(isTradeSeller ? Math.abs(inspectedTrade.theta || -12.50) : (inspectedTrade.theta || -12.50))}
                    </strong>
                    <span className={`text-[10px] block font-semibold ${isTradeSeller ? 'text-emerald-400' : 'text-gray-400'}`}>
                      {isTradeSeller ? '/day decay profit' : '/day time decay'}
                    </span>
                  </div>

                  <div className="p-2.5 bg-gray-950/80 rounded border border-gray-800 text-center">
                    <span className="text-gray-400 block text-[10px]">Gamma (Γ)</span>
                    <strong className="text-indigo-400 text-sm">{Number(inspectedTrade.gamma || 0.0012).toFixed(4)}</strong>
                    <span className="text-[10px] text-gray-400 block">Delta acceleration</span>
                  </div>
                  <div className="p-2.5 bg-gray-950/80 rounded border border-gray-800 text-center">
                    <span className="text-gray-400 block text-[10px]">Vega (ν)</span>
                    <strong className="text-emerald-400 text-sm">{formatIndianCurrency(inspectedTrade.vega || 14.20)}</strong>
                    <span className="text-[10px] text-gray-400 block">/ 1% IV shift</span>
                  </div>
                  <div className="p-2.5 bg-gray-950/80 rounded border border-gray-800 text-center">
                    <span className="text-gray-400 block text-[10px]">Implied Vol (IV)</span>
                    <strong className="text-purple-400 text-sm">{(Number(inspectedTrade.iv || 0.15) * 100).toFixed(1)}%</strong>
                    <span className="text-[10px] text-gray-400 block">Annualized IV</span>
                  </div>
                  <div className="p-2.5 bg-gray-950/80 rounded border border-gray-800 text-center">
                    <span className="text-gray-400 block text-[10px]">Spot Reference</span>
                    <strong className="text-white text-sm">{formatIndianCurrency(inspectedTrade.entry_spot || inspectedTrade.current_spot || 0)}</strong>
                    <span className="text-[10px] text-gray-400 block">Strike: {inspectedTrade.strike || 'N/A'}</span>
                  </div>
                </div>
              </div>

              {/* Grid 4: AI Confluence & Setup Signals */}
              <div className="mb-5">
                <span className="text-[11px] font-bold text-gray-400 uppercase tracking-wider block mb-2">
                  4. AI Confluence &amp; Fired Setup Triggers
                </span>
                <div className="p-3 bg-gray-950/80 rounded-lg border border-gray-800 space-y-2 text-xs">
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-800/80 pb-2">
                    <div className="flex items-center gap-2">
                      <span className="text-gray-400">AI Confidence:</span>
                      <span className="font-bold text-emerald-400 font-mono">{(Number(inspectedTrade.probability || 0.72) * 100).toFixed(0)}%</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-gray-400">Regime:</span>
                      <span className="font-bold text-blue-400 uppercase font-mono">{inspectedTrade.regime || 'TRENDING'}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-gray-400">TradingView:</span>
                      <span className="font-bold text-amber-400 uppercase font-mono">{inspectedTrade.tv_recommendation || 'BUY'}</span>
                    </div>
                  </div>

                  <div>
                    <span className="text-[10px] text-gray-400 uppercase block mb-1.5">Confluence Signals at Entry:</span>
                    <div className="flex flex-wrap gap-1.5">
                      {Array.isArray(inspectedTrade.setup_signals) && inspectedTrade.setup_signals.length > 0 ? (
                        inspectedTrade.setup_signals.map((sig: any, sIdx: number) => {
                          const sigName = String(sig?.name || '').replace(/_/g, ' ').toUpperCase();
                          const sigDirection = String(sig?.signal || 'NEUTRAL').toUpperCase();
                          const sigConfidence = Number.isFinite(Number(sig?.confidence)) ? (Number(sig.confidence) * 100).toFixed(0) : '0';
                          return (
                            <span
                              key={sIdx}
                              className={`px-2 py-0.5 rounded text-[10px] font-mono font-semibold ${
                                sigDirection === 'BULLISH'
                                  ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                                  : sigDirection === 'BEARISH'
                                    ? 'bg-red-950 text-red-400 border border-red-800'
                                    : 'bg-gray-800 text-gray-400 border border-gray-700'
                              }`}
                            >
                              {sigName}: {sigDirection} ({sigConfidence}%)
                            </span>
                          );
                        })
                      ) : (
                        <span className="text-gray-400 text-xs italic">Multi-indicator F&O momentum &amp; breakout confluence</span>
                      )}
                    </div>
                  </div>
                </div>
              </div>

              {/* Modal Actions */}
              <div className="flex items-center justify-between pt-3 border-t border-gray-800">
                {isTradeOpt ? (
                  <button
                    type="button"
                    onClick={() => {
                      setFocusedOption({
                        underlying: inspectedTrade.underlying_ticker || inspectedTrade.underlying || (inspectedTrade.ticker?.includes('BANK') ? 'BANKNIFTY' : inspectedTrade.ticker?.includes('FIN') ? 'FINNIFTY' : 'NIFTY'),
                        strike: Number(inspectedTrade.strike || 22800),
                        optionType: (inspectedTrade.option_type === 'PE' ? 'PE' : 'CE'),
                        action: isTradeSeller ? 'SELL' : 'BUY',
                        strategyType: inspectedTrade.strategy_type || (isTradeSpread ? 'CREDIT_SPREAD' : isTradeSeller ? 'WRITING' : 'DIRECTIONAL'),
                        hedgeStrike: inspectedTrade.hedge_strike_price,
                        hedgePrice: inspectedTrade.hedge_entry_price,
                        netCredit: inspectedTrade.net_credit,
                        entryPrice: Number(inspectedTrade.entry_price || 0),
                        targetPrice: Number(inspectedTrade.tp || 0),
                        stopLossPrice: Number(inspectedTrade.sl || 0),
                      });
                      setChartViewMode('option');
                      closeTradeDossier();
                    }}
                    className="px-4 py-2 bg-purple-600 hover:bg-purple-500 text-white font-bold text-xs rounded-lg flex items-center gap-1.5 transition"
                  >
                    <Zap className="w-3.5 h-3.5" />
                    View Option Candlestick Chart
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => {
                      setChartViewMode('spot');
                      closeTradeDossier();
                    }}
                    className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white font-bold text-xs rounded-lg flex items-center gap-1.5 transition"
                  >
                    <TrendingUp className="w-3.5 h-3.5" />
                    View Underlying Chart
                  </button>
                )}

                <button
                  type="button"
                  onClick={closeTradeDossier}
                  className="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 font-bold text-xs rounded-lg transition"
                >
                  Close Dossier
                </button>
              </div>
            </div>
          </div>
        );
      })()}
    </div>
  );
};

export default TrainingUI;
