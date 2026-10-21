import { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';
import { Plus, Trash2, Save, SlidersHorizontal, CheckCircle2 } from 'lucide-react';

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

const StrategyBuilder = () => {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [strategies, setStrategies] = useState<any[]>([]);
  const [bullishConditions, setBullishConditions] = useState<Condition[]>([createCondition()]);
  const [bearishConditions, setBearishConditions] = useState<Condition[]>([createCondition()]);
  const [error, setError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [saving, setSaving] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

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
    loadStrategies();
    return () => {
      if (abortRef.current) {
        abortRef.current.abort();
      }
    };
  }, [loadStrategies]);

  const handleCreate = async () => {
    const trimmedName = name.trim();
    if (!trimmedName) {
      setError('Give this strategy a name before saving.');
      return;
    }
    const allConditions = [...bullishConditions, ...bearishConditions];
    if (allConditions.some(c => !c.value.trim())) {
      setError('Complete every condition value before saving.');
      return;
    }

    try {
      setError('');
      setSaving(true);
      await axios.post('/api/v1/strategy/create', {
        name: trimmedName,
        description: description.trim(),
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
      setTimeout(() => setSuccessMessage(''), 5000);
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
    setter(current => (current.length === 1 ? [createCondition()] : current.filter(c => c.id !== id)));
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
        {conditions.map((condition, index) => (
          <div className="condition-row" key={condition.id}>
            <span className="condition-number">{String(index + 1).padStart(2, '0')}</span>
            <label className="sr-only" htmlFor={`${side}-indicator-${condition.id}`}>Indicator</label>
            <select
              id={`${side}-indicator-${condition.id}`}
              value={condition.indicator}
              onChange={event => updateCondition(side, condition.id, 'indicator', event.target.value)}
            >
              {indicatorOptions.map(option => <option key={option} value={option}>{option}</option>)}
            </select>
            <label className="sr-only" htmlFor={`${side}-operator-${condition.id}`}>Operator</label>
            <select
              id={`${side}-operator-${condition.id}`}
              value={condition.operator}
              onChange={event => updateCondition(side, condition.id, 'operator', event.target.value)}
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
        ))}
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
        <section className="builder-panel">
          <div className="builder-panel-heading">
            <div>
              <span className="eyebrow">Strategy details</span>
              <h2>New rule set</h2>
            </div>
            <span className="draft-status">DRAFT</span>
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

        <aside className="strategy-preview">
          <span className="eyebrow">Live preview</span>
          <h2>{name.trim() || 'Untitled strategy'}</h2>
          <p>{description.trim() || 'Your strategy summary will appear here as you write it.'}</p>
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
      </div>

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
                  <h3>{strategy.name}</h3>
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
    </div>
  );
};

export default StrategyBuilder;
