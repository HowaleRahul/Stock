import { useEffect, useRef, useId, memo } from 'react';
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
  const rawId = useId();
  const containerId = `tv_widget_${rawId.replace(/[^a-zA-Z0-9_-]/g, '')}`;
  const tvSymbol = formatTradingViewSymbol(symbol);

  useEffect(() => {
    let isCancelled = false;
    const currentContainer = containerRef.current;
    if (!currentContainer) return;

    currentContainer.innerHTML = '';
    const widgetDiv = document.createElement('div');
    widgetDiv.id = containerId;
    widgetDiv.style.height = autosize ? '100%' : `${height}px`;
    widgetDiv.style.width = '100%';
    currentContainer.appendChild(widgetDiv);

    const initWidget = () => {
      if (isCancelled || !document.getElementById(containerId)) return;
      if (typeof (window as any).TradingView !== 'undefined') {
        new (window as any).TradingView.widget({
          autosize,
          height,
          symbol: tvSymbol,
          interval,
          timezone: 'Asia/Kolkata',
          theme,
          style: '1',
          locale: 'en',
          toolbar_bg: '#131722',
          enable_publishing: false,
          hide_side_toolbar: false,
          allow_symbol_change: true,
          save_image: false,
          container_id: containerId,
          studies: ['RSI@tv-basicstudies', 'MASimple@tv-basicstudies', 'MACD@tv-basicstudies'],
        });
      }
    };

    if (typeof (window as any).TradingView !== 'undefined') {
      initWidget();
    } else {
      let script = document.getElementById('tradingview-tvjs') as HTMLScriptElement;
      if (!script) {
        script = document.createElement('script');
        script.id = 'tradingview-tvjs';
        script.src = 'https://s3.tradingview.com/tv.js';
        script.type = 'text/javascript';
        script.async = true;
        document.head.appendChild(script);
      }
      script.addEventListener('load', initWidget);
      return () => {
        isCancelled = true;
        script.removeEventListener('load', initWidget);
        if (currentContainer) currentContainer.innerHTML = '';
      };
    }

    return () => {
      isCancelled = true;
      if (currentContainer) currentContainer.innerHTML = '';
    };
  }, [containerId, tvSymbol, theme, autosize, height, interval]);

  return (
    <div
      ref={containerRef}
      className="tradingview-widget-container rounded-lg overflow-hidden border border-gray-800"
      style={{ height: autosize ? '100%' : `${height}px`, width: '100%' }}
    />
  );
};

export default memo(TradingViewWidget);
