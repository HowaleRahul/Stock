import Plot from 'react-plotly.js';

const MetricsPanel = ({ metrics, exits }) => {
  if (!metrics || !metrics.summary) {
    return <div className="text-text-muted">Loading metrics...</div>;
  }

  const { summary, setup_perf } = metrics;
  
  // Prepare Equity Curve Data
  let equityData = [];
  if (exits && exits.length > 0) {
    let runningTotal = 0;
    equityData = exits.map((t, i) => {
      runningTotal += t.cash_pnl;
      return { x: i + 1, y: runningTotal };
    });
  }

  return (
    <div className="flex flex-col gap-8 h-full w-full">
      {/* Top Cards */}
      <div className="grid grid-cols-4 gap-6">
        <MetricCard title="Total Net P&L" value={`₹${summary.total_cash_pnl?.toLocaleString(undefined, {minimumFractionDigits: 2})}`} highlight={summary.total_cash_pnl >= 0 ? 'success' : 'danger'} />
        <MetricCard title="Win Rate" value={`${(summary.win_rate * 100).toFixed(1)}%`} highlight="primary" />
        <MetricCard title="Profit Factor" value={summary.profit_factor?.toFixed(2)} highlight="primary" />
        <MetricCard title="Max Drawdown" value={`${(summary.max_drawdown * 100).toFixed(2)}%`} highlight="danger" />
      </div>

      <div className="grid grid-cols-3 gap-6 flex-1 min-h-[400px]">
        {/* Chart */}
        <div className="col-span-2 glass rounded-xl p-6 border border-white/10 flex flex-col">
          <h3 className="text-lg font-semibold mb-4">Equity Curve (Cash P&L)</h3>
          <div className="flex-1 relative">
            {equityData.length > 0 ? (
              <Plot
                data={[
                  {
                    x: equityData.map(d => d.x),
                    y: equityData.map(d => d.y),
                    type: 'scatter',
                    mode: 'lines+markers',
                    marker: { color: '#3b82f6' },
                    line: { color: '#3b82f6', width: 3, shape: 'spline' },
                    fill: 'tozeroy',
                    fillcolor: 'rgba(59, 130, 246, 0.1)'
                  }
                ]}
                layout={{
                  autosize: true,
                  margin: { l: 40, r: 20, t: 20, b: 40 },
                  paper_bgcolor: 'transparent',
                  plot_bgcolor: 'transparent',
                  font: { color: '#94a3b8' },
                  xaxis: { gridcolor: 'rgba(255,255,255,0.05)', title: 'Trade Number' },
                  yaxis: { gridcolor: 'rgba(255,255,255,0.05)', title: 'Cumulative P&L (₹)' }
                }}
                useResizeHandler={true}
                style={{ width: '100%', height: '100%', position: 'absolute' }}
                config={{ displayModeBar: false }}
              />
            ) : (
              <div className="absolute inset-0 flex items-center justify-center text-text-muted">
                No closed trades yet to form an equity curve.
              </div>
            )}
          </div>
        </div>

        {/* Setup Performance Table */}
        <div className="col-span-1 glass rounded-xl p-6 border border-white/10 overflow-hidden flex flex-col">
          <h3 className="text-lg font-semibold mb-4">Setup Performance</h3>
          <div className="flex-1 overflow-auto pr-2">
            <table className="w-full text-sm text-left">
              <thead className="text-xs text-text-muted uppercase sticky top-0 bg-surface/80 backdrop-blur-md">
                <tr>
                  <th className="py-3 px-2">Setup</th>
                  <th className="py-3 px-2 text-right">Win Rate</th>
                  <th className="py-3 px-2 text-right">Avg R:R</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {Object.entries(setup_perf || {}).map(([name, stats]) => (
                  <tr key={name} className="hover:bg-white/5 transition-colors">
                    <td className="py-3 px-2 font-medium">{name.replace('Setup', '')}</td>
                    <td className={`py-3 px-2 text-right ${stats.win_rate > 0.5 ? 'text-success' : 'text-danger'}`}>
                      {(stats.win_rate * 100).toFixed(0)}%
                    </td>
                    <td className="py-3 px-2 text-right">{stats.avg_rr?.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
};

function MetricCard({ title, value, highlight }) {
  const highlightColors = {
    primary: 'text-primary',
    success: 'text-success',
    danger: 'text-danger'
  };
  
  return (
    <div className="glass rounded-xl p-6 border border-white/10 relative overflow-hidden group hover:border-white/20 transition-all">
      <div className={`absolute -right-4 -top-4 w-16 h-16 rounded-full blur-[40px] opacity-20 ${
        highlight === 'primary' ? 'bg-primary' : highlight === 'success' ? 'bg-success' : 'bg-danger'
      }`} />
      <h4 className="text-sm font-medium text-text-muted mb-2">{title}</h4>
      <p className={`text-3xl font-bold tracking-tight ${highlightColors[highlight] || 'text-text'}`}>
        {value}
      </p>
    </div>
  );
}

export default MetricsPanel;
