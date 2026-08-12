const TradeJournal = ({ trades }) => {
  const openTrades = trades?.entries?.filter(t => t.status === 'OPEN') || [];
  const closedTrades = trades?.exits?.sort((a, b) => new Date(b.closed_at) - new Date(a.closed_at)) || [];

  return (
    <div className="flex flex-col gap-8 h-full">
      {/* Open Trades */}
      <div className="glass rounded-xl border border-white/10 overflow-hidden flex flex-col max-h-[40%]">
        <div className="p-4 border-b border-white/5 bg-surface/50">
          <h3 className="text-lg font-semibold flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse"></span>
            Active Open Trades
          </h3>
        </div>
        <div className="flex-1 overflow-auto">
          {openTrades.length === 0 ? (
            <div className="p-8 text-center text-text-muted">No open trades currently active.</div>
          ) : (
            <table className="w-full text-sm text-left whitespace-nowrap">
              <thead className="text-xs text-text-muted uppercase bg-surface/80 sticky top-0 backdrop-blur">
                <tr>
                  <th className="py-3 px-4">Ticker</th>
                  <th className="py-3 px-4">Direction</th>
                  <th className="py-3 px-4 text-right">Entry Price</th>
                  <th className="py-3 px-4 text-right">Target</th>
                  <th className="py-3 px-4 text-right">Stop Loss</th>
                  <th className="py-3 px-4 text-right">Invested</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {openTrades.map((t, i) => (
                  <tr key={i} className="hover:bg-white/5">
                    <td className="py-3 px-4 font-bold">{t.ticker}</td>
                    <td className="py-3 px-4">
                      <span className={`px-2 py-1 rounded text-xs font-bold ${t.direction === 'LONG' ? 'bg-success/20 text-success' : 'bg-danger/20 text-danger'}`}>
                        {t.direction}
                      </span>
                    </td>
                    <td className="py-3 px-4 text-right">₹{t.entry_price?.toFixed(2)}</td>
                    <td className="py-3 px-4 text-right text-success">₹{t.tp?.toFixed(2)}</td>
                    <td className="py-3 px-4 text-right text-danger">₹{t.sl?.toFixed(2)}</td>
                    <td className="py-3 px-4 text-right font-medium">₹{t.invested?.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Closed Trades */}
      <div className="glass rounded-xl border border-white/10 overflow-hidden flex flex-col flex-1">
        <div className="p-4 border-b border-white/5 bg-surface/50">
          <h3 className="text-lg font-semibold text-text-muted">Closed Trades History</h3>
        </div>
        <div className="flex-1 overflow-auto">
          {closedTrades.length === 0 ? (
            <div className="p-8 text-center text-text-muted">No closed trades yet.</div>
          ) : (
            <table className="w-full text-sm text-left whitespace-nowrap">
              <thead className="text-xs text-text-muted uppercase bg-surface/80 sticky top-0 backdrop-blur">
                <tr>
                  <th className="py-3 px-4">Time</th>
                  <th className="py-3 px-4">Ticker</th>
                  <th className="py-3 px-4">Reason</th>
                  <th className="py-3 px-4 text-right">Exit Price</th>
                  <th className="py-3 px-4 text-right">P&L (%)</th>
                  <th className="py-3 px-4 text-right">Cash P&L</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {closedTrades.map((t, i) => (
                  <tr key={i} className="hover:bg-white/5">
                    <td className="py-3 px-4 text-text-muted">{new Date(t.closed_at).toLocaleString()}</td>
                    <td className="py-3 px-4 font-bold">{t.ticker}</td>
                    <td className="py-3 px-4 text-text-muted">{t.exit_reason}</td>
                    <td className="py-3 px-4 text-right">₹{t.exit_price?.toFixed(2)}</td>
                    <td className={`py-3 px-4 text-right font-medium ${t.pnl_pct > 0 ? 'text-success' : 'text-danger'}`}>
                      {(t.pnl_pct * 100).toFixed(2)}%
                    </td>
                    <td className={`py-3 px-4 text-right font-bold ${t.cash_pnl > 0 ? 'text-success' : 'text-danger'}`}>
                      {t.cash_pnl > 0 ? '+' : ''}₹{t.cash_pnl?.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
};

export default TradeJournal;
