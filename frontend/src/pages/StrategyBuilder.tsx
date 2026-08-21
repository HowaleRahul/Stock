import { useState, useEffect } from 'react';
import axios from 'axios';
import { Plus, Trash2, Save, SlidersHorizontal } from 'lucide-react';

interface Condition {
    indicator: string;
    operator: string;
    value: string;
}

const indicatorOptions = ['RSI', 'MACD', 'EMA 20', 'EMA 50', 'Price', 'Volume'];
const operatorOptions = ['>', '<', '>=', '<=', 'crosses above', 'crosses below'];

const blankCondition = (): Condition => ({ indicator: 'RSI', operator: '>', value: '' });

const StrategyBuilder = () => {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [strategies, setStrategies] = useState<any[]>([]);
    const [bullishConditions, setBullishConditions] = useState<Condition[]>([blankCondition()]);
    const [bearishConditions, setBearishConditions] = useState<Condition[]>([blankCondition()]);
    const [error, setError] = useState('');
    const [saving, setSaving] = useState(false);
  
  const loadStrategies = async () => {
    try {
        const res = await axios.get('/api/v1/strategy/list');
        setStrategies(res.data.strategies);
        setError('');
    } catch (err: any) {
        setError(err?.response?.status ? `Strategy service unavailable (HTTP ${err.response.status}).` : 'Backend is offline. Start the API server and retry.');
    }
  };

  useEffect(() => {
    loadStrategies();
  }, []);

  const handleCreate = async () => {
        if (!name.trim()) {
            setError('Give this strategy a name before saving.');
            return;
        }
        const allConditions = [...bullishConditions, ...bearishConditions];
        if (allConditions.some(condition => !condition.value.trim())) {
            setError('Complete every condition value before saving.');
            return;
        }
    try {
        setError('');
                setSaving(true);
        await axios.post('/api/v1/strategy/create', {
                        name: name.trim(),
            description,
                        bullish_conditions: bullishConditions,
                        bearish_conditions: bearishConditions,
        });
        setName('');
        setDescription('');
                setBullishConditions([blankCondition()]);
                setBearishConditions([blankCondition()]);
                await loadStrategies();
    } catch (err: any) {
        setError(err?.response?.data?.detail || 'Strategy could not be created.');
        } finally {
                setSaving(false);
    }
  };

    const updateCondition = (side: 'bullish' | 'bearish', index: number, key: keyof Condition, value: string) => {
        const setter = side === 'bullish' ? setBullishConditions : setBearishConditions;
        setter(current => current.map((condition, conditionIndex) => conditionIndex === index ? { ...condition, [key]: value } : condition));
    };

    const removeCondition = (side: 'bullish' | 'bearish', index: number) => {
        const setter = side === 'bullish' ? setBullishConditions : setBearishConditions;
        setter(current => current.length === 1 ? [blankCondition()] : current.filter((_, conditionIndex) => conditionIndex !== index));
    };

    const renderConditionGroup = (side: 'bullish' | 'bearish', conditions: Condition[]) => (
        <section className={`condition-group ${side}`} aria-labelledby={`${side}-conditions-heading`}>
            <div className="condition-group-heading">
                <div><span className="condition-dot" /><h3 id={`${side}-conditions-heading`}>{side === 'bullish' ? 'Entry bias' : 'Exit bias'}</h3></div>
                <span>{conditions.length} rule{conditions.length === 1 ? '' : 's'}</span>
            </div>
            <p className="condition-helper">All rules must be true</p>
            <div className="condition-list">
                {conditions.map((condition, index) => (
                    <div className="condition-row" key={`${side}-${index}`}>
                        <span className="condition-number">{String(index + 1).padStart(2, '0')}</span>
                        <label className="sr-only" htmlFor={`${side}-indicator-${index}`}>Indicator</label>
                        <select id={`${side}-indicator-${index}`} value={condition.indicator} onChange={event => updateCondition(side, index, 'indicator', event.target.value)}>
                            {indicatorOptions.map(option => <option key={option}>{option}</option>)}
                        </select>
                        <label className="sr-only" htmlFor={`${side}-operator-${index}`}>Operator</label>
                        <select id={`${side}-operator-${index}`} value={condition.operator} onChange={event => updateCondition(side, index, 'operator', event.target.value)}>
                            {operatorOptions.map(option => <option key={option}>{option}</option>)}
                        </select>
                        <label className="sr-only" htmlFor={`${side}-value-${index}`}>Value</label>
                        <input id={`${side}-value-${index}`} value={condition.value} onChange={event => updateCondition(side, index, 'value', event.target.value)} placeholder="Value" maxLength={64} />
                        <button type="button" className="condition-remove" onClick={() => removeCondition(side, index)} aria-label={`Remove ${side} rule ${index + 1}`} title="Remove rule"><Trash2 /></button>
                    </div>
                ))}
            </div>
            <button type="button" className="add-condition" onClick={() => (side === 'bullish' ? setBullishConditions : setBearishConditions)(conditions => [...conditions, blankCondition()])}><Plus /> Add rule</button>
        </section>
    );

  return (
    <div className="strategy-page">
      {error && <div className="state-panel compact" role="alert"><strong>{error}</strong><button className="retry-button" onClick={loadStrategies}>Retry connection</button></div>}
      <div className="page-heading strategy-heading">
        <div><span className="eyebrow">Rule composer / 07</span><h1>Build a strategy</h1><p>Translate your market read into rules the engine can evaluate.</p></div>
        <div className="strategy-badge"><SlidersHorizontal /> NO-CODE MODE</div>
      </div>
      <div className="strategy-layout">
        <section className="builder-panel">
          <div className="builder-panel-heading"><div><span className="eyebrow">Strategy details</span><h2>New rule set</h2></div><span className="draft-status">DRAFT</span></div>
          <div className="strategy-fields">
            <div className="field-block"><label htmlFor="strat-name">Strategy name</label><input id="strat-name" type="text" value={name} onChange={event => setName(event.target.value)} maxLength={128} placeholder="e.g. Morning trend continuation" /></div>
            <div className="field-block"><label htmlFor="strat-desc">Description <span>Optional</span></label><textarea id="strat-desc" value={description} onChange={event => setDescription(event.target.value)} maxLength={512} placeholder="What market behavior is this strategy designed for?" /></div>
          </div>
          <div className="builder-divider" />
          {renderConditionGroup('bullish', bullishConditions)}
          {renderConditionGroup('bearish', bearishConditions)}
          <div className="builder-footer"><span>{bullishConditions.length + bearishConditions.length} total rules</span><button type="button" className="save-strategy" onClick={handleCreate} disabled={saving}><Save /> {saving ? 'Saving...' : 'Save strategy'}</button></div>
        </section>
        <aside className="strategy-preview"><span className="eyebrow">Live preview</span><h2>{name.trim() || 'Untitled strategy'}</h2><p>{description.trim() || 'Your strategy summary will appear here as you write it.'}</p><div className="preview-rule-title">Rule summary</div><div className="preview-rule"><span className="preview-line bullish-line" /><div><strong>{bullishConditions.length} entry rule{bullishConditions.length === 1 ? '' : 's'}</strong><small>Long bias conditions</small></div></div><div className="preview-rule"><span className="preview-line bearish-line" /><div><strong>{bearishConditions.length} exit rule{bearishConditions.length === 1 ? '' : 's'}</strong><small>Short bias conditions</small></div></div><div className="preview-note">Conditions are stored with the strategy and ready for engine integration.</div></aside>
      </div>
      <section className="strategy-library">
        <div className="library-heading"><div><span className="eyebrow">Saved workspace</span><h2>Your strategies</h2></div><span>{strategies.length} / 50</span></div>
        {strategies.length === 0 ? (
            <div className="library-empty">No saved strategies yet. Your first rule set will appear here.</div>
        ) : (
            <div className="strategy-cards">
                {strategies.map((strategy, index) => (
                    <div key={`${strategy.name}-${index}`} className="saved-strategy">
                        <span className="saved-index">{String(index + 1).padStart(2, '0')}</span><div><h3>{strategy.name}</h3><p>{strategy.description || 'No description provided.'}</p><span className="condition-summary">{(strategy.bullish_conditions?.length || 0) + (strategy.bearish_conditions?.length || 0)} conditions</span></div>
                    </div>
                ))}
            </div>
        )}
      </section>
    </div>
  );
};

export default StrategyBuilder;
