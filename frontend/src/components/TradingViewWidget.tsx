import { useEffect, useRef, memo } from 'react';
import { formatTradingViewSymbol } from './tradingViewUtils';

interface TradingViewWidgetProps {
  symbol?: string;
  theme?: 'dark' | 'light';
  autosize?: boolean;
  height?: number;
  interval?: string;
}

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
    const currentContainer = containerRef.current;
    if (!currentContainer) return;

    // Clear any previous chart instances
    currentContainer.innerHTML = '';

    const widgetDiv = document.createElement('div');
    widgetDiv.id = 'tradingview_advanced_chart';
    widgetDiv.style.height = autosize ? '100%' : `${height}px`;
    widgetDiv.style.width = '100%';
    currentContainer.appendChild(widgetDiv);

    const script = document.createElement('script');
    script.src = 'https://s3.tradingview.com/tv.js';
    script.type = 'text/javascript';
    script.async = true;
    script.onload = () => {
      if (typeof (window as any).TradingView !== 'undefined') {
        new (window as any).TradingView.widget({
          autosize: autosize,
          height: height,
          symbol: tvSymbol,
          interval: interval,
          timezone: 'Asia/Kolkata',
          theme: theme,
          style: '1',
          locale: 'en',
          toolbar_bg: '#131722',
          enable_publishing: false,
          hide_side_toolbar: false,
          allow_symbol_change: true,
          save_image: false,
          container_id: 'tradingview_advanced_chart',
          studies: [
            'RSI@tv-basicstudies',
            'MASimple@tv-basicstudies',
            'MACD@tv-basicstudies'
          ],
        });
      }
    };

    currentContainer.appendChild(script);

    return () => {
      if (currentContainer) {
        currentContainer.innerHTML = '';
      }
    };
  }, [tvSymbol, theme, autosize, height, interval]);

  return (
    <div
      ref={containerRef}
      className="tradingview-widget-container rounded-lg overflow-hidden border border-gray-800"
      style={{ height: autosize ? '100%' : `${height}px`, width: '100%' }}
    />
  );
};

export default memo(TradingViewWidget);
