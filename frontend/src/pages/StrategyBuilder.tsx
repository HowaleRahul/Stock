import { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';
import { Plus, Trash2, Save, SlidersHorizontal, CheckCircle2, Sparkles, Layers } from 'lucide-react';
import ErrorBoundary from '../components/ErrorBoundary';
import { formatIndianCurrency } from '../utils/formatters';

interface Condition {
  id: string;
  indicator: string;
  operator: string;
  value: string;
}

const indicatorOptions = ['RSI', 'MACD', 'EMA 20', 'EMA 50', 'Price', 'Volume'];
const operatorOptions = ['>', '<', '>=', '<=', 'crosses above', 'crosses below'];

const createCondition = (): Condition => ({
  id: Math.random().toString(36).substring(2, 11),
  indicator: 'RSI',
  operator: '>',
  value: '',
});

const UNDERLYING_SPECS = [
  { id: 'NIFTY' as const, label: 'NIFTY 50', lotSize: 50, strikeStep: 50, typicalSpot: 24500, spreadMargin: 32500, debitOutlay: 6000, netCredit: 2250, thetaGain: 450 },
  { id: 'BANKNIFTY' as const, label: 'BANKNIFTY 15', lotSize: 15, strikeStep: 100, typicalSpot: 52000, spreadMargin: 36000, debitOutlay: 3750, netCredit: 1800, thetaGain: 520 },
  { id: 'SENSEX' as const, label: 'SENSEX 10', lotSize: 10, strikeStep: 100, typicalSpot: 80000, spreadMargin: 38000, debitOutlay: 3500, netCredit: 1600, thetaGain: 480 },
  { id: 'FINNIFTY' as const, label: 'FINNIFTY 25', lotSize: 25, strikeStep: 50, typicalSpot: 23500, spreadMargin: 28000, debitOutlay: 2500, netCredit: 1250, thetaGain: 380 },
  { id: 'MIDCPNIFTY' as const, label: 'MIDCPNIFTY 50', lotSize: 50, strikeStep: 25, typicalSpot: 12500, spreadMargin: 25000, debitOutlay: 3500, netCredit: 1400, thetaGain: 400 },
];

const F_AND_O_TEMPLATES = [
  {
    name: 'Bull Put Credit Spread (Sell OTM Put, Buy lower Put)',
    category: 'CREDIT_SPREAD' as const,
    underlying: 'NIFTY' as const,
    description: 'High-probability OTM put credit spread harvesting positive daily theta decay. Sells 0.25 Delta Put with lower protective wing hedge for defined risk and margin relief.',
    bullish: [
      { indicator: 'RSI', operator: '>', value: '50' },
      { indicator: 'EMA 20', operator: '>', value: '45' },
      { indicator: 'Price', operator: '>', value: '80' },
    ],
    bearish: [
      { indicator: 'RSI', operator: '<', value: '40' },
      { indicator: 'Price', operator: '<', value: '25' },
    ],
  },
  {
    name: 'Bear Call Credit Spread (Sell OTM Call, Buy higher Call)',
    category: 'CREDIT_SPREAD' as const,
    underlying: 'BANKNIFTY' as const,
    description: 'Resistance writing credit spread. Sells OTM Call at key resistance ceiling and buys higher protective call to harvest time decay with strictly defined risk.',
    bullish: [
      { indicator: 'RSI', operator: '<', value: '45' },
      { indicator: 'EMA 20', operator: '<', value: '55' },
      { indicator: 'Price', operator: '>', value: '120' },
    ],
    bearish: [
      { indicator: 'RSI', operator: '>', value: '65' },
      { indicator: 'Price', operator: '<', value: '30' },
    ],
  },
  {
    name: 'Iron Condor (Sell OTM Put + Buy further OTM Put, Sell OTM Call + Buy further OTM Call)',
    category: 'HEDGED_WRITING' as const,
    underlying: 'NIFTY' as const,
    description: 'Double-wing delta-neutral theta harvesting during low-volatility consolidation regimes. Sells OTM Put & Call with further OTM protective wings for defined risk.',
    bullish: [
      { indicator: 'RSI', operator: '>', value: '45' },
      { indicator: 'EMA 20', operator: '>', value: '48' },
      { indicator: 'Price', operator: '>', value: '50' },
    ],
    bearish: [
      { indicator: 'RSI', operator: '<', value: '55' },
      { indicator: 'EMA 20', operator: '<', value: '52' },
      { indicator: 'Price', operator: '<', value: '15' },
    ],
  },
  {
    name: 'Momentum Scalp Call (Fast CE Momentum)',
    category: 'DIRECTIONAL' as const,
    underlying: 'NIFTY' as const,
    description: 'High-speed bullish intraday momentum scalp riding above 20 EMA with RSI expansion on index Call options.',
    bullish: [
      { indicator: 'RSI', operator: '>', value: '60' },
      { indicator: 'EMA 20', operator: '>', value: '50' },
      { indicator: 'Price', operator: '>', value: '120' },
    ],
    bearish: [
      { indicator: 'RSI', operator: '<', value: '45' },
      { indicator: 'Price', operator: '<', value: '90' },
    ],
  },
  {
    name: 'Momentum Scalp Put (Fast PE Momentum)',
    category: 'DIRECTIONAL' as const,
    underlying: 'BANKNIFTY' as const,
    description: 'Mean-reversion and breakdown put momentum scalp when contracts show extreme overbought exhaustion or breakdown below 20 EMA.',
    bullish: [
      { indicator: 'RSI', operator: '<', value: '35' },
      { indicator: 'Price', operator: '>', value: '250' },
    ],
    bearish: [
      { indicator: 'RSI', operator: '>', value: '70' },
      { indicator: 'EMA 20', operator: '<', value: '40' },
    ],
  },
];

const StrategyBuilder = () => {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [strategyStyle, setStrategyStyle] = useState<'DIRECTIONAL' | 'CREDIT_SPREAD' | 'HEDGED_WRITING'>('DIRECTIONAL');
  const [selectedUnderlying, setSelectedUnderlying] = useState<'NIFTY' | 'BANKNIFTY' | 'SENSEX' | 'FINNIFTY' | 'MIDCPNIFTY'>('NIFTY');
  const [strategies, setStrategies] = useState<any[]>([]);
  const [bullishConditions, setBullishConditions] = useState<Condition[]>([createCondition()]);
  const [bearishConditions, setBearishConditions] = useState<Condition[]>([createCondition()]);
  const [error, setError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [saving, setSaving] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      if (abortRef.current) abortRef.current.abort();
    };
  }, []);

  const applyTemplate = (tpl: typeof F_AND_O_TEMPLATES[number]) => {
    setName(tpl.name);
    setDescription(tpl.description);
    setStrategyStyle(tpl.category || 'DIRECTIONAL');
    if (tpl.underlying) {
      setSelectedUnderlying(tpl.underlying);
    }
    setBullishConditions(tpl.bullish.map(c => ({ id: Math.random().toString(36).substring(2, 11), ...c })));
    setBearishConditions(tpl.bearish.map(c => ({ id: Math.random().toString(36).substring(2, 11), ...c })));
    setError('');
  };

  const loadStrategies = useCallback(async () => {
    if (abortRef.current) {
      abortRef.current.abort();
    }
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await axios.get('/api/v1/strategy/list', {
        signal: controller.signal,
      });
      setStrategies(Array.isArray(res.data.strategies) ? res.data.strategies : []);
      setError('');
    } catch (err: any) {
      if (axios.isCancel(err)) return;
      setError(err?.response?.status ? `Strategy service unavailable (HTTP ${err.response.status}).` : 'Backend is offline. Start the API server and retry.');
    }
  }, []);

  useEffect(() => {
    let ignore = false;
    const controller = new AbortController();
    abortRef.current = controller;

    axios.get('/api/v1/strategy/list', { signal: controller.signal })
      .then(res => {
        if (!ignore) {
          setStrategies(Array.isArray(res.data.strategies) ? res.data.strategies : []);
        }
      })
      .catch((err: any) => {
        if (!ignore && !axios.isCancel(err)) {
          setError(err?.response?.status ? `Strategy service unavailable (HTTP ${err.response.status}).` : 'Backend is offline. Start the API server and retry.');
        }
      });

    return () => {
      ignore = true;
      controller.abort();
    };
  }, []);

  const handleCreate = async () => {
    const trimmedName = name.trim();
    if (!trimmedName) {
      setError('Give this strategy a name before saving.');
      return;
    }
    const allConditions = [...bullishConditions, ...bearishConditions];
    if (allConditions.length === 0) {
      setError('A strategy must have at least one rule (entry or exit bias) before saving.');
      return;
    }
    if (allConditions.some(c => !c.value.trim())) {
      setError('Complete every condition value or remove unused rule rows before saving.');
      return;
    }

    const validateConditionValue = (indicator: string, valStr: string): string | null => {
      const val = Number(valStr);
      if (!Number.isFinite(val)) return 'Condition value must be a valid number.';
      if (indicator === 'RSI' && (val < 0 || val > 100)) {
        return 'RSI value must be between 0 and 100.';
      }
      if ((indicator === 'Price' || indicator === 'Volume') && val <= 0) {
        return `${indicator} must be greater than zero.`;
      }
      return null;
    };

    for (const c of allConditions) {
      const err = validateConditionValue(c.indicator, c.value.trim());
      if (err) {
        setError(`Invalid rule "${c.indicator} ${c.operator} ${c.value}": ${err}`);
        return;
      }
    }

    try {
      setError('');
      setSaving(true);
      await axios.post('/api/v1/strategy/create', {
        name: trimmedName,
        description: description.trim(),
        strategy_style: strategyStyle,
        underlying: selectedUnderlying,
        bullish_conditions: bullishConditions.map(({ indicator, operator, value }) => ({
          indicator,
          operator,
          value: value.trim(),
        })),
        bearish_conditions: bearishConditions.map(({ indicator, operator, value }) => ({
          indicator,
          operator,
          value: value.trim(),
        })),
      });

      setSuccessMessage(`Strategy "${trimmedName}" was saved successfully.`);
      setName('');
      setDescription('');
      setBullishConditions([createCondition()]);
      setBearishConditions([createCondition()]);
      await loadStrategies();

      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setSuccessMessage(''), 5000);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Strategy could not be created.');
    } finally {
      setSaving(false);
    }
  };

  const updateCondition = (side: 'bullish' | 'bearish', id: string, key: keyof Omit<Condition, 'id'>, value: string) => {
    const setter = side === 'bullish' ? setBullishConditions : setBearishConditions;
    setter(current => current.map(c => c.id === id ? { ...c, [key]: value } : c));
  };

  const removeCondition = (side: 'bullish' | 'bearish', id: string) => {
    const setter = side === 'bullish' ? setBullishConditions : setBearishConditions;
    setter(current => current.filter(c => c.id !== id));
  };

  const renderConditionGroup = (side: 'bullish' | 'bearish', conditions: Condition[]) => (
    <section className={`condition-group ${side}`} aria-labelledby={`${side}-conditions-heading`}>
      <div className="condition-group-heading">
        <div>
          <span className="condition-dot" />
          <h3 id={`${side}-conditions-heading`}>{side === 'bullish' ? 'Entry bias' : 'Exit bias'}</h3>
        </div>
        <span>{conditions.length} rule{conditions.length === 1 ? '' : 's'}</span>
      </div>
      <p className="condition-helper">All rules must be true</p>
      <div className="condition-list">
        {conditions.length === 0 ? (
          <div className="p-4 text-center text-xs text-gray-500 border border-dashed border-gray-800 rounded-lg mb-2">
            No {side === 'bullish' ? 'entry' : 'exit'} rules added yet. Click &quot;Add rule&quot; to configure.
          </div>
        ) : (
          conditions.map((condition, index) => (
            <div className="condition-row" key={condition.id}>
              <span className="condition-number">{String(index + 1).padStart(2, '0')}</span>
              <label className="sr-only" htmlFor={`${side}-indicator-${condition.id}`}>Indicator</label>
              <select
                id={`${side}-indicator-${condition.id}`}
                value={condition.indicator}
                onChange={event => updateCondition(side, condition.id, 'indicator', event.target.value)}
                aria-label={`${side} rule ${index + 1} indicator`}
              >
                {indicatorOptions.map(option => <option key={option} value={option}>{option}</option>)}
              </select>
              <label className="sr-only" htmlFor={`${side}-operator-${condition.id}`}>Operator</label>
              <select
                id={`${side}-operator-${condition.id}`}
                value={condition.operator}
                onChange={event => updateCondition(side, condition.id, 'operator', event.target.value)}
                aria-label={`${side} rule ${index + 1} operator`}
              >
                {operatorOptions.map(option => <option key={option} value={option}>{option}</option>)}
              </select>
              <label className="sr-only" htmlFor={`${side}-value-${condition.id}`}>Value</label>
              <input
                id={`${side}-value-${condition.id}`}
                value={condition.value}
                onChange={event => updateCondition(side, condition.id, 'value', event.target.value)}
                placeholder="Value"
                maxLength={64}
                aria-label={`${side} rule ${index + 1} value`}
              />
              <button
                type="button"
                className="condition-remove"
                onClick={() => removeCondition(side, condition.id)}
                aria-label={`Remove ${side} rule ${index + 1}`}
                title="Remove rule"
              >
                <Trash2 />
              </button>
            </div>
          ))
        )}
      </div>
      <button
        type="button"
        className="add-condition"
        onClick={() => (side === 'bullish' ? setBullishConditions : setBearishConditions)(current => [...current, createCondition()])}
      >
        <Plus /> Add rule
      </button>
    </section>
  );

  return (
    <div className="strategy-page">
      {error && (
        <div className="state-panel compact mb-4" role="alert">
          <strong>{error}</strong>
          <button className="retry-button" onClick={loadStrategies}>Retry connection</button>
        </div>
      )}

      {successMessage && (
        <div className="p-4 mb-4 rounded-lg bg-emerald-900/30 border border-emerald-500/50 text-emerald-300 flex items-center gap-3 text-sm">
          <CheckCircle2 className="w-5 h-5 flex-shrink-0 text-emerald-400" />
          <span>{successMessage}</span>
        </div>
      )}

      <div className="page-heading strategy-heading">
        <div>
          <span className="eyebrow">Rule composer / 07</span>
          <h1>Build a strategy</h1>
          <p>Translate your market read into rules the engine can evaluate.</p>
        </div>
        <div className="strategy-badge"><SlidersHorizontal /> NO-CODE MODE</div>
      </div>

      <div className="strategy-layout">
        <ErrorBoundary compact title="Strategy Builder Form Error">
          <section className="builder-panel">
            <div className="builder-panel-heading">
              <div>
                <span className="eyebrow">Strategy details</span>
                <h2>New rule set</h2>
              </div>
              <span className="draft-status">DRAFT</span>
            </div>

            <div className="mb-4 p-3 bg-gray-900/60 rounded-lg border border-gray-800">
              <div className="flex items-center gap-1.5 text-xs text-blue-400 font-semibold mb-2">
                <Sparkles className="w-3.5 h-3.5 text-amber-400" />
                <span>Indian F&amp;O Presets</span>
              </div>
              <div className="flex flex-wrap gap-2">
                {F_AND_O_TEMPLATES.map((tpl) => (
                  <button
                    key={tpl.name}
                    type="button"
                    onClick={() => applyTemplate(tpl)}
                    className="px-2.5 py-1 text-xs rounded-md bg-gray-800 hover:bg-blue-600/20 border border-gray-700 hover:border-blue-500/50 text-gray-300 hover:text-blue-300 transition-colors"
                  >
                    {tpl.name}
                  </button>
                ))}
              </div>
            </div>

            {/* Indian F&O Underlying Asset & Margin Estimator */}
            <div className="mb-4 p-3 bg-gray-900/60 rounded-lg border border-gray-800">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-semibold text-gray-200 flex items-center gap-1.5">
                  <Layers className="w-3.5 h-3.5 text-blue-400" />
                  Select F&amp;O Underlying Asset
                </span>
                <span className="text-[10px] text-gray-400 font-mono">SEBI / NSE Lot &amp; SPAN Margins</span>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-1.5" role="group" aria-label="Underlying Selection">
                {UNDERLYING_SPECS.map(u => (
                  <button
                    key={u.id}
                    type="button"
                    onClick={() => setSelectedUnderlying(u.id)}
                    className={`p-2 rounded-lg border text-left transition-all ${
                      selectedUnderlying === u.id
                        ? 'bg-blue-600/20 border-blue-500 text-white shadow-sm ring-1 ring-blue-500/40'
                        : 'bg-gray-800/60 border-gray-700/60 text-gray-300 hover:text-white hover:border-gray-600'
                    }`}
                  >
                    <div className="font-bold text-xs font-mono">{u.label}</div>
                    <div className="text-[10px] text-gray-400 mt-0.5">Lot: {u.lotSize} Qty</div>
                    <div className="text-[9px] text-gray-500 font-mono">Step: {u.strikeStep} pts</div>
                  </button>
                ))}
              </div>

              {/* Dynamic Margin Feedback Banner */}
              {(() => {
                const spec = UNDERLYING_SPECS.find(s => s.id === selectedUnderlying) || UNDERLYING_SPECS[0];
                const isCredit = strategyStyle === 'CREDIT_SPREAD';
                const isCondor = strategyStyle === 'HEDGED_WRITING';
                const estMargin = isCredit ? spec.spreadMargin : isCondor ? spec.spreadMargin * 1.4 : spec.debitOutlay;
                const netCash = isCredit ? spec.netCredit : isCondor ? spec.netCredit * 1.8 : 0;
                const thetaEst = isCredit ? spec.thetaGain : isCondor ? spec.thetaGain * 1.7 : -spec.thetaGain * 0.7;

                return (
                  <div className="mt-2.5 p-2.5 bg-gray-950/80 rounded-lg border border-gray-800 grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs font-mono">
                    <div>
                      <span className="text-[10px] text-gray-400 block">Exchange Lot:</span>
                      <span className="font-bold text-white">{spec.lotSize} Qty</span>{' '}
                      <span className="text-[9px] text-gray-500">(Step: {spec.strikeStep})</span>
                    </div>
                    <div>
                      <span className="text-[10px] text-gray-400 block">
                        {strategyStyle === 'DIRECTIONAL' ? 'Est. 1 Lot Outlay:' : 'SPAN / Spread Margin:'}
                      </span>
                      <span className="font-bold text-amber-300">
                        {formatIndianCurrency(estMargin)}
                      </span>
                    </div>
                    <div>
                      <span className="text-[10px] text-gray-400 block">
                        {strategyStyle === 'DIRECTIONAL' ? 'Premium Outlay:' : 'Net Credit Upfront:'}
                      </span>
                      <span className={`font-bold ${strategyStyle !== 'DIRECTIONAL' ? 'text-emerald-400' : 'text-gray-300'}`}>
                        {strategyStyle !== 'DIRECTIONAL' ? `+${formatIndianCurrency(netCash)}` : formatIndianCurrency(spec.debitOutlay)}
                      </span>
                    </div>
                    <div>
                      <span className="text-[10px] text-gray-400 block">Net Theta / Day:</span>
                      <span className={`font-bold ${thetaEst > 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {thetaEst > 0 ? `+${formatIndianCurrency(thetaEst)}/d` : `-${formatIndianCurrency(Math.abs(thetaEst))}/d`}
                      </span>
                    </div>
                  </div>
                );
              })()}
            </div>

            <div className="strategy-fields">
              <div className="field-block">
                <label htmlFor="strat-name">Strategy name</label>
                <input
                  id="strat-name"
                  type="text"
                  value={name}
                  onChange={event => setName(event.target.value)}
                  maxLength={128}
                  placeholder="e.g. Morning trend continuation"
                />
              </div>
              <div className="field-block">
                <label htmlFor="strat-desc">Description <span>Optional</span></label>
                <textarea
                  id="strat-desc"
                  value={description}
                  onChange={event => setDescription(event.target.value)}
                  maxLength={512}
                  placeholder="What market behavior is this strategy designed for?"
                />
              </div>
            </div>

            {/* Strategy Execution Style Selector */}
            <div className="mt-4 p-3.5 bg-gray-900/60 rounded-lg border border-gray-800">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-semibold text-gray-200">Execution &amp; Greek Profile</span>
                <span className="text-[10px] text-gray-400 font-mono">Option Writing / Spreads</span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2" role="group" aria-label="Strategy Execution Style">
                <button
                  type="button"
                  onClick={() => setStrategyStyle('DIRECTIONAL')}
                  className={`p-2.5 rounded-lg border text-left transition-all ${
                    strategyStyle === 'DIRECTIONAL'
                      ? 'bg-blue-950/60 border-blue-500/60 text-blue-200 ring-1 ring-blue-500/30'
                      : 'bg-gray-800/60 border-gray-700/60 text-gray-400 hover:text-gray-200 hover:border-gray-600'
                  }`}
                >
                  <div className="flex items-center justify-between text-xs font-bold">
                    <span>Directional Buying</span>
                    <span className="text-[9px] px-1 py-0.5 rounded bg-blue-500/20 text-blue-300 font-mono">Long CE/PE</span>
                  </div>
                  <p className="text-[11px] text-gray-400 mt-1 leading-snug">
                    Debit outlay. Negative Theta (-Θ decay cost).
                  </p>
                </button>

                <button
                  type="button"
                  onClick={() => setStrategyStyle('CREDIT_SPREAD')}
                  className={`p-2.5 rounded-lg border text-left transition-all ${
                    strategyStyle === 'CREDIT_SPREAD'
                      ? 'bg-amber-950/60 border-amber-500/60 text-amber-200 ring-1 ring-amber-500/30'
                      : 'bg-gray-800/60 border-gray-700/60 text-gray-400 hover:text-gray-200 hover:border-gray-600'
                  }`}
                >
                  <div className="flex items-center justify-between text-xs font-bold">
                    <span className="text-amber-300">Credit Spread</span>
                    <span className="text-[9px] px-1 py-0.5 rounded bg-amber-500/20 text-amber-300 font-mono">+Θ Seller</span>
                  </div>
                  <p className="text-[11px] text-gray-400 mt-1 leading-snug">
                    Net credit upfront. Positive Theta decay profit (+₹Theta/day). Defined wing risk.
                  </p>
                </button>

                <button
                  type="button"
                  onClick={() => setStrategyStyle('HEDGED_WRITING')}
                  className={`p-2.5 rounded-lg border text-left transition-all ${
                    strategyStyle === 'HEDGED_WRITING'
                      ? 'bg-purple-950/60 border-purple-500/60 text-purple-200 ring-1 ring-purple-500/30'
                      : 'bg-gray-800/60 border-gray-700/60 text-gray-400 hover:text-gray-200 hover:border-gray-600'
                  }`}
                >
                  <div className="flex items-center justify-between text-xs font-bold">
                    <span className="text-purple-300">Hedged Writing</span>
                    <span className="text-[9px] px-1 py-0.5 rounded bg-purple-500/20 text-purple-300 font-mono">Condor/Strangle</span>
                  </div>
                  <p className="text-[11px] text-gray-400 mt-1 leading-snug">
                    Range-bound premium collection. Max theta capture with tail hedge protection.
                  </p>
                </button>
              </div>
            </div>
            <div className="builder-divider" />
            {renderConditionGroup('bullish', bullishConditions)}
            {renderConditionGroup('bearish', bearishConditions)}
            <div className="builder-footer">
              <span>{bullishConditions.length + bearishConditions.length} total rules</span>
              <button
                type="button"
                className="save-strategy"
                onClick={handleCreate}
                disabled={saving}
              >
                <Save /> {saving ? 'Saving...' : 'Save strategy'}
              </button>
            </div>
          </section>
        </ErrorBoundary>

        <ErrorBoundary compact title="Strategy Preview Error">
          <aside className="strategy-preview">
            <span className="eyebrow">Live preview</span>
            <div className="flex items-center gap-2 mt-2">
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded font-mono border ${
                strategyStyle === 'CREDIT_SPREAD'
                  ? 'bg-amber-500/10 text-amber-300 border-amber-500/30'
                  : strategyStyle === 'HEDGED_WRITING'
                  ? 'bg-purple-500/10 text-purple-300 border-purple-500/30'
                  : 'bg-blue-500/10 text-blue-300 border-blue-500/30'
              }`}>
                {strategyStyle === 'CREDIT_SPREAD' ? 'CREDIT SPREAD (+Θ HARVESTING)' : strategyStyle === 'HEDGED_WRITING' ? 'HEDGED WRITING (+Θ RANGE)' : 'DIRECTIONAL BUYING (-Θ DECAY)'}
              </span>
            </div>
            <h2>{name.trim() || 'Untitled strategy'}</h2>
            <p>{description.trim() || 'Your strategy summary will appear here as you write it.'}</p>

            {/* Greek & Capital Profile Box */}
            {(() => {
              const spec = UNDERLYING_SPECS.find(s => s.id === selectedUnderlying) || UNDERLYING_SPECS[0];
              const isCredit = strategyStyle === 'CREDIT_SPREAD';
              const isCondor = strategyStyle === 'HEDGED_WRITING';
              const estMargin = isCredit ? spec.spreadMargin : isCondor ? spec.spreadMargin * 1.4 : spec.debitOutlay;
              const thetaEst = isCredit ? spec.thetaGain : isCondor ? spec.thetaGain * 1.7 : -spec.thetaGain * 0.7;

              return (
                <div className="mt-4 p-3 rounded-lg bg-gray-900/90 border border-gray-800 space-y-2 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="text-gray-400">Target Underlying:</span>
                    <span className="font-mono font-bold text-white">
                      {spec.label} • Lot: {spec.lotSize} Qty
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-gray-400">Theta Dynamics:</span>
                    <span className={`font-mono font-semibold ${
                      strategyStyle !== 'DIRECTIONAL' ? 'text-emerald-400' : 'text-rose-400'
                    }`}>
                      {thetaEst > 0 ? `+${formatIndianCurrency(thetaEst)}/day (Decay Profit)` : `-${formatIndianCurrency(Math.abs(thetaEst))}/day (Decay Cost)`}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-gray-400">Capital Requirement:</span>
                    <span className="font-mono text-amber-300 font-bold">
                      {formatIndianCurrency(estMargin)} {strategyStyle !== 'DIRECTIONAL' ? '(SPAN Margin)' : '(Outlay)'}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-gray-400">Payoff Profile:</span>
                    <span className="font-mono text-emerald-400">
                      {strategyStyle === 'CREDIT_SPREAD' ? 'Defined Net Credit Max Gain' : strategyStyle === 'HEDGED_WRITING' ? 'Range-Bound Max Credit' : 'Directional Asymmetric Payoff'}
                    </span>
                  </div>
                </div>
              );
            })()}

            <div className="preview-rule-title">Rule summary</div>
            <div className="preview-rule">
              <span className="preview-line bullish-line" />
              <div>
                <strong>{bullishConditions.length} entry rule{bullishConditions.length === 1 ? '' : 's'}</strong>
                <small>Long bias conditions</small>
              </div>
            </div>
            <div className="preview-rule">
              <span className="preview-line bearish-line" />
              <div>
                <strong>{bearishConditions.length} exit rule{bearishConditions.length === 1 ? '' : 's'}</strong>
                <small>Short bias conditions</small>
              </div>
            </div>
            <div className="preview-note">Conditions are stored with the strategy and ready for engine integration.</div>
          </aside>
        </ErrorBoundary>
      </div>

      <ErrorBoundary compact title="Strategy Library Error">
        <section className="strategy-library">
          <div className="library-heading">
            <div>
              <span className="eyebrow">Saved workspace</span>
              <h2>Your strategies</h2>
            </div>
            <span>{strategies.length} / 50</span>
          </div>
          {strategies.length === 0 ? (
            <div className="library-empty">No saved strategies yet. Your first rule set will appear here.</div>
          ) : (
            <div className="strategy-cards">
              {strategies.map((strategy, index) => (
                <div key={`${strategy.name}-${index}`} className="saved-strategy">
                  <span className="saved-index">{String(index + 1).padStart(2, '0')}</span>
                  <div>
                    <div className="flex items-center gap-2">
                      <h3>{strategy.name}</h3>
                      {strategy.strategy_style && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-300 font-mono border border-gray-700">
                          {strategy.strategy_style.replace('_', ' ')}
                        </span>
                      )}
                    </div>
                    <p>{strategy.description || 'No description provided.'}</p>
                    <span className="condition-summary">
                      {(strategy.bullish_conditions?.length || 0) + (strategy.bearish_conditions?.length || 0)} conditions
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </ErrorBoundary>
    </div>
  );
};

export default StrategyBuilder;
