import { BrowserRouter as Router, Routes, Route, Link, useLocation } from 'react-router-dom';
import Dashboard from './pages/Dashboard';
import Portfolio from './pages/Portfolio';
import BacktestUI from './pages/BacktestUI';
import TrainingUI from './pages/TrainingUI';
import Analytics from './pages/Analytics';
import StrategyBuilder from './pages/StrategyBuilder';
import AIJournal from './pages/AIJournal';
import ErrorBoundary from './components/ErrorBoundary';
import { LineChart, Briefcase, Activity, BrainCircuit, BarChart2, Wrench, BookOpen } from 'lucide-react';

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
    <nav className="bg-gray-900 border-b border-gray-800 text-white p-4" aria-label="Main navigation">
      <div className="container mx-auto flex items-center justify-between">
        <div className="flex items-center space-x-6">
          <h1 className="text-xl font-bold bg-gradient-to-r from-blue-400 to-emerald-400 bg-clip-text text-transparent">
            AI Trading
          </h1>
          <div className="flex space-x-1" role="navigation">
            {navItems.map((item) => (
              <Link
                key={item.path}
                to={item.path}
                aria-current={location.pathname === item.path ? 'page' : undefined}
                className={`flex items-center px-3 py-2 rounded-md transition-colors text-sm ${
                  location.pathname === item.path
                    ? 'bg-blue-600 text-white'
                    : 'text-gray-400 hover:bg-gray-800 hover:text-white'
                }`}
              >
                {item.icon}
                {item.label}
              </Link>
            ))}
          </div>
        </div>
      </div>
    </nav>
  );
};

function App() {
  return (
    <Router basename="/app">
      <ErrorBoundary>
        <div className="min-h-screen bg-gray-950 text-gray-100 flex flex-col">
          <Navigation />
          <main className="flex-grow p-6">
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
