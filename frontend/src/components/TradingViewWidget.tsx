import { useEffect, useRef, memo } from 'react';

interface TradingViewWidgetProps {
  symbol?: string;
  theme?: 'dark' | 'light';
  autosize?: boolean;
  height?: number;
  interval?: string;
}

// Convert ticker to TradingView format (e.g. ^NSEI -> NSE:NIFTY, RELIANCE.NS -> NSE:RELIANCE)
export const formatTradingViewSymbol = (ticker: string): string => {
  const clean = (ticker || '').trim().toUpperCase();
  if (clean === '^NSEI' || clean === 'NIFTY' || clean === 'NIFTY 50') {
    return 'NSE:NIFTY';
  }
  if (clean === '^NSEBANK' || clean === 'BANKNIFTY' || clean === 'NIFTY BANK') {
    return 'NSE:BANKNIFTY';
  }
  if (clean === '^BSESN' || clean === 'SENSEX') {
    return 'BSE:SENSEX';
  }
  if (clean.endsWith('.NS')) {
    return `NSE:${clean.replace('.NS', '')}`;
  }
  if (clean.endsWith('.BO')) {
    return `BSE:${clean.replace('.BO', '')}`;
  }
  if (clean.includes(':')) {
    return clean;
  }
  // Default to NSE for Indian equities
  return `NSE:${clean}`;
};

const TradingViewWidget = ({
  symbol = 'NSE:NIFTY',
  theme = 'dark',
  autosize = true,
  height = 550,
  interval = 'D',
}: TradingViewWidgetProps) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const tvSymbol = formatTradingViewSymbol(symbol);

  useEffect(() => {
    if (!containerRef.current) return;

    // Clear previous widget
    containerRef.current.innerHTML = '';

    const widgetContainer = document.createElement('div');
    widgetContainer.className = 'tradingview-widget-container__widget';
    widgetContainer.style.height = '100%';
    widgetContainer.style.width = '100%';
    containerRef.current.appendChild(widgetContainer);

    const script = document.createElement('script');
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
    script.type = 'text/javascript';
    script.async = true;
    script.innerHTML = JSON.stringify({
      autosize: autosize,
      symbol: tvSymbol,
      interval: interval,
      timezone: 'Asia/Kolkata',
      theme: theme,
      style: '1',
      locale: 'en',
      enable_publishing: false,
      allow_symbol_change: true,
      calendar: false,
      support_host: 'https://www.tradingview.com',
      hide_top_toolbar: false,
      hide_side_toolbar: false,
      save_image: true,
      details: true,
      hotlist: true,
      studies: [
        'RSI@tv-basicstudies',
        'MASimple@tv-basicstudies',
        'MACD@tv-basicstudies'
      ],
      container_id: 'tradingview_advanced_chart',
    });

    containerRef.current.appendChild(script);

    return () => {
      if (containerRef.current) {
        containerRef.current.innerHTML = '';
      }
    };
  }, [tvSymbol, theme, autosize, interval]);

  return (
    <div
      ref={containerRef}
      className="tradingview-widget-container rounded-lg overflow-hidden border border-gray-800 shadow-xl"
      style={{ height: `${height}px`, width: '100%' }}
    />
  );
};

export default memo(TradingViewWidget);
