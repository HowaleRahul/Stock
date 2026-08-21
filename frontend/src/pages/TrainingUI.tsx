import { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { Play, Square, Terminal, Activity } from 'lucide-react';

const TrainingUI = () => {
  const [isTraining, setIsTraining] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const logsEndRef = useRef<HTMLDivElement>(null);

  const fetchStatus = async () => {
    try {
      const res = await axios.get('/api/v1/training/status');
      setIsTraining(res.data.is_training);
      setLogs(res.data.logs);
    } catch (err) {
      console.error("Failed to fetch training status:", err);
    }
  };

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 2000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  const handleStart = async () => {
    try {
      await axios.post('/api/v1/training/start');
      fetchStatus();
    } catch (err) {
      console.error(err);
    }
  };

  const handleStop = async () => {
    try {
      await axios.post('/api/v1/training/stop');
      fetchStatus();
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="space-y-6">
      <div className="bg-gray-900 p-6 rounded-lg border border-gray-800 flex justify-between items-center">
        <div>
          <h2 className="text-2xl font-bold text-white flex items-center">
            <Activity className="w-6 h-6 mr-2 text-blue-400" />
            AI Training Engine
          </h2>
          <p className="text-gray-400 mt-1 text-sm">
            Continuous reinforcement learning via AlphaZero mode. 
            The brain incrementally learns by playing millions of simulated trades.
          </p>
        </div>
        
        <div className="flex gap-4">
          <button 
            onClick={handleStart}
            disabled={isTraining}
            className={`flex items-center px-6 py-2 rounded font-medium transition-colors ${
              isTraining 
                ? 'bg-gray-800 text-gray-500 cursor-not-allowed' 
                : 'bg-emerald-600 hover:bg-emerald-700 text-white'
            }`}
          >
            <Play className="w-4 h-4 mr-2" /> Start Training
          </button>
          <button 
            onClick={handleStop}
            disabled={!isTraining}
            className={`flex items-center px-6 py-2 rounded font-medium transition-colors ${
              !isTraining 
                ? 'bg-gray-800 text-gray-500 cursor-not-allowed' 
                : 'bg-red-600 hover:bg-red-700 text-white'
            }`}
          >
            <Square className="w-4 h-4 mr-2" /> Stop
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-gray-900 p-4 rounded-lg border border-gray-800">
          <div className="text-gray-400 text-sm">Engine Status</div>
          <div className="flex items-center mt-1">
            <div className={`w-3 h-3 rounded-full mr-2 ${isTraining ? 'bg-emerald-500 animate-pulse' : 'bg-red-500'}`}></div>
            <span className="font-bold text-xl">{isTraining ? 'RUNNING' : 'STOPPED'}</span>
          </div>
        </div>
      </div>

      <div className="bg-black p-4 rounded-lg border border-gray-800 font-mono text-sm relative">
        <div className="flex items-center text-gray-500 border-b border-gray-800 pb-2 mb-2">
          <Terminal className="w-4 h-4 mr-2" />
          Training Console Output
        </div>
        
        <div className="h-96 overflow-y-auto space-y-1 scrollbar-thin scrollbar-thumb-gray-700">
          {logs.length === 0 ? (
            <div className="text-gray-600 italic">No logs available. Click Start Training.</div>
          ) : (
            logs.map((log, idx) => {
              // Syntax highlight logs slightly
              let color = "text-gray-300";
              if (log.includes("CRITICAL") || log.includes("Error") || log.includes("🛑")) color = "text-red-400";
              else if (log.includes("Warning") || log.includes("Skipping")) color = "text-yellow-400";
              else if (log.includes("Saved")) color = "text-emerald-400";
              else if (log.includes("[CYCLE")) color = "text-blue-400 font-bold";
              
              return (
                <div key={idx} className={`${color}`}>
                  <span className="text-gray-600 mr-2">{new Date().toLocaleTimeString()}</span>
                  {log}
                </div>
              );
            })
          )}
          <div ref={logsEndRef} />
        </div>
      </div>
    </div>
  );
};

export default TrainingUI;
