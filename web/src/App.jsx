import { useState, useEffect } from 'react';
import axios from 'axios';
import { LineChart, LayoutDashboard, Settings, Activity, BookOpen, ToggleLeft, ToggleRight, Loader2 } from 'lucide-react';
import TradingViewWidget from './components/TradingViewWidget';
import MetricsPanel from './components/MetricsPanel';
import TradeJournal from './components/TradeJournal';

// Use standard API URL (FastAPI)
const API_URL = 'http://127.0.0.1:8000/api/v1/dashboard';

function App() {
  const [activeTab, setActiveTab] = useState('market');
  const [metrics, setMetrics] = useState(null);
  const [trades, setTrades] = useState({ entries: [], exits: [] });
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchData();
    // Auto-refresh every 30 seconds
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, []);

  const fetchData = async () => {
    try {
      const [metricsRes, tradesRes, configRes] = await Promise.all([
        axios.get(`${API_URL}/metrics`),
        axios.get(`${API_URL}/trades`),
        axios.get(`${API_URL}/config`),
      ]);
      setMetrics(metricsRes.data);
      setTrades(tradesRes.data);
      setConfig(configRes.data);
    } catch (error) {
      console.error("Failed to fetch dashboard data", error);
    } finally {
      setLoading(false);
    }
  };

  const toggleEnvironment = async () => {
    if (!config) return;
    const newEnv = config.environment === 'LIVE' ? 'PAPER' : 'LIVE';
    
    // Optimistic UI update
    setConfig({ ...config, environment: newEnv });
    
    try {
      await axios.post(`${API_URL}/config`, { environment: newEnv });
    } catch (error) {
      // Revert on failure
      setConfig({ ...config, environment: config.environment });
      console.error("Failed to update environment", error);
    }
  };

  if (loading) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-12 w-12 animate-spin text-primary" />
          <p className="text-text-muted font-medium tracking-wide">INITIALIZING AI SYSTEMS...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background">
      {/* Sidebar Navigation */}
      <aside className="glass w-64 flex-shrink-0 flex flex-col justify-between border-r border-white/10 z-10">
        <div>
          <div className="p-6">
            <h1 className="text-xl font-bold bg-gradient-to-r from-blue-400 to-emerald-400 bg-clip-text text-transparent">
              AI Algorithmic Trader
            </h1>
            <p className="text-xs text-text-muted mt-1 uppercase tracking-wider font-semibold">
              Personal Edition
            </p>
          </div>
          
          <nav className="mt-4 flex flex-col gap-2 px-4">
            <NavItem 
              icon={<LineChart size={20} />} 
              label="Live Markets" 
              active={activeTab === 'market'} 
              onClick={() => setActiveTab('market')} 
            />
            <NavItem 
              icon={<LayoutDashboard size={20} />} 
              label="Performance" 
              active={activeTab === 'performance'} 
              onClick={() => setActiveTab('performance')} 
            />
            <NavItem 
              icon={<BookOpen size={20} />} 
              label="Trade Journal" 
              active={activeTab === 'journal'} 
              onClick={() => setActiveTab('journal')} 
            />
            <NavItem 
              icon={<Settings size={20} />} 
              label="Configuration" 
              active={activeTab === 'config'} 
              onClick={() => setActiveTab('config')} 
            />
          </nav>
        </div>

        {/* Global Environment Toggle */}
        <div className="p-6 border-t border-white/10">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-text-muted">Environment</span>
            <span className={`text-xs font-bold px-2 py-1 rounded ${config?.environment === 'LIVE' ? 'bg-danger/20 text-danger' : 'bg-success/20 text-success'}`}>
              {config?.environment || 'PAPER'}
            </span>
          </div>
          <button 
            onClick={toggleEnvironment}
            className="w-full flex items-center justify-center gap-2 py-2 rounded-lg bg-surface hover:bg-surface-hover transition-colors border border-white/5"
          >
            {config?.environment === 'LIVE' ? <ToggleRight className="text-danger" /> : <ToggleLeft className="text-success" />}
            <span className="text-sm font-medium">Toggle Mode</span>
          </button>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col overflow-hidden relative">
        {/* Background glow effects */}
        <div className="absolute top-[-20%] left-[-10%] w-[50%] h-[50%] rounded-full bg-primary/10 blur-[120px] pointer-events-none" />
        <div className="absolute bottom-[-20%] right-[-10%] w-[40%] h-[40%] rounded-full bg-emerald-500/10 blur-[100px] pointer-events-none" />
        
        <header className="glass h-16 flex-shrink-0 flex items-center px-8 border-b border-white/10 z-10">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            {activeTab === 'market' && <><LineChart className="text-primary" /> Live Market Intelligence</>}
            {activeTab === 'performance' && <><LayoutDashboard className="text-emerald-400" /> Portfolio Performance</>}
            {activeTab === 'journal' && <><BookOpen className="text-amber-400" /> Trade Journal</>}
            {activeTab === 'config' && <><Settings className="text-slate-400" /> System Configuration</>}
          </h2>
        </header>

        <div className="flex-1 overflow-auto p-8 z-10">
          <div className="h-full w-full max-w-7xl mx-auto animate-in fade-in duration-500">
            {activeTab === 'market' && <TradingViewWidget watchlists={config?.watchlist || ['NSE:NIFTY']} />}
            {activeTab === 'performance' && <MetricsPanel metrics={metrics} exits={trades?.exits || []} />}
            {activeTab === 'journal' && <TradeJournal trades={trades} />}
            {activeTab === 'config' && (
              <div className="glass rounded-xl p-8 max-w-2xl text-center">
                 <Settings size={48} className="mx-auto text-text-muted mb-4 opacity-50" />
                 <h3 className="text-xl font-bold mb-2">Configuration Settings</h3>
                 <p className="text-text-muted">
                    Advanced configuration via the React dashboard is under construction. 
                    <br/>Currently running with Budget: ₹{config?.capital?.toLocaleString() || '100,000'}
                 </p>
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}

function NavItem({ icon, label, active, onClick }) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-3 px-4 py-3 rounded-lg transition-all duration-200 ${
        active 
          ? 'bg-primary/15 text-primary font-medium border border-primary/20' 
          : 'text-text-muted hover:bg-white/5 hover:text-text'
      }`}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

export default App;
