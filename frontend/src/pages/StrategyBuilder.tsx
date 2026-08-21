import { useState, useEffect } from 'react';
import axios from 'axios';

const StrategyBuilder = () => {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [strategies, setStrategies] = useState<any[]>([]);
  
  const loadStrategies = async () => {
    try {
        const res = await axios.get('/api/v1/strategy/list');
        setStrategies(res.data.strategies);
    } catch (err) {
        console.error(err);
    }
  };

  useEffect(() => {
    loadStrategies();
  }, []);

  const handleCreate = async () => {
    if (!name) return;
    try {
        await axios.post('/api/v1/strategy/create', {
            name,
            description,
            bullish_conditions: [],
            bearish_conditions: []
        });
        setName('');
        setDescription('');
        loadStrategies();
    } catch (err) {
        console.error(err);
    }
  };

  return (
    <div className="space-y-6">
      <div className="bg-gray-900 p-6 rounded-lg border border-gray-800">
        <h2 className="text-2xl font-bold text-white mb-4">No-Code Strategy Builder</h2>
        
        <div className="space-y-4 max-w-md">
            <div>
                <label htmlFor="strat-name" className="block text-sm text-gray-400 mb-1">Strategy Name</label>
                <input
                    id="strat-name"
                    type="text"
                    value={name}
                    onChange={e => setName(e.target.value)}
                    maxLength={128}
                    className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white"
                />
            </div>
            <div>
                <label htmlFor="strat-desc" className="block text-sm text-gray-400 mb-1">Description</label>
                <textarea
                    id="strat-desc"
                    value={description}
                    onChange={e => setDescription(e.target.value)}
                    maxLength={512}
                    className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white"
                />
            </div>
            
            <div className="bg-gray-800 p-4 border border-gray-700 rounded text-gray-400 text-sm">
                Advanced condition builder (e.g., RSI {'>'} 70 AND MACD Cross) UI goes here in Phase 4. 
                For now, you can define basic metadata.
            </div>

            <button 
                onClick={handleCreate}
                className="bg-blue-600 hover:bg-blue-700 px-6 py-2 rounded text-white font-medium transition-colors"
            >
                Create Strategy
            </button>
        </div>
      </div>

      <div className="bg-gray-900 p-6 rounded-lg border border-gray-800">
        <h3 className="text-lg font-bold text-white mb-4">Your Custom Strategies</h3>
        {strategies.length === 0 ? (
            <div className="text-gray-500">No custom strategies built yet.</div>
        ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {strategies.map((s, idx) => (
                    <div key={idx} className="bg-gray-800 p-4 rounded border border-gray-700">
                        <div className="font-bold text-blue-400 text-lg">{s.name}</div>
                        <div className="text-sm text-gray-400 mt-1">{s.description}</div>
                        <div className="mt-3 text-xs text-gray-500 bg-gray-900 p-2 rounded">
                            0 Conditions Defined
                        </div>
                    </div>
                ))}
            </div>
        )}
      </div>
    </div>
  );
};

export default StrategyBuilder;
