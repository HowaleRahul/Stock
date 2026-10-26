import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import axios from 'axios';
import {
  Flame,
  CheckCircle2,
  XCircle,
  ExternalLink,
  RefreshCw,
  Plus,
  Trash2,
  Layers,
  ShieldCheck,
  Zap,
  Search,
  AlertTriangle,
  X,
} from 'lucide-react';
import ErrorBoundary from '../components/ErrorBoundary';
import { formatIndianCurrency } from '../utils/formatters';
import { getExchangeLotSize } from '../utils/foUtils';

interface ChecklistDetail {
  name: string;
  passed: boolean;
  score: number;
  max_score: number;
  details: string;
}

interface Candidate {
  ticker: string;
  sector: string;
  matched_scanners: string[];
  confluence_count: number;
  composite_score: number;
  qualifies_for_watchlist: boolean;
  summary: string;
  cur_close: number;
  change_pct: number;
  checklist: {
    checklist_items: Record<string, ChecklistDetail>;
    passed_count: number;
    total_checks: number;
  };
}

interface WatchlistItem {
  ticker: string;
  sector: string;
  source_scanners: string[];
  composite_score: number;
  vcp_detected: boolean;
  stage_2: boolean;
  added_at: string;
  notes?: string;
}

interface ORBPlan {
  ticker: string;
  is_triggered: boolean;
  volume_gate_confirmed: boolean;
  gate_5m_pct: number;
  gate_5m_passed: boolean;
  gate_15m_pct: number;
  gate_15m_passed: boolean;
  orb_high: number;
  orb_low: number;
  current_price: number;
  adv_20: number;
  entry_price?: number;
  stop_loss?: number;
  target_2r?: number;
  target_3r?: number;
  position_size: number;
  risk_amount: number;
  reasoning: string;
  error?: string;
}

const SwingToolkit: React.FC = () => {
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [selectedCandidate, setSelectedCandidate] = useState<Candidate | null>(null);
  const [orbPlan, setOrbPlan] = useState<ORBPlan | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);
  const [loadingWatchlist, setLoadingWatchlist] = useState(false);
  const [watchlistError, setWatchlistError] = useState<string | null>(null);
  const [evaluatingOrb, setEvaluatingOrb] = useState<string | null>(null);
  const [notification, setNotification] = useState<string>('');

  const [candidateFilterStatus, setCandidateFilterStatus] = useState<'ALL' | 'QUALIFIED' | 'FILTERED'>('ALL');
  const [candidateFilterScanner, setCandidateFilterScanner] = useState<string>('ALL');
  const [candidateSearch, setCandidateSearch] = useState<string>('');
  const scanAbortRef = useRef<AbortController | null>(null);
  const checklistModalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    return () => {
      if (scanAbortRef.current) {
        scanAbortRef.current.abort();
      }
    };
  }, []);

  const fetchWatchlist = useCallback(async (isManual = false) => {
    try {
      if (isManual) setLoadingWatchlist(true);
      const res = await axios.get('/api/v1/swing/watchlist');
      if (res.data?.watchlist) {
        setWatchlist(res.data.watchlist);
      }
      setWatchlistError(null);
    } catch {
      setWatchlistError('Unable to load the approved watchlist.');
    } finally {
      if (isManual) setLoadingWatchlist(false);
    }
  }, []);

  useEffect(() => {
    let ignore = false;
    axios.get('/api/v1/swing/watchlist')
      .then(res => {
        if (!ignore && res.data?.watchlist) {
          setWatchlist(res.data.watchlist);
        }
      })
      .catch(() => {
        if (!ignore) {
          setWatchlistError('Unable to load the approved watchlist.');
        }
      });
    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedCandidate) return;
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setSelectedCandidate(null);
        return;
      }
      if (e.key === 'Tab' && checklistModalRef.current) {
        const focusables = Array.from(
          checklistModalRef.current.querySelectorAll<HTMLElement>(
            'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
          )
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
      window.removeEventListener('keydown', handleKeyDown);
      previouslyFocused?.focus();
    };
  }, [selectedCandidate]);

  const cancelScan = () => {
    if (scanAbortRef.current) {
      scanAbortRef.current.abort();
    }
    setScanning(false);
    setNotification('Universe scan was cancelled.');
  };

  const runAllScanners = async () => {
    if (scanAbortRef.current) {
      scanAbortRef.current.abort();
    }
    const controller = new AbortController();
    scanAbortRef.current = controller;

    try {
      setScanning(true);
      setScanError(null);
      setNotification('Running Momentum, DWIB Inside Bar, and ATH Scanners across universe...');
      const res = await axios.get('/api/v1/swing/scanners/run', {
        params: { universe_size: 25 },
        signal: controller.signal,
        timeout: 45000,
      });
      if (res.data?.candidates) {
        setCandidates(res.data.candidates);
        setNotification(`Scanned universe complete: Found ${res.data.total_scanner_hits} hits (${res.data.qualified_for_watchlist} passed the 8-Factor filter).`);
      }
    } catch (err: any) {
      if (axios.isCancel(err)) {
        return;
      }
      const isTimeout = err.code === 'ECONNABORTED' || String(err.message).toLowerCase().includes('timeout');
      const msg = isTimeout
        ? 'Scanner request timed out after 45s. The market data feed may be slow or temporarily overloaded.'
        : `Scan failed: ${err?.response?.data?.detail || err.message}`;
      setScanError(msg);
      setNotification(msg);
    } finally {
      if (!controller.signal.aborted && scanAbortRef.current === controller) {
        setScanning(false);
      }
    }
  };

  const filteredCandidates = useMemo(() => {
    return candidates.filter(cand => {
      if (candidateFilterStatus === 'QUALIFIED' && !cand.qualifies_for_watchlist) return false;
      if (candidateFilterStatus === 'FILTERED' && cand.qualifies_for_watchlist) return false;
      if (candidateFilterScanner !== 'ALL' && !cand.matched_scanners.some(s => s.toLowerCase().includes(candidateFilterScanner.toLowerCase()))) return false;
      if (candidateSearch.trim()) {
        const q = candidateSearch.trim().toLowerCase();
        const matchTicker = (cand.ticker || '').toLowerCase().includes(q);
        const matchSector = (cand.sector || '').toLowerCase().includes(q);
        if (!matchTicker && !matchSector) return false;
      }
      return true;
    });
  }, [candidates, candidateFilterStatus, candidateFilterScanner, candidateSearch]);

  const addToWatchlist = async (cand: Candidate) => {
    try {
      const payload = {
        ticker: cand.ticker,
        sector: cand.sector,
        source_scanners: cand.matched_scanners,
        composite_score: cand.composite_score,
        vcp_detected: cand.checklist?.checklist_items?.contraction?.passed || false,
        stage_2: cand.checklist?.checklist_items?.stage_2?.passed || false,
        notes: `Score: ${cand.composite_score} | Scanners: ${cand.matched_scanners.join(', ')}`,
      };
      await axios.post('/api/v1/swing/watchlist', payload);
      setNotification(`✅ ${cand.ticker} added to winning watchlist!`);
      fetchWatchlist();
    } catch (err: any) {
      setNotification(`Error adding ${cand.ticker}: ${err.message}`);
    }
  };

  const removeFromWatchlist = async (ticker: string) => {
    try {
      await axios.delete(`/api/v1/swing/watchlist/${ticker}`);
      setNotification(`Removed ${ticker} from watchlist.`);
      fetchWatchlist();
    } catch (err: any) {
      setNotification(`Error removing: ${err.message}`);
    }
  };

  const checkORB = async (ticker: string) => {
    try {
      setEvaluatingOrb(ticker);
      setOrbPlan(null);
      const res = await axios.get(`/api/v1/swing/orb-check/${ticker}`);
      setOrbPlan(res.data);
    } catch (err: any) {
      setNotification(`ORB check failed for ${ticker}: ${err.message}`);
    } finally {
      setEvaluatingOrb(null);
    }
  };

  return (
    <div className="dashboard-page p-6 max-w-7xl mx-auto space-y-8">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-gray-800 pb-6">
        <div>
          <div className="flex items-center gap-2 text-blue-400 font-semibold text-xs tracking-wider uppercase mb-1">
            <Flame className="w-4 h-4 text-orange-400 animate-pulse" />
            Institutional Playbook
          </div>
          <h1 className="text-3xl font-extrabold text-white tracking-tight">
            MOMENTUM MASTERS · SWING TOOLKIT
          </h1>
          <p className="text-gray-400 text-sm mt-1 max-w-3xl">
            Half an hour a week. Three scanners. One clean watchlist. Run them once or twice a week, filter every hit through the 8-factor checklist, and execute with 15m ORB volume gating.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {scanning && (
            <button
              type="button"
              onClick={cancelScan}
              className="px-3.5 py-2.5 rounded-lg font-bold text-sm bg-gray-800 hover:bg-gray-700 text-gray-300 border border-gray-700 transition-all flex items-center gap-1.5"
            >
              <X className="w-4 h-4 text-gray-400" /> Cancel
            </button>
          )}
          <button
            type="button"
            onClick={runAllScanners}
            disabled={scanning}
            className={`px-5 py-2.5 rounded-lg font-bold text-sm flex items-center gap-2 transition-all ${
              scanning
                ? 'bg-blue-800 text-gray-300 cursor-not-allowed'
                : 'bg-blue-600 hover:bg-blue-500 text-white shadow-lg shadow-blue-600/30 active:scale-95'
            }`}
          >
            <RefreshCw className={`w-4 h-4 ${scanning ? 'animate-spin' : ''}`} />
            {scanning ? 'Scanning Market Universe...' : 'Run All 3 Scanners'}
          </button>
        </div>
      </div>

      {scanError && (
        <div className="bg-red-950/60 border border-red-800 text-red-200 px-4 py-3 rounded-lg text-sm flex flex-wrap items-center justify-between gap-3" role="alert">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-5 h-5 text-red-400 shrink-0" />
            <span>{scanError}</span>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button
              type="button"
              onClick={runAllScanners}
              className="px-3 py-1 bg-red-900/80 hover:bg-red-800 border border-red-700 text-xs font-semibold rounded text-white transition"
            >
              Retry Scanner
            </button>
            <button
              type="button"
              onClick={() => setScanError(null)}
              className="text-gray-400 hover:text-white text-xs underline"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      {notification && !scanError && (
        <div className="bg-blue-950/60 border border-blue-800 text-blue-200 px-4 py-2.5 rounded-lg text-sm flex items-center justify-between">
          <span>{notification}</span>
          <button onClick={() => setNotification('')} className="text-gray-400 hover:text-white text-xs">Dismiss</button>
        </div>
      )}

      {/* 3 Scanner Blueprint Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        {/* Scanner 1 */}
        <div className="bg-gray-900/80 border border-gray-800 rounded-xl p-5 flex flex-col justify-between hover:border-gray-700 transition-all">
          <div>
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-bold px-2 py-0.5 rounded bg-emerald-950 text-emerald-400 border border-emerald-800">
                Scanner 1
              </span>
              <a
                href="https://www.tradingview.com/screener/Hn9KTAyJ/"
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1"
              >
                TradingView Link <ExternalLink className="w-3 h-3" />
              </a>
            </div>
            <h3 className="text-lg font-bold text-white mb-1">Momentum Scanner</h3>
            <p className="text-gray-400 text-xs leading-relaxed mb-3">
              Finds stocks in strong momentum right now, backed by good volume, that have either just broken out or are coiling right at a breakout level.
            </p>
            <div className="bg-gray-950/70 p-2.5 rounded border border-gray-800 text-[11px] space-y-1 text-gray-300">
              <div className="font-semibold text-gray-200">What to keep:</div>
              <div>• Rising Relative Volume (RVol &gt; 1.2x)</div>
              <div>• Above 20 EMA &amp; 50 SMA</div>
              <div>• Breaking out or coiling within 2% of 20d pivot</div>
            </div>
          </div>
        </div>

        {/* Scanner 2 */}
        <div className="bg-gray-900/80 border border-gray-800 rounded-xl p-5 flex flex-col justify-between hover:border-gray-700 transition-all">
          <div>
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-bold px-2 py-0.5 rounded bg-purple-950 text-purple-400 border border-purple-800">
                Scanner 2
              </span>
              <a
                href="https://chartink.com/screener/copy-dwib-873"
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1"
              >
                Chartink DWIB <ExternalLink className="w-3 h-3" />
              </a>
            </div>
            <h3 className="text-lg font-bold text-white mb-1">Daily &amp; Weekly Inside Bar</h3>
            <p className="text-gray-400 text-xs leading-relaxed mb-3">
              Finds stocks forming an inside bar on the weekly chart while also showing contraction on the daily. The classic multi-timeframe pre-breakout squeeze.
            </p>
            <div className="bg-gray-950/70 p-2.5 rounded border border-gray-800 text-[11px] space-y-1 text-gray-300">
              <div className="font-semibold text-gray-200">What to keep:</div>
              <div>• Tight weekly inside bars (range within prior week)</div>
              <div>• Daily ATR / range contraction</div>
              <div>• Near prior highs or base (within 12%)</div>
            </div>
          </div>
        </div>

        {/* Scanner 3 */}
        <div className="bg-gray-900/80 border border-gray-800 rounded-xl p-5 flex flex-col justify-between hover:border-gray-700 transition-all">
          <div>
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-bold px-2 py-0.5 rounded bg-blue-950 text-blue-400 border border-blue-800">
                Scanner 3
              </span>
              <a
                href="https://chartink.com/screener/all-time-high-aman"
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1"
              >
                Chartink ATH <ExternalLink className="w-3 h-3" />
              </a>
            </div>
            <h3 className="text-lg font-bold text-white mb-1">All-Time-High (ATH)</h3>
            <p className="text-gray-400 text-xs leading-relaxed mb-3">
              Finds stocks at or near all-time highs — the strongest names with zero overhead supply. No trapped bagholders to sell into your rally.
            </p>
            <div className="bg-gray-950/70 p-2.5 rounded border border-gray-800 text-[11px] space-y-1 text-gray-300">
              <div className="font-semibold text-gray-200">What to keep:</div>
              <div>• Within 0% to 3.5% of ATH / 52W High</div>
              <div>• Contraction hugging 10 and 20 EMA band</div>
              <div>• Volume dry-up during base consolidation</div>
            </div>
          </div>
        </div>
      </div>

      {/* Active Winning Watchlist Section */}
      <ErrorBoundary compact title="Approved Watchlist Error">
        <div className="bg-gray-900/70 border border-gray-800 rounded-xl p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-xl font-bold text-white flex items-center gap-2">
                <ShieldCheck className="w-5 h-5 text-emerald-400" />
                The Winning Watchlist (Approved Swing Pool)
              </h2>
              <p className="text-xs text-gray-400">
                Filtered candidates cleared through the 8-Factor Checklist. These are monitored for 15m ORB volume gate execution on breakout day.
              </p>
            </div>
            <span className="px-3 py-1 bg-gray-800 text-gray-300 rounded-full text-xs font-bold font-mono">
              {watchlist.length} Active Candidates
            </span>
          </div>

          {loadingWatchlist ? (
            <div className="text-center py-8 text-gray-400" role="status">Loading approved watchlist...</div>
          ) : watchlistError ? (
            <div className="flex items-center justify-center gap-3 py-8 text-sm text-red-300" role="alert">
              <span>{watchlistError}</span>
              <button type="button" className="underline" onClick={() => void fetchWatchlist(true)}>Retry</button>
            </div>
          ) : watchlist.length === 0 ? (
            <div className="bg-gray-950/50 border border-dashed border-gray-800 rounded-xl p-8 text-center my-2">
              <div className="w-12 h-12 bg-gray-800/80 rounded-full flex items-center justify-center mx-auto mb-3 text-orange-400">
                <Flame className="w-6 h-6" />
              </div>
              <h3 className="text-base font-bold text-white mb-1">Approved Swing Watchlist is Empty</h3>
              <p className="text-gray-400 text-sm max-w-md mx-auto mb-4">
                Run the 3 swing scanners (Momentum, Inside Bar, and ATH) to scan liquid market stocks. Candidates scoring &ge; 70 on the 8-Factor filter can be approved into this watchlist with one click.
              </p>
              <button
                type="button"
                onClick={runAllScanners}
                disabled={scanning}
                className="px-4 py-2 bg-gradient-to-r from-orange-500 to-amber-500 hover:from-orange-600 hover:to-amber-600 disabled:opacity-50 text-white text-xs font-semibold rounded-lg transition inline-flex items-center gap-2"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${scanning ? 'animate-spin' : ''}`} />
                {scanning ? 'Scanning Market Universe...' : 'Run All 3 Scanners Now'}
              </button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-sm min-w-[760px]">
                <thead>
                  <tr className="border-b border-gray-800 text-gray-400 text-xs uppercase">
                    <th className="py-2.5 px-3">Ticker</th>
                    <th className="py-2.5 px-3">Sector</th>
                    <th className="py-2.5 px-3">Scanner Source</th>
                    <th className="py-2.5 px-3">Quality Score</th>
                    <th className="py-2.5 px-3">VCP &amp; Stage 2</th>
                    <th className="py-2.5 px-3 text-right">Intraday ORB Gate</th>
                    <th className="py-2.5 px-3 text-center">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800/60">
                  {watchlist.map((item) => (
                    <tr key={item.ticker} className="hover:bg-gray-800/40 transition-colors">
                      <td className="py-3 px-3 font-bold text-white flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full bg-emerald-400" />
                        {item.ticker}
                      </td>
                      <td className="py-3 px-3 text-gray-300 text-xs">{item.sector}</td>
                      <td className="py-3 px-3">
                        <div className="flex flex-wrap gap-1">
                          {item.source_scanners.map((sc, i) => (
                            <span key={i} className="text-[10px] px-2 py-0.5 rounded bg-blue-950 text-blue-300 border border-blue-800 font-semibold">
                              {sc}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="py-3 px-3">
                        <span className="px-2.5 py-1 rounded text-xs font-bold bg-emerald-950 text-emerald-300 border border-emerald-800">
                          {item.composite_score.toFixed(1)} / 100
                        </span>
                      </td>
                      <td className="py-3 px-3 text-xs">
                        <div className="flex gap-2">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${item.stage_2 ? 'bg-emerald-900/50 text-emerald-300' : 'bg-gray-800 text-gray-400'}`}>
                            STAGE 2
                          </span>
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${item.vcp_detected ? 'bg-purple-900/50 text-purple-300' : 'bg-gray-800 text-gray-400'}`}>
                            VCP BASE
                          </span>
                        </div>
                      </td>
                      <td className="py-3 px-3 text-right">
                        <button
                          onClick={() => checkORB(item.ticker)}
                          disabled={evaluatingOrb === item.ticker}
                          className="px-3 py-1 bg-amber-950/70 hover:bg-amber-900 text-amber-300 border border-amber-800 rounded text-xs font-semibold flex items-center gap-1.5 ml-auto transition-all"
                        >
                          <Zap className={`w-3.5 h-3.5 ${evaluatingOrb === item.ticker ? 'animate-bounce' : ''}`} />
                          {evaluatingOrb === item.ticker ? 'Evaluating...' : 'Check 15m ORB'}
                        </button>
                      </td>
                      <td className="py-3 px-3 text-center">
                        <button
                          onClick={() => removeFromWatchlist(item.ticker)}
                          className="text-gray-500 hover:text-red-400 transition-colors p-1"
                          title="Remove candidate"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </ErrorBoundary>

      {/* ORB Execution Plan Modal / Panel */}
      {orbPlan && (
        <ErrorBoundary compact title="ORB Plan Error">
          <div className="bg-gray-900 border border-amber-600/40 rounded-xl p-6 shadow-2xl space-y-4 animate-in fade-in">
            <div className="flex items-center justify-between border-b border-gray-800 pb-3">
              <div className="flex items-center gap-3">
                <Zap className="w-6 h-6 text-amber-400" />
                <div>
                  <h3 className="text-lg font-bold text-white">
                    Intraday ORB &amp; Volume Gate Execution Plan: {orbPlan.ticker}
                  </h3>
                  <p className="text-xs text-gray-400">
                    Evaluated against 20-Day ADV: {orbPlan.adv_20?.toLocaleString('en-IN')} shares
                  </p>
                </div>
              </div>
              <button onClick={() => setOrbPlan(null)} className="text-gray-400 hover:text-white text-sm">Close</button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              {/* 5m Volume Gate */}
              <div className="bg-gray-950 p-4 rounded-lg border border-gray-800">
                <span className="text-xs text-gray-400 block mb-1">Gate 1: First 5-Min Volume</span>
                <div className="flex items-baseline gap-2">
                  <span className="text-2xl font-bold font-mono text-white">{orbPlan.gate_5m_pct}%</span>
                  <span className="text-xs text-gray-400">of 20d ADV</span>
                </div>
                <div className="mt-2 text-xs font-semibold flex items-center gap-1.5">
                  {orbPlan.gate_5m_passed ? (
                    <span className="text-emerald-400 flex items-center gap-1"><CheckCircle2 className="w-3.5 h-3.5" /> PASSED (&ge; 7%)</span>
                  ) : (
                    <span className="text-gray-500 flex items-center gap-1"><XCircle className="w-3.5 h-3.5" /> Below 7%</span>
                  )}
                </div>
              </div>

              {/* 15m Volume Gate */}
              <div className="bg-gray-950 p-4 rounded-lg border border-gray-800">
                <span className="text-xs text-gray-400 block mb-1">Gate 2: First 15-Min Volume</span>
                <div className="flex items-baseline gap-2">
                  <span className="text-2xl font-bold font-mono text-white">{orbPlan.gate_15m_pct}%</span>
                  <span className="text-xs text-gray-400">of 20d ADV</span>
                </div>
                <div className="mt-2 text-xs font-semibold flex items-center gap-1.5">
                  {orbPlan.gate_15m_passed ? (
                    <span className="text-emerald-400 flex items-center gap-1"><CheckCircle2 className="w-3.5 h-3.5" /> PASSED (&ge; 17%)</span>
                  ) : (
                    <span className="text-gray-500 flex items-center gap-1"><XCircle className="w-3.5 h-3.5" /> Below 17%</span>
                  )}
                </div>
              </div>

              {/* 15m Opening Range */}
              <div className="bg-gray-950 p-4 rounded-lg border border-gray-800">
                <span className="text-xs text-gray-400 block mb-1">15m Opening Range</span>
                <div className="text-xs font-mono space-y-1 text-gray-200">
                  <div>High (Trigger): <span className="font-bold text-white">{formatIndianCurrency(orbPlan.orb_high)}</span></div>
                  <div>Low (Stop): <span className="font-bold text-gray-400">{formatIndianCurrency(orbPlan.orb_low)}</span></div>
                  <div>LTP: <span className="font-bold text-blue-400">{formatIndianCurrency(orbPlan.current_price)}</span></div>
                </div>
              </div>

              {/* Trigger State */}
              <div className="bg-gray-950 p-4 rounded-lg border border-gray-800 flex flex-col justify-center">
                <span className="text-xs text-gray-400 block mb-1">Execution Status</span>
                {orbPlan.is_triggered ? (
                  <div className="text-sm font-bold px-3 py-1 rounded bg-emerald-950 text-emerald-300 border border-emerald-800 text-center animate-pulse">
                    🔥 BUY TRIGGERED
                  </div>
                ) : (
                  <div className="text-xs font-semibold px-2.5 py-1 rounded bg-gray-800 text-gray-400 text-center">
                    AWAITING BREAKOUT
                  </div>
                )}
              </div>
            </div>

            <div className="bg-gray-950 p-4 rounded-lg border border-gray-800 text-xs text-gray-300 leading-relaxed">
              <strong>System Readout:</strong> {orbPlan.reasoning}
            </div>

            {orbPlan.is_triggered && orbPlan.entry_price && (
              <div className="bg-emerald-950/40 border border-emerald-800/80 p-4 rounded-lg grid grid-cols-2 md:grid-cols-6 gap-3 text-xs">
                <div><span className="text-gray-400 block">Entry Price:</span><span className="font-bold text-white text-sm">{formatIndianCurrency(orbPlan.entry_price)}</span></div>
                <div><span className="text-gray-400 block">Stop Loss:</span><span className="font-bold text-red-400 text-sm">{formatIndianCurrency(orbPlan.stop_loss)}</span></div>
                <div><span className="text-gray-400 block">Target 2R:</span><span className="font-bold text-emerald-400 text-sm">{formatIndianCurrency(orbPlan.target_2r)}</span></div>
                <div><span className="text-gray-400 block">Target 3R:</span><span className="font-bold text-emerald-300 text-sm">{formatIndianCurrency(orbPlan.target_3r)}</span></div>
                <div><span className="text-gray-400 block">Position Size (1.5% Risk):</span><span className="font-bold text-amber-300 text-sm">{orbPlan.position_size} shares</span></div>
                <div><span className="text-gray-400 block">Exchange Lot:</span><span className="font-bold text-cyan-300 text-sm">{getExchangeLotSize(orbPlan.ticker)} qty/lot</span></div>
              </div>
            )}
          </div>
        </ErrorBoundary>
      )}

      {/* Scanner Hits & 8-Factor Filter Checklist Matrix */}
      <ErrorBoundary compact title="Candidate Scanner Universe Error">
        <div className="bg-gray-900/70 border border-gray-800 rounded-xl p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-xl font-bold text-white flex items-center gap-2">
                <Layers className="w-5 h-5 text-blue-400" />
                Scanner Hits &amp; 8-Factor Filter Matrix
              </h2>
              <p className="text-xs text-gray-400">
                Every scanner hit must clear the checklist cutoff (Score &ge; 70.0) before earning a place on your watchlist.
              </p>
            </div>
            <span className="text-xs text-gray-400 font-mono">
              {filteredCandidates.length} of {candidates.length} Hits Displayed
            </span>
          </div>

          {/* Candidate Filter Toolbar */}
          {candidates.length > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-3 mb-4 p-3 bg-gray-950/60 border border-gray-800 rounded-lg text-xs">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-gray-400 font-semibold mr-1">Status:</span>
                {[
                  { label: 'All Hits', val: 'ALL', count: candidates.length },
                  { label: 'Approved (Score ≥ 70)', val: 'QUALIFIED', count: candidates.filter(c => c.qualifies_for_watchlist).length },
                  { label: 'Filtered Out (< 70)', val: 'FILTERED', count: candidates.filter(c => !c.qualifies_for_watchlist).length },
                ].map(tab => (
                  <button
                    key={tab.val}
                    type="button"
                    onClick={() => setCandidateFilterStatus(tab.val as any)}
                    className={`px-2.5 py-1 rounded text-xs font-semibold border transition ${
                      candidateFilterStatus === tab.val
                        ? 'bg-blue-600 border-blue-500 text-white'
                        : 'bg-gray-800 border-gray-700 text-gray-400 hover:text-white'
                    }`}
                  >
                    {tab.label} <span className="opacity-70 font-mono">({tab.count})</span>
                  </button>
                ))}
              </div>

              <div className="flex items-center gap-2">
                <select
                  aria-label="Filter by matched scanner"
                  value={candidateFilterScanner}
                  onChange={e => setCandidateFilterScanner(e.target.value)}
                  className="bg-gray-800 border border-gray-700 text-gray-200 text-xs rounded px-2.5 py-1 focus:outline-none focus:border-blue-500"
                >
                  <option value="ALL">All Scanners</option>
                  <option value="Momentum">Momentum 52W</option>
                  <option value="DWIB">DWIB Inside Bar</option>
                  <option value="ATH">ATH Breakout</option>
                </select>

                <div className="flex items-center gap-1 bg-gray-800 border border-gray-700 px-2.5 py-1 rounded">
                  <Search className="w-3.5 h-3.5 text-gray-500" />
                  <input
                    type="text"
                    placeholder="Search ticker/sector..."
                    value={candidateSearch}
                    onChange={e => setCandidateSearch(e.target.value)}
                    aria-label="Search candidates by ticker or sector"
                    className="bg-transparent border-none text-gray-200 placeholder-gray-500 text-xs focus:outline-none w-32"
                  />
                  {candidateSearch && (
                    <button
                      type="button"
                      onClick={() => setCandidateSearch('')}
                      aria-label="Clear search"
                      className="text-gray-400 hover:text-white text-xs"
                    >
                      ✕
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}

          {candidates.length === 0 ? (
            <div className="text-center py-12 text-gray-500 text-sm">
              Click <strong>"Run All 3 Scanners"</strong> above to scan the liquid momentum universe.
            </div>
          ) : filteredCandidates.length === 0 ? (
            <div className="text-center py-8 text-gray-500 text-sm">
              No scanner hits match the current filter criteria.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-sm min-w-[760px]">
                <thead>
                  <tr className="border-b border-gray-800 text-gray-400 text-xs uppercase">
                    <th className="py-2.5 px-3">Ticker</th>
                    <th className="py-2.5 px-3">Sector</th>
                    <th className="py-2.5 px-3">LTP / Change</th>
                    <th className="py-2.5 px-3">Scanners Matched</th>
                    <th className="py-2.5 px-3">Filter Score</th>
                    <th className="py-2.5 px-3">Checklist Gate</th>
                    <th className="py-2.5 px-3 text-center">Inspect</th>
                    <th className="py-2.5 px-3 text-right">Add to Watchlist</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800/60">
                  {filteredCandidates.map((cand) => {
                    const qualifies = cand.qualifies_for_watchlist;
                    const inWatchlist = watchlist.some((w) => w.ticker === cand.ticker);
                    return (
                      <tr key={cand.ticker} className="hover:bg-gray-800/40 transition-colors">
                        <td className="py-3 px-3 font-bold text-white">{cand.ticker}</td>
                        <td className="py-3 px-3 text-gray-300 text-xs">{cand.sector}</td>
                        <td className="py-3 px-3 text-xs">
                          <div className="font-mono text-white">{formatIndianCurrency(cand.cur_close)}</div>
                          <div className={`text-[11px] ${cand.change_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            {cand.change_pct >= 0 ? '+' : ''}{cand.change_pct}%
                          </div>
                        </td>
                        <td className="py-3 px-3">
                          <div className="flex flex-wrap gap-1">
                            {cand.matched_scanners.map((sc, i) => (
                              <span key={i} className="text-[10px] px-2 py-0.5 rounded bg-gray-800 text-gray-300 font-semibold border border-gray-700">
                                {sc}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="py-3 px-3">
                          <span className={`px-2.5 py-1 rounded text-xs font-bold ${
                            qualifies ? 'bg-emerald-950 text-emerald-300 border border-emerald-800' : 'bg-red-950 text-red-300 border border-red-800'
                          }`}>
                            {Number(cand.composite_score || 0).toFixed(1)} / 100
                          </span>
                        </td>
                        <td className="py-3 px-3 text-xs">
                          {qualifies ? (
                            <span className="text-emerald-400 font-semibold flex items-center gap-1">
                              <CheckCircle2 className="w-3.5 h-3.5" /> Approved
                            </span>
                          ) : (
                            <span className="text-red-400 font-semibold flex items-center gap-1">
                              <XCircle className="w-3.5 h-3.5" /> Filtered Out
                            </span>
                          )}
                        </td>
                        <td className="py-3 px-3 text-center">
                          <button
                            onClick={() => setSelectedCandidate(cand)}
                            className="px-2.5 py-1 rounded bg-gray-800 hover:bg-gray-700 text-gray-300 text-xs font-semibold"
                          >
                            Details
                          </button>
                        </td>
                        <td className="py-3 px-3 text-right">
                          {inWatchlist ? (
                            <span className="text-xs text-gray-500 font-semibold">On Watchlist</span>
                          ) : (
                            <button
                              onClick={() => addToWatchlist(cand)}
                              className="px-3 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded text-xs font-semibold flex items-center gap-1 ml-auto"
                            >
                              <Plus className="w-3.5 h-3.5" /> Add
                            </button>
                          )}
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

      {/* Candidate Checklist Detail Modal */}
      {selectedCandidate && (
        <div
          className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4 animate-fadeIn"
          role="dialog"
          aria-modal="true"
          aria-labelledby="checklist-modal-title"
        >
          <div
            ref={checklistModalRef}
            className="bg-gray-900 border border-gray-800 rounded-xl max-w-2xl w-full p-6 space-y-4 max-h-[90vh] overflow-y-auto shadow-2xl"
          >
            <div className="flex items-center justify-between border-b border-gray-800 pb-3">
              <div>
                <h3 id="checklist-modal-title" className="text-xl font-bold text-white flex items-center gap-2">
                  {selectedCandidate.ticker} — 8-Factor Quality Checklist Breakdown
                </h3>
                <p className="text-xs text-gray-400">Sector: {selectedCandidate.sector} | Score: {selectedCandidate.composite_score}/100</p>
              </div>
              <button
                type="button"
                onClick={() => setSelectedCandidate(null)}
                aria-label="Close Checklist Modal"
                className="text-gray-400 hover:text-white p-1 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                ✕
              </button>
            </div>

            <div className="space-y-3">
              {Object.entries(selectedCandidate.checklist?.checklist_items || {}).map(([key, item]) => (
                <div key={key} className="bg-gray-950 p-3 rounded-lg border border-gray-800 flex items-start justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      {item.passed ? (
                        <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                      ) : (
                        <XCircle className="w-4 h-4 text-red-400 shrink-0" />
                      )}
                      <span className="font-bold text-sm text-white">{item.name}</span>
                    </div>
                    <p className="text-xs text-gray-400">{item.details}</p>
                  </div>
                  <span className="text-xs font-mono font-bold text-gray-300 shrink-0">
                    {item.score} / {item.max_score} pts
                  </span>
                </div>
              ))}
            </div>

            <div className="flex justify-end gap-3 pt-3 border-t border-gray-800">
              <button
                onClick={() => setSelectedCandidate(null)}
                className="px-4 py-2 bg-gray-800 text-gray-300 rounded text-xs font-semibold"
              >
                Close
              </button>
              <button
                onClick={() => {
                  addToWatchlist(selectedCandidate);
                  setSelectedCandidate(null);
                }}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded text-xs font-semibold flex items-center gap-1.5"
              >
                <Plus className="w-3.5 h-3.5" /> Add to Winning Watchlist
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default SwingToolkit;
