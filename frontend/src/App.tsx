import { Suspense, lazy, useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, Link, useLocation } from 'react-router-dom';
import ErrorBoundary from './components/ErrorBoundary';
import { SettingsModal } from './components/SettingsModal';
import {
  LineChart,
  Briefcase,
  Activity,
  BrainCircuit,
  BarChart2,
  Wrench,
  BookOpen,
  CircleHelp,
  Radio,
  Settings2,
  Flame,
} from 'lucide-react';

const Dashboard = lazy(() => import('./pages/Dashboard'));
const Portfolio = lazy(() => import('./pages/Portfolio'));
const BacktestUI = lazy(() => import('./pages/BacktestUI'));
const TrainingUI = lazy(() => import('./pages/TrainingUI'));
const Analytics = lazy(() => import('./pages/Analytics'));
const StrategyBuilder = lazy(() => import('./pages/StrategyBuilder'));
const AIJournal = lazy(() => import('./pages/AIJournal'));
const SwingToolkit = lazy(() => import('./pages/SwingToolkit'));

const RouteLoading = () => (
  <div className="chart-state" role="status">
    <div className="loader-line" />
    <span>Loading view...</span>
  </div>
);

const NotFound = () => (
  <div className="state-panel text-center max-w-md mx-auto my-16" role="alert">
    <strong className="text-base text-gray-200">404 — Surface not found</strong>
    <p className="text-gray-400 text-sm my-2">The requested operational view does not exist on this trading desk.</p>
    <Link to="/" className="retry-button inline-block text-center mt-2">
      Return to Dashboard
    </Link>
  </div>
);

const Navigation = ({ onOpenSettings }: { onOpenSettings: () => void }) => {
  const location = useLocation();

  const navItems = [
    { path: '/', label: 'Dashboard', icon: <LineChart className="w-5 h-5 mr-2" /> },
    { path: '/swing-toolkit', label: 'Swing Toolkit', icon: <Flame className="w-5 h-5 mr-2 text-orange-400" /> },
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
        <span>
          <strong>Signal</strong>
          <small>DESK / AI TRADING</small>
        </span>
      </Link>
      <div className="nav-label">Workspace</div>
      <nav className="nav-list">
        {navItems.map(item => (
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
        <div className="system-card">
          <span className="live-dot" /> PAPER SYSTEM <strong>ONLINE</strong>
        </div>
        <button
          type="button"
          onClick={onOpenSettings}
          className="nav-link muted w-full text-left bg-transparent border-0 cursor-pointer"
        >
          <Settings2 /> <span>Workspace settings</span>
        </button>
        <a
          className="nav-link muted"
          href="/docs"
          target="_blank"
          rel="noopener noreferrer"
        >
          <CircleHelp />
          <span>API documentation</span>
        </a>
      </div>
    </aside>
  );
};

function App() {
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isAuthRequired, setIsAuthRequired] = useState(false);

  useEffect(() => {
    const handleAuthRequired = () => {
      setIsAuthRequired(true);
      setIsSettingsOpen(true);
    };
    window.addEventListener('signal-desk-auth-required', handleAuthRequired);
    return () => {
      window.removeEventListener('signal-desk-auth-required', handleAuthRequired);
    };
  }, []);

  const todayStr = new Intl.DateTimeFormat('en-IN', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  }).format(new Date());

  return (
    <Router basename="/app">
      <ErrorBoundary>
        <a href="#main-content" className="sr-only focus:not-sr-only skip-link">
          Skip to content
        </a>
        <div className="app-shell">
          <Navigation onOpenSettings={() => setIsSettingsOpen(true)} />
          <SettingsModal
            isOpen={isSettingsOpen}
            onClose={() => {
              setIsSettingsOpen(false);
              setIsAuthRequired(false);
            }}
            initialAuthError={isAuthRequired}
          />
          <main id="main-content" className="main-content" tabIndex={-1}>
            <header className="topbar">
              <div>
                <span className="eyebrow">MARKET OPERATIONS</span>
                <span className="topbar-date">{todayStr}</span>
              </div>
              <div className="topbar-actions">
                <span className="market-status">
                  <Radio /> NSE SESSION <b>LIVE</b>
                </span>
                <span className="avatar">R</span>
              </div>
            </header>
            <ErrorBoundary
              fallback={(err, reset) => (
                <div className="state-panel" role="alert">
                  <strong>An error occurred in this view.</strong>
                  <p className="text-xs text-gray-400">{err.message}</p>
                  <button className="retry-button" onClick={reset}>
                    Try again
                  </button>
                </div>
              )}
            >
              <Suspense fallback={<RouteLoading />}>
                <Routes>
                  <Route path="/" element={<Dashboard />} />
                  <Route path="/swing-toolkit" element={<SwingToolkit />} />
                  <Route path="/portfolio" element={<Portfolio />} />
                  <Route path="/analytics" element={<Analytics />} />
                  <Route path="/backtest" element={<BacktestUI />} />
                  <Route path="/training" element={<TrainingUI />} />
                  <Route path="/strategy" element={<StrategyBuilder />} />
                  <Route path="/ai-journal" element={<AIJournal />} />
                  <Route path="*" element={<NotFound />} />
                </Routes>
              </Suspense>
            </ErrorBoundary>
          </main>
        </div>
      </ErrorBoundary>
    </Router>
  );
}

export default App;
