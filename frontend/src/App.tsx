import { BrowserRouter as Router, Routes, Route, Link, useLocation } from 'react-router-dom';
import Dashboard from './pages/Dashboard';
import Portfolio from './pages/Portfolio';
import BacktestUI from './pages/BacktestUI';
import TrainingUI from './pages/TrainingUI';
import Analytics from './pages/Analytics';
import StrategyBuilder from './pages/StrategyBuilder';
import AIJournal from './pages/AIJournal';
import ErrorBoundary from './components/ErrorBoundary';
import { LineChart, Briefcase, Activity, BrainCircuit, BarChart2, Wrench, BookOpen, CircleHelp, Radio, Settings2 } from 'lucide-react';

const Navigation = () => {
  const location = useLocation();

  const navItems = [
    { path: '/', label: 'Dashboard', icon: <LineChart className="w-5 h-5 mr-2" /> },
    { path: '/portfolio', label: 'Portfolio', icon: <Briefcase className="w-5 h-5 mr-2" /> },
    { path: '/analytics', label: 'Analytics', icon: <BarChart2 className="w-5 h-5 mr-2" /> },
    { path: '/backtest', label: 'Backtesting', icon: <Activity className="w-5 h-5 mr-2" /> },
    { path: '/training', label: 'Training', icon: <BrainCircuit className="w-5 h-5 mr-2" /> },
    { path: '/strategy', label: 'Strategies', icon: <Wrench className="w-5 h-5 mr-2" /> },
    { path: '/ai-journal', label: 'AI Journal', icon: <BookOpen className="w-5 h-5 mr-2" /> },
  ];

  return (
    <aside className="sidebar" aria-label="Main navigation">
      <Link to="/" className="brand" aria-label="Signal Desk home">
        <span className="brand-mark">S</span>
        <span><strong>Signal</strong><small>DESK / AI TRADING</small></span>
      </Link>
      <div className="nav-label">Workspace</div>
      <nav className="nav-list">
        {navItems.map((item) => (
          <Link
            key={item.path}
            to={item.path}
            aria-current={location.pathname === item.path ? 'page' : undefined}
            className={`nav-link ${location.pathname === item.path ? 'active' : ''}`}
          >
            {item.icon}
            <span>{item.label}</span>
          </Link>
        ))}
      </nav>
      <div className="sidebar-bottom">
        <div className="system-card"><span className="live-dot" /> PAPER SYSTEM <strong>ONLINE</strong></div>
        <Link to="/strategy" className="nav-link muted"><Settings2 /> <span>Workspace settings</span></Link>
        <a className="nav-link muted" href="/docs"><CircleHelp /><span>API documentation</span></a>
      </div>
    </aside>
  );
};

function App() {
  return (
    <Router basename="/app">
      <ErrorBoundary>
        <div className="app-shell">
          <Navigation />
          <main className="main-content">
            <header className="topbar">
              <div><span className="eyebrow">MARKET OPERATIONS</span><span className="topbar-date">Thursday, 21 August 2026</span></div>
              <div className="topbar-actions"><span className="market-status"><Radio /> NSE SESSION <b>LIVE</b></span><span className="avatar">R</span></div>
            </header>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/portfolio" element={<Portfolio />} />
              <Route path="/analytics" element={<Analytics />} />
              <Route path="/backtest" element={<BacktestUI />} />
              <Route path="/training" element={<TrainingUI />} />
              <Route path="/strategy" element={<StrategyBuilder />} />
              <Route path="/ai-journal" element={<AIJournal />} />
            </Routes>
          </main>
        </div>
      </ErrorBoundary>
    </Router>
  );
}

export default App;
