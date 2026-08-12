import { useState, memo } from 'react';
import { AdvancedRealTimeChart } from "react-ts-tradingview-widgets";

const TradingViewWidget = ({ watchlists }) => {
  const mapSymbol = (sym) => {
    // Revert to exactly NIFTY and BANKNIFTY (no NSE prefix) to match previous phases.
    if (sym === '^NSEI' || sym === 'NIFTY' || sym === 'NSE:NIFTY' || sym === 'NSE:NIFTY1!') return 'NIFTY';
    if (sym === '^NSEBANK' || sym === 'BANKNIFTY' || sym === 'NSE:BANKNIFTY' || sym === 'NSE:BANKNIFTY1!') return 'BANKNIFTY';
    if (sym && sym.endsWith('.NS')) return `NSE:${sym.replace('.NS', '')}`;
    if (sym && sym.endsWith('.BO')) return `BSE:${sym.replace('.BO', '')}`;
    return sym;
  };

  const defaultSymbol = watchlists && watchlists.length > 0 ? mapSymbol(watchlists[0]) : 'BSE:SENSEX';
  const [symbol, setSymbol] = useState(defaultSymbol);

  return (
    <div className="flex flex-col h-full w-full gap-4">
      <div className="flex items-center gap-4">
        <label className="text-sm font-medium text-text-muted">Symbol:</label>
        <select 
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          className="bg-surface border border-white/10 rounded px-3 py-1.5 text-sm outline-none focus:border-primary transition-colors"
        >
          {watchlists?.map(s => {
            const mapped = mapSymbol(s);
            return <option key={mapped} value={mapped}>{mapped}</option>
          })}
        </select>
      </div>
      
      <div className="flex-1 rounded-xl overflow-hidden glass border border-white/10 shadow-2xl relative h-[600px]">
        <AdvancedRealTimeChart 
            symbol={symbol}
            theme="dark"
            width="100%"
            height="100%"
            interval="5"
            timezone="Asia/Kolkata"
            style="1"
            locale="en"
            enable_publishing={false}
            hide_legend={false}
            hide_top_toolbar={false}
            allow_symbol_change={false}
        />
      </div>
    </div>
  );
};

export default memo(TradingViewWidget);
