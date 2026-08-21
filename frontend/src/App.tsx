import { BrowserRouter as Router, Routes, Route, Link, useLocation } from 'react-router-dom';
import Dashboard from './pages/Dashboard';
import Portfolio from './pages/Portfolio';
import BacktestUI from './pages/BacktestUI';
import TrainingUI from './pages/TrainingUI';
import { LineChart, Briefcase, Activity, BrainCircuit } from 'lucide-react';

const Navigation = () => {
  const location = useLocation();
  
  const navItems = [
    { path: '/', label: 'Dashboard', icon: <LineChart className="w-5 h-5 mr-2" /> },
    { path: '/portfolio', label: 'Portfolio', icon: <Briefcase className="w-5 h-5 mr-2" /> },
    { path: '/backtest', label: 'Backtesting', icon: <Activity className="w-5 h-5 mr-2" /> },
    { path: '/training', label: 'Model Training', icon: <BrainCircuit className="w-5 h-5 mr-2" /> },
  ];

  return (
    <nav className="bg-gray-900 border-b border-gray-800 text-white p-4">
      <div className="container mx-auto flex items-center justify-between">
        <div className="flex items-center space-x-6">
          <h1 className="text-xl font-bold bg-gradient-to-r from-blue-400 to-emerald-400 bg-clip-text text-transparent">
            AI Trading
          </h1>
          <div className="flex space-x-2">
            {navItems.map((item) => (
              <Link
                key={item.path}
                to={item.path}
                className={`flex items-center px-4 py-2 rounded-md transition-colors ${
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
      <div className="min-h-screen bg-gray-950 text-gray-100 flex flex-col">
        <Navigation />
        <main className="flex-grow p-6">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/portfolio" element={<Portfolio />} />
            <Route path="/backtest" element={<BacktestUI />} />
            <Route path="/training" element={<TrainingUI />} />
          </Routes>
        </main>
      </div>
    </Router>
  );
}

export default App;
