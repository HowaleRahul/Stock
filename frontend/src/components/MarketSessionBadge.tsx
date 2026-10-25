import React, { useState, useEffect } from 'react';
import { Radio, CalendarClock, Clock } from 'lucide-react';
import { getMarketSessionState, type MarketSessionState } from '../utils/foUtils';

interface MarketSessionBadgeProps {
  compact?: boolean;
  showExpiry?: boolean;
}

export const MarketSessionBadge: React.FC<MarketSessionBadgeProps> = ({
  compact = false,
  showExpiry = true,
}) => {
  const [session, setSession] = useState<MarketSessionState>(() => getMarketSessionState());

  useEffect(() => {
    // Update every 5 seconds for smooth countdown without high CPU
    const interval = setInterval(() => {
      setSession(getMarketSessionState());
    }, 5000);

    return () => clearInterval(interval);
  }, []);

  const { status, badgeTitle, subText, nextExpiry, expiryName, expiryCountdown, istTimeString } = session;

  const getStatusStyles = () => {
    switch (status) {
      case 'LIVE':
        return {
          pill: 'bg-emerald-950/80 text-emerald-400 border-emerald-800 shadow-sm shadow-emerald-950/50',
          dot: 'bg-emerald-400 animate-pulse',
          iconColor: 'text-emerald-400',
        };
      case 'PRE_OPEN':
        return {
          pill: 'bg-amber-950/80 text-amber-400 border-amber-800 shadow-sm shadow-amber-950/50',
          dot: 'bg-amber-400 animate-pulse',
          iconColor: 'text-amber-400',
        };
      case 'WEEKEND':
      case 'CLOSED':
      default:
        return {
          pill: 'bg-gray-900/90 text-gray-300 border-gray-700',
          dot: 'bg-gray-500',
          iconColor: 'text-gray-400',
        };
    }
  };

  const styles = getStatusStyles();

  if (compact) {
    return (
      <div className="flex items-center gap-1.5 font-mono text-[11px]" title={`IST: ${istTimeString} | Next Expiry: ${nextExpiry}`}>
        <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-semibold ${styles.pill}`}>
          <span className={`w-2 h-2 rounded-full ${styles.dot}`} />
          <span>{badgeTitle}</span>
        </span>
        {showExpiry && (
          <span className="hidden sm:inline-flex items-center gap-1 px-2 py-0.5 rounded bg-gray-900 border border-gray-800 text-gray-400 text-[10px]">
            <CalendarClock className="w-3 h-3 text-purple-400" />
            <span>{expiryName}: {expiryCountdown}</span>
          </span>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2 font-mono text-xs" role="region" aria-label="Indian Market Session Status">
      {/* Real-time Status Badge */}
      <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border transition-all ${styles.pill}`}>
        <Radio className={`w-3.5 h-3.5 ${styles.iconColor} ${status === 'LIVE' ? 'animate-pulse' : ''}`} />
        <div className="flex flex-col sm:flex-row sm:items-center sm:gap-2 leading-tight">
          <span className="font-bold tracking-wide">{badgeTitle}</span>
          <span className="text-[10px] opacity-75 hidden sm:inline">•</span>
          <span className="text-[10px] opacity-90">{subText}</span>
        </div>
      </div>

      {/* Next Weekly Expiry Countdown */}
      {showExpiry && (
        <div
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-gray-900/90 border border-gray-800 text-gray-300 shadow-sm"
          title={`Next Indian Index Expiry: ${nextExpiry}`}
        >
          <CalendarClock className="w-3.5 h-3.5 text-purple-400 shrink-0" />
          <div className="flex items-center gap-1 text-[11px]">
            <span className="text-gray-400 uppercase text-[10px]">Expiry:</span>
            <span className="font-bold text-purple-300">{expiryName}</span>
            <span className="text-gray-400">({expiryCountdown})</span>
          </div>
        </div>
      )}

      {/* Live IST Clock */}
      <div className="hidden lg:flex items-center gap-1 px-2 py-1.5 rounded-lg bg-gray-900/60 border border-gray-800 text-gray-400 text-[10px]">
        <Clock className="w-3 h-3 text-blue-400 shrink-0" />
        <span>IST {istTimeString}</span>
      </div>
    </div>
  );
};

export default MarketSessionBadge;
