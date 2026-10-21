import { useEffect, useRef, memo } from 'react';
import { formatTradingViewSymbol } from './TradingViewWidget';

interface TradingViewTASummaryProps {
  symbol?: string;
  theme?: 'dark' | 'light';
  interval?: string;
  height?: number;
}

const TradingViewTASummary = ({
  symbol = 'NSE:NIFTY',
  theme = 'dark',
  interval = '1h',
  height = 380,
}: TradingViewTASummaryProps) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const tvSymbol = formatTradingViewSymbol(symbol);

  // Map internal interval to TradingView interval format (1m, 5m, 15m, 1h, 4h, 1D, 1W, 1M)
  const mapInterval = (intv: string) => {
    switch (intv) {
      case '1m': return '1m';
      case '5m': return '5m';
      case '15m': return '15m';
      case '30m': return '30m';
      case '1h': return '1h';
      case '4h': return '4h';
      case '1d': return '1D';
      case '1wk': return '1W';
      default: return '1h';
    }
  };

  useEffect(() => {
    if (!containerRef.current) return;

    containerRef.current.innerHTML = '';

    const widgetContainer = document.createElement('div');
    widgetContainer.className = 'tradingview-widget-container__widget';
    widgetContainer.style.height = '100%';
    widgetContainer.style.width = '100%';
    containerRef.current.appendChild(widgetContainer);

    const script = document.createElement('script');
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-technical-analysis.js';
    script.type = 'text/javascript';
    script.async = true;
    script.innerHTML = JSON.stringify({
      interval: mapInterval(interval),
      width: '100%',
      isTransparent: true,
      height: height,
      symbol: tvSymbol,
      showIntervalTabs: true,
      displayMode: 'multiple',
      locale: 'en',
      colorTheme: theme,
    });

    containerRef.current.appendChild(script);

    return () => {
      if (containerRef.current) {
        containerRef.current.innerHTML = '';
      }
    };
  }, [tvSymbol, theme, interval, height]);

  return (
    <div
      ref={containerRef}
      className="tradingview-widget-container rounded-lg overflow-hidden border border-gray-800"
      style={{ height: `${height}px`, width: '100%' }}
    />
  );
};

export default memo(TradingViewTASummary);
