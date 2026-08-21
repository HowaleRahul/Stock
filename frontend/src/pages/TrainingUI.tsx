import { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { Play, Square, Terminal, Activity, BrainCircuit, Clock3, Database, RefreshCw } from 'lucide-react';

const TrainingUI = () => {
  const [isTraining, setIsTraining] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [actionPending, setActionPending] = useState(false);
  const logsEndRef = useRef<HTMLDivElement>(null);

  const fetchStatus = async () => {
    try {
      const res = await axios.get('/api/v1/training/status');
      setIsTraining(res.data.is_training);
      setLogs(res.data.logs);
      setError(null);
    } catch {
      setError("Training service is offline. Start the API server and retry.");
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
      setActionPending(true);
      setError(null);
      await axios.post('/api/v1/training/start');
      await fetchStatus();
    } catch {
      setError("Training could not be started.");
    } finally {
      setActionPending(false);
    }
  };

  const handleStop = async () => {
    try {
      setActionPending(true);
      setError(null);
      await axios.post('/api/v1/training/stop');
      await fetchStatus();
    } catch {
      setError("Training could not be stopped.");
    } finally {
      setActionPending(false);
    }
  };

  const latestLog = logs[logs.length - 1] || 'No training events recorded yet.';

  return (
    <div className="training-page">
      {error && <div className="state-panel compact" role="alert"><strong>{error}</strong><button className="retry-button" onClick={fetchStatus}>Retry connection</button></div>}
      <div className="page-heading training-heading">
        <div><span className="eyebrow">Model lab / 05</span><h1>AI Training Engine</h1><p>Incremental learning from simulated market outcomes and new observations.</p></div>
        <div className={`training-state ${isTraining ? 'running' : ''}`}><span className="state-dot" /> {isTraining ? 'RUNNING' : 'IDLE'}</div>
      </div>
      <section className="training-command-bar">
        <div className="training-command-copy"><div className="training-icon"><BrainCircuit /></div><div><span className="eyebrow">Continuous trainer</span><h2>{isTraining ? 'Training cycle in progress' : 'Ready for a new cycle'}</h2><p>{isTraining ? 'The model is downloading data, generating features, and updating its checkpoint.' : 'Start a run when the market data service and model workspace are ready.'}</p></div></div>
        <div className="training-actions">
          <button 
            onClick={handleStart}
            disabled={isTraining || actionPending}
            className="training-start"
          >
            <Play /> {actionPending ? 'Working...' : 'Start training'}
          </button>
          <button 
            onClick={handleStop}
            disabled={!isTraining || actionPending}
            className="training-stop"
          >
            <Square /> Stop run
          </button>
        </div>
      </section>

      <div className="training-metrics">
        <div className="training-metric"><Activity /><div><span>Engine status</span><strong>{isTraining ? 'RUNNING' : 'STOPPED'}</strong></div></div>
        <div className="training-metric"><Database /><div><span>Log buffer</span><strong>{logs.length} <small>/ 200 events</small></strong></div></div>
        <div className="training-metric"><Clock3 /><div><span>Refresh cadence</span><strong>2 sec</strong></div></div>
      </div>

      <section className="training-console">
        <div className="console-heading"><div><span className="eyebrow">Run telemetry</span><h2><Terminal /> Training console</h2></div><button className="console-refresh" onClick={fetchStatus} aria-label="Refresh training status" title="Refresh status"><RefreshCw /></button></div>
        <div className="latest-event"><span>Latest event</span><strong>{latestLog}</strong></div>
        <div className="console-output" aria-live="polite">
          {logs.length === 0 ? (
            <div className="console-empty">No logs available. Start a training cycle to see model activity.</div>
          ) : (
            logs.map((log, idx) => {
              // Syntax highlight logs slightly
              let color = "log-default";
              if (log.includes("CRITICAL") || log.includes("Error") || log.includes("🛑")) color = "log-error";
              else if (log.includes("Warning") || log.includes("Skipping")) color = "log-warning";
              else if (log.includes("Saved")) color = "log-success";
              else if (log.includes("[CYCLE")) color = "log-cycle";
              
              return (
                <div key={`${idx}-${log}`} className={color}>
                  <span className="log-index">{String(idx + 1).padStart(3, '0')}</span>
                  {log}
                </div>
              );
            })
          )}
          <div ref={logsEndRef} />
        </div>
      </section>
    </div>
  );
};

export default TrainingUI;
