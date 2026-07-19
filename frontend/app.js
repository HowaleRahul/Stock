/* ===========================================================
   AI Trading Dashboard — app.js
   Connects to FastAPI backend, renders TradingView charts,
   and displays setup signal cards.
   =========================================================== */

(() => {
    'use strict';

    // ── DOM refs ──────────────────────────────────────────────
    const tickerSelect     = document.getElementById('ticker-select');
    let currentTf          = '1d';
    const tickerSearch     = document.getElementById('ticker-search');
    const searchBtn        = document.getElementById('search-btn');
    const marketModeSelect = document.getElementById('market-mode-select');
    const searchSuggestions = document.getElementById('search-suggestions');
    const lastUpdatedEl    = document.getElementById('last-updated');
    const priceChartEl     = document.getElementById('price-chart');
    const rsiChartEl       = document.getElementById('rsi-chart');
    const macdChartEl      = document.getElementById('macd-chart');
    const loadingOverlay   = document.getElementById('loading-overlay');
    const signalsContainer = document.getElementById('signals-container');

    // ── Base URL ──────────────────────────────────────────────
    const BASE = window.location.origin;

    // ── Chart references (for cleanup / resize) ──────────────
    let priceChart = null;
    let rsiChart   = null;
    let macdChart  = null;

    // ── Helpers ──────────────────────────────────────────────
    function showLoading(msg = 'Analyzing...') {
        const p = loadingOverlay.querySelector('p');
        if (p) p.textContent = msg;
        loadingOverlay.classList.add('active');
    }

    function hideLoading() {
        loadingOverlay.classList.remove('active');
    }

    /** Extract date string or Unix timestamp safely based on timeframe. */
    function toChartTime(iso, tf) {
        if (!iso) return null;
        if (tf && (tf === '15m' || tf === '1h' || tf.endsWith('m') || tf.endsWith('h'))) {
            const dt = new Date(iso);
            if (isNaN(dt.getTime())) return null;
            return Math.floor(dt.getTime() / 1000);
        }
        if (typeof iso === 'string') return iso.slice(0, 10);
        if (iso instanceof Date) return iso.toISOString().slice(0, 10);
        return String(iso).slice(0, 10);
    }

    /** Keep only finite numeric entries, deduplicate by time string/number, and sort ascending. */
    function sanitizeSeriesData(arr, isCandle = false, tf = '1d') {
        if (!Array.isArray(arr)) return [];
        const seen = new Map();
        for (let i = 0; i < arr.length; i++) {
            const item = arr[i];
            if (!item || !item.time) continue;
            const t = toChartTime(item.time, tf);
            if (t == null) continue;
            if (isCandle) {
                if (
                    item.open != null && Number.isFinite(item.open) &&
                    item.high != null && Number.isFinite(item.high) &&
                    item.low != null && Number.isFinite(item.low) &&
                    item.close != null && Number.isFinite(item.close)
                ) {
                    seen.set(t, { time: t, open: item.open, high: item.high, low: item.low, close: item.close });
                }
            } else {
                if (item.value != null && Number.isFinite(item.value)) {
                    seen.set(t, { time: t, value: item.value, color: item.color });
                }
            }
        }
        const sorted = Array.from(seen.values()).sort((a, b) => (a.time > b.time ? 1 : a.time < b.time ? -1 : 0));
        return sorted;
    }

    // ── API Fetchers ─────────────────────────────────────────
    async function fetchSymbols() {
        const res = await fetch(`${BASE}/api/v1/symbols`);
        if (!res.ok) throw new Error('Failed to load symbols');
        return res.json();
    }

    async function fetchIndicators(ticker, tf = '1d') {
        const res = await fetch(`${BASE}/api/v1/indicators/${ticker}?timeframe=${tf}&limit=500`);
        if (!res.ok) throw new Error('Failed to load indicators');
        return res.json();
    }

    async function fetchSetups(ticker, tf = '1d') {
        const res = await fetch(`${BASE}/api/v1/setups/${ticker}?timeframe=${tf}&period=200`);
        if (!res.ok) throw new Error('Failed to load setups');
        return res.json();
    }

    // ── Populate Ticker Dropdown ─────────────────────────────
    async function populateSymbols() {
        try {
            const data = await fetchSymbols();
            const symbols = data.symbols || data;
            const symList = Array.isArray(symbols) ? symbols : [];
            tickerSelect.innerHTML = '<option value="" disabled selected>Select a symbol…</option>';
            let firstTicker = null;
            symList.forEach(sym => {
                if (!sym) return;
                const val = typeof sym === 'string' ? sym : sym.ticker || sym.symbol;
                if (!val) return;
                if (!firstTicker) firstTicker = val;
                const opt = document.createElement('option');
                opt.value = val;
                opt.textContent = val;
                tickerSelect.appendChild(opt);
            });
            // Auto-load first ticker if available so dashboard is immediately populated
            if (firstTicker && !tickerSelect.value) {
                tickerSelect.value = firstTicker;
                loadTickerData(firstTicker);
            }
        } catch (err) {
            console.error(err);
            tickerSelect.innerHTML = '<option value="" disabled selected>Error loading symbols</option>';
        }
    }

    // ── Chart Cleanup ────────────────────────────────────────
    function destroyCharts() {
        [priceChart, rsiChart, macdChart].forEach(c => {
            if (c) {
                try { c.remove(); } catch (_) { /* already removed */ }
            }
        });
        priceChart = null;
        rsiChart   = null;
        macdChart  = null;
    }

    // ── Chart Factory ────────────────────────────────────────
    function createDarkChart(container, height) {
        const safeWidth = Math.max(container.clientWidth || 600, 100);
        const safeHeight = Math.max(height || container.clientHeight || 400, 100);
        return LightweightCharts.createChart(container, {
            width: safeWidth,
            height: safeHeight,
            layout: {
                background: { color: '#131722' },
                textColor: '#d1d4dc',
            },
            grid: {
                vertLines: { color: '#2a2e3e' },
                horzLines: { color: '#2a2e3e' },
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Normal,
            },
            rightPriceScale: {
                borderColor: '#2a2e3e',
            },
            timeScale: {
                borderColor: '#2a2e3e',
                timeVisible: true,
            },
            handleScroll: {
                mouseWheel: true,
                pressedMouseMove: true,
                horzTouchDrag: true,
                vertTouchDrag: true,
            },
            handleScale: {
                mouseWheel: false,
                pinch: true,
                axisPressedMouseMove: { time: true, price: true },
                axisDoubleClickReset: true,
            },
        });
    }

    // ── Time-Scale Sync ──────────────────────────────────────
    function syncTimeScales(charts) {
        let isSyncing = false;
        charts.forEach((src, i) => {
            src.timeScale().subscribeVisibleLogicalRangeChange(range => {
                if (isSyncing || !range) return;
                isSyncing = true;
                charts.forEach((dst, j) => {
                    if (i !== j) dst.timeScale().setVisibleLogicalRange(range);
                });
                isSyncing = false;
            });
        });
    }

    // ── Render Charts ────────────────────────────────────────
    function renderCharts(indicators, tf = '1d', ticker = '') {
        destroyCharts();

        const candles = sanitizeSeriesData(indicators.candles || [], true, tf);

        // ── Price Chart ──────────────────────────────────────
        priceChart = createDarkChart(priceChartEl, 400);

        if (ticker) {
            priceChart.applyOptions({
                watermark: {
                    visible: true,
                    fontSize: 48,
                    horzAlign: 'center',
                    vertAlign: 'center',
                    color: 'rgba(255, 255, 255, 0.05)',
                    text: ticker,
                },
            });
        }

        const candleSeries = priceChart.addSeries(LightweightCharts.CandlestickSeries, {
            upColor:          '#00c853',
            downColor:        '#ff1744',
            borderUpColor:    '#00c853',
            borderDownColor:  '#ff1744',
            wickUpColor:      '#00c853',
            wickDownColor:    '#ff1744',
        });
        if (candles.length > 0) {
            candleSeries.setData(candles);
        }

        let volumeSeries = null;
        if (indicators.candles && indicators.candles.length > 0) {
            volumeSeries = priceChart.addSeries(LightweightCharts.HistogramSeries, {
                color: '#26a69a',
                priceFormat: { type: 'volume' },
                priceScaleId: '', // Set to empty to use a hidden scale
            });
            priceChart.priceScale('').applyOptions({
                scaleMargins: { top: 0.8, bottom: 0 },
            });
            
            const volData = indicators.candles.map((c, i) => {
                const color = c.close >= c.open ? 'rgba(0, 200, 83, 0.4)' : 'rgba(255, 23, 68, 0.4)';
                return { time: c.time, value: c.volume, color: color };
            });
            volumeSeries.setData(sanitizeSeriesData(volData, false, tf));
        }

        let ema20Series = null, ema50Series = null;
        let rsiSeries = null;
        let histSeries = null, macdLine = null, signalLine = null;

        // EMA 20
        if (indicators.ema_20 && indicators.candles) {
            ema20Series = priceChart.addSeries(LightweightCharts.LineSeries, {
                color: '#ffd740',
                lineWidth: 1,
                priceLineVisible: false,
                lastValueVisible: false,
            });
            ema20Series.setData(sanitizeSeriesData(
                indicators.ema_20.map((v, i) => ({ time: indicators.candles[i]?.time, value: v })),
                false,
                tf
            ));
        }

        // EMA 50
        if (indicators.ema_50 && indicators.candles) {
            ema50Series = priceChart.addSeries(LightweightCharts.LineSeries, {
                color: '#448aff',
                lineWidth: 1,
                priceLineVisible: false,
                lastValueVisible: false,
            });
            ema50Series.setData(sanitizeSeriesData(
                indicators.ema_50.map((v, i) => ({ time: indicators.candles[i]?.time, value: v })),
                false,
                tf
            ));
        }

        // Bollinger Bands
        if (indicators.bb_upper && indicators.candles) {
            const bbUpper = priceChart.addSeries(LightweightCharts.LineSeries, {
                color: 'rgba(156, 39, 176, 0.5)',
                lineWidth: 1,
                priceLineVisible: false,
                lastValueVisible: false,
            });
            bbUpper.setData(sanitizeSeriesData(
                indicators.bb_upper.map((v, i) => ({ time: indicators.candles[i]?.time, value: v })),
                false,
                tf
            ));
        }

        if (indicators.bb_lower && indicators.candles) {
            const bbLower = priceChart.addSeries(LightweightCharts.LineSeries, {
                color: 'rgba(156, 39, 176, 0.5)',
                lineWidth: 1,
                priceLineVisible: false,
                lastValueVisible: false,
            });
            bbLower.setData(sanitizeSeriesData(
                indicators.bb_lower.map((v, i) => ({ time: indicators.candles[i]?.time, value: v })),
                false,
                tf
            ));
        }

        if (indicators.bb_middle && indicators.candles) {
            const bbMiddle = priceChart.addSeries(LightweightCharts.LineSeries, {
                color: 'rgba(156, 39, 176, 0.3)',
                lineWidth: 1,
                lineStyle: LightweightCharts.LineStyle.Dashed,
                priceLineVisible: false,
                lastValueVisible: false,
            });
            bbMiddle.setData(sanitizeSeriesData(
                indicators.bb_middle.map((v, i) => ({ time: indicators.candles[i]?.time, value: v })),
                false,
                tf
            ));
        }

        // Support / Resistance levels
        if (Array.isArray(indicators.support_levels)) {
            indicators.support_levels.forEach(level => {
                if (level != null && Number.isFinite(level)) {
                    candleSeries.createPriceLine({
                        price:     level,
                        color:     '#00c853',
                        lineWidth: 1,
                        lineStyle: LightweightCharts.LineStyle.Dashed,
                        axisLabelVisible: true,
                        title:     'S',
                    });
                }
            });
        }

        if (Array.isArray(indicators.resistance_levels)) {
            indicators.resistance_levels.forEach(level => {
                if (level != null && Number.isFinite(level)) {
                    candleSeries.createPriceLine({
                        price:     level,
                        color:     '#ff1744',
                        lineWidth: 1,
                        lineStyle: LightweightCharts.LineStyle.Dashed,
                        axisLabelVisible: true,
                        title:     'R',
                    });
                }
            });
        }

        priceChart.timeScale().fitContent();

        // ── RSI Chart ────────────────────────────────────────
        rsiChart = createDarkChart(rsiChartEl, 150);

        if (indicators.rsi_14 && indicators.candles) {
            rsiSeries = rsiChart.addSeries(LightweightCharts.LineSeries, {
                color: '#ffd740',
                lineWidth: 1.5,
                priceLineVisible: false,
                lastValueVisible: false,
            });
            rsiSeries.setData(sanitizeSeriesData(
                indicators.rsi_14.map((v, i) => ({ time: indicators.candles[i]?.time, value: v })),
                false,
                tf
            ));

            // Reference lines at 30 and 70
            rsiSeries.createPriceLine({
                price: 70,
                color: 'rgba(255, 23, 68, 0.4)',
                lineWidth: 1,
                lineStyle: LightweightCharts.LineStyle.Dashed,
                axisLabelVisible: false,
            });
            rsiSeries.createPriceLine({
                price: 30,
                color: 'rgba(0, 200, 83, 0.4)',
                lineWidth: 1,
                lineStyle: LightweightCharts.LineStyle.Dashed,
                axisLabelVisible: false,
            });
        }

        rsiChart.timeScale().fitContent();

        // ── MACD Chart ───────────────────────────────────────
        macdChart = createDarkChart(macdChartEl, 150);

        if (indicators.macd_histogram && indicators.candles) {
            histSeries = macdChart.addSeries(LightweightCharts.HistogramSeries, {
                priceLineVisible: false,
                lastValueVisible: false,
            });
            histSeries.setData(sanitizeSeriesData(
                indicators.macd_histogram.map((v, i) => ({
                    time:  indicators.candles[i]?.time,
                    value: v,
                    color: v != null && v >= 0 ? '#00c853' : '#ff1744',
                })),
                false,
                tf
            ));
        }

        if (indicators.macd_line && indicators.candles) {
            macdLine = macdChart.addSeries(LightweightCharts.LineSeries, {
                color: '#448aff',
                lineWidth: 1.5,
                priceLineVisible: false,
                lastValueVisible: false,
            });
            macdLine.setData(sanitizeSeriesData(
                indicators.macd_line.map((v, i) => ({ time: indicators.candles[i]?.time, value: v })),
                false,
                tf
            ));
        }

        if (indicators.macd_signal && indicators.candles) {
            signalLine = macdChart.addSeries(LightweightCharts.LineSeries, {
                color: '#ff6d00',
                lineWidth: 1.5,
                priceLineVisible: false,
                lastValueVisible: false,
            });
            signalLine.setData(sanitizeSeriesData(
                indicators.macd_signal.map((v, i) => ({ time: indicators.candles[i]?.time, value: v })),
                false,
                tf
            ));
        }

        macdChart.applyOptions({
            timeScale: { timeVisible: true }
        });
        macdChart.timeScale().fitContent();

        // Sync
        syncTimeScales([priceChart, rsiChart, macdChart]);
        
        // ── True Crosshair Vertical Sync ────────────────────────
        function syncCrosshair(param, sourceChart) {
            if (!param || param.time === undefined || param.point === undefined || param.point.x < 0 || param.point.y < 0) {
                [priceChart, rsiChart, macdChart].forEach(c => {
                    if (c && c !== sourceChart) c.clearCrosshairPosition();
                });
                return;
            }
            [priceChart, rsiChart, macdChart].forEach(c => {
                if (c && c !== sourceChart) {
                    const s = (c === priceChart) ? candleSeries : (c === rsiChart) ? rsiSeries : histSeries;
                    if (s) {
                        // Trick in v4 to sync just the vertical line: pass NaN for price
                        c.setCrosshairPosition(NaN, param.time, s);
                    }
                }
            });
        }
        
        // ── Crosshair Legends ────────────────────────────────────
        const priceLegend = document.getElementById('price-legend');
        const rsiLegend = document.getElementById('rsi-legend');
        const macdLegend = document.getElementById('macd-legend');
        
        function updateLegends(param, sourceChart) {
            syncCrosshair(param, sourceChart);
            if (!param || !param.time) return;
            
            if (candleSeries && priceLegend) {
                const candle = param.seriesData.get(candleSeries);
                if (candle) {
                    const colorClass = candle.close >= candle.open ? 'val-up' : 'val-down';
                    let html = `<span class="legend-item">O <span class="${colorClass}">${candle.open.toFixed(2)}</span></span>`;
                    html += `<span class="legend-item">H <span class="${colorClass}">${candle.high.toFixed(2)}</span></span>`;
                    html += `<span class="legend-item">L <span class="${colorClass}">${candle.low.toFixed(2)}</span></span>`;
                    html += `<span class="legend-item">C <span class="${colorClass}">${candle.close.toFixed(2)}</span></span>`;
                    
                    if (volumeSeries) {
                        const vol = param.seriesData.get(volumeSeries);
                        if (vol) {
                            let volStr = vol.value.toFixed(0);
                            if (vol.value >= 1e6) volStr = (vol.value / 1e6).toFixed(2) + 'M';
                            else if (vol.value >= 1e3) volStr = (vol.value / 1e3).toFixed(2) + 'K';
                            const isHidden = !volumeSeries.options().visible ? 'hidden-series' : '';
                            html += `<span class="legend-item ${isHidden}">Vol <span class="${colorClass}">${volStr}</span><span class="toggle-vis" data-series="vol">👁</span></span>`;
                        }
                    }
                    
                    if (ema20Series) {
                        const ema20 = param.seriesData.get(ema20Series);
                        const isHidden = !ema20Series.options().visible ? 'hidden-series' : '';
                        if (ema20) html += ` <span class="legend-item val-ema20 ${isHidden}">EMA(20): ${ema20.value.toFixed(2)}<span class="toggle-vis" data-series="ema20">👁</span></span>`;
                    }
                    if (ema50Series) {
                        const ema50 = param.seriesData.get(ema50Series);
                        const isHidden = !ema50Series.options().visible ? 'hidden-series' : '';
                        if (ema50) html += ` <span class="legend-item val-ema50 ${isHidden}">EMA(50): ${ema50.value.toFixed(2)}<span class="toggle-vis" data-series="ema50">👁</span></span>`;
                    }
                    priceLegend.innerHTML = html;
                }
            }
            
            if (rsiSeries && rsiLegend) {
                const rsi = param.seriesData.get(rsiSeries);
                const isHidden = !rsiSeries.options().visible ? 'hidden-series' : '';
                if (rsi) rsiLegend.innerHTML = `<span class="legend-item val-ema20 ${isHidden}">RSI(14): ${rsi.value.toFixed(2)}<span class="toggle-vis" data-series="rsi">👁</span></span>`;
            }
            
            if (macdLine && signalLine && histSeries && macdLegend) {
                const macd = param.seriesData.get(macdLine);
                const sig = param.seriesData.get(signalLine);
                const hist = param.seriesData.get(histSeries);
                if (macd && sig && hist) {
                    const hCol = hist.value >= 0 ? 'val-up' : 'val-down';
                    macdLegend.innerHTML = `<span class="legend-item val-macd">MACD: ${macd.value.toFixed(2)}</span> <span class="legend-item val-signal">Sig: ${sig.value.toFixed(2)}</span> <span class="legend-item ${hCol}">Hist: ${hist.value.toFixed(2)}</span>`;
                }
            }
        }
        
        // Initial empty state
        if (priceLegend) priceLegend.innerHTML = `<span class="legend-item">Hover over chart for values</span>`;
        if (rsiLegend) rsiLegend.innerHTML = `<span class="legend-item val-ema20">RSI(14)<span class="toggle-vis" data-series="rsi">👁</span></span>`;
        if (macdLegend) macdLegend.innerHTML = `<span class="legend-item val-macd">MACD(12, 26, 9)</span>`;

        priceChart.subscribeCrosshairMove(p => updateLegends(p, priceChart));
        rsiChart.subscribeCrosshairMove(p => updateLegends(p, rsiChart));
        macdChart.subscribeCrosshairMove(p => updateLegends(p, macdChart));
        
        // Setup legend visibility toggles
        document.querySelectorAll('.chart-legend').forEach(legend => {
            legend.addEventListener('click', (e) => {
                if (e.target.classList.contains('toggle-vis')) {
                    const seriesName = e.target.getAttribute('data-series');
                    let targetSeries = null;
                    if (seriesName === 'vol') targetSeries = volumeSeries;
                    if (seriesName === 'ema20') targetSeries = ema20Series;
                    if (seriesName === 'ema50') targetSeries = ema50Series;
                    if (seriesName === 'rsi') targetSeries = rsiSeries;
                    
                    if (targetSeries) {
                        const currentVis = targetSeries.options().visible !== false;
                        targetSeries.applyOptions({ visible: !currentVis });
                        e.target.parentElement.classList.toggle('hidden-series', currentVis);
                    }
                }
            });
        });
    }

    // ── Render Signal Cards ──────────────────────────────────
    let allSetups = [];
    let enabledSetups = new Set();

    function renderSignals(data) {
        const container = document.getElementById('signals-container');
        const regimeBadge = document.getElementById('regime-badge');
        const regimeText = document.getElementById('regime-text');
        const toggleAll = document.getElementById('toggle-all');
        const checkboxesContainer = document.getElementById('setup-checkboxes');
        
        container.innerHTML = '';
        
        if (!data.setups || data.setups.length === 0) {
            container.innerHTML = `<div class="empty-state"><p>No analysis available</p></div>`;
            if (regimeBadge) regimeBadge.classList.add('hidden');
            return;
        }
        
        // 1. Handle Regime Badge
        if (regimeBadge && data.regime && data.regime.regime !== 'unknown' && data.regime.regime !== 'error') {
            regimeBadge.classList.remove('hidden', 'trending', 'range-bound');
            regimeBadge.classList.add(data.regime.regime);
            regimeText.textContent = `Regime: ${data.regime.regime.toUpperCase()} (ADX: ${data.regime.adx}) - ${data.regime.direction}`;
        } else if (regimeBadge) {
            regimeBadge.classList.add('hidden');
        }
        
        // Store globally for filtering
        allSetups = data.setups;
        
        // 2. Build Toggles if not already built (only once per symbol load)
        if (checkboxesContainer.children.length === 0) {
            data.setups.forEach(setup => {
                enabledSetups.add(setup.name);
                const lbl = document.createElement('label');
                const cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.checked = true;
                cb.value = setup.name;
                cb.addEventListener('change', (e) => {
                    if (e.target.checked) enabledSetups.add(setup.name);
                    else enabledSetups.delete(setup.name);
                    
                    // Update "Toggle All" state
                    toggleAll.checked = enabledSetups.size === allSetups.length;
                    renderFilteredSignals();
                });
                lbl.appendChild(cb);
                lbl.appendChild(document.createTextNode(setup.name));
                checkboxesContainer.appendChild(lbl);
            });
        }
        
        renderFilteredSignals();
    }

    function renderFilteredSignals() {
        const container = document.getElementById('signals-container');
        const summary = document.getElementById('signals-summary');
        container.innerHTML = '';
        
        const visibleSetups = allSetups.filter(s => enabledSetups.has(s.name));
        
        if (visibleSetups.length === 0) {
            container.innerHTML = `<div class="empty-state"><p>No setups selected</p></div>`;
            if (summary) summary.classList.add('hidden');
            return;
        }
        
        let bullCount = 0, bearCount = 0, neutCount = 0;
        
        container.innerHTML = visibleSetups.map(s => {
            const rawSignal  = (s.signal || 'neutral').toLowerCase();
            const signal     = rawSignal.replace(/[^a-z0-9_-]/g, '') || 'neutral';
            
            if (signal === 'bullish') bullCount++;
            else if (signal === 'bearish') bearCount++;
            else neutCount++;
            
            const rawConf    = (typeof s.confidence === 'number' && Number.isFinite(s.confidence)) ? s.confidence : 0;
            const confidence = Math.max(0, Math.min(1, rawConf));
            const pct        = (confidence * 100).toFixed(0);
            const name       = s.name || s.setup || 'Setup';
            const reasoning  = s.reasoning || '';

            return `
            <div class="signal-card signal-card--${signal}">
                <div class="signal-card__header">
                    <span class="signal-card__name">${escapeHTML(name)}</span>
                    <span class="signal-badge signal-badge--${signal}">${escapeHTML(signal)}</span>
                </div>
                <div class="signal-card__confidence">
                    <div class="confidence-bar">
                        <div class="confidence-fill" style="width: ${pct}%"></div>
                    </div>
                    <span class="confidence-value">${pct}%</span>
                </div>
                <p class="signal-card__reasoning">${escapeHTML(reasoning)}</p>
            </div>`;
        }).join('');
        
        if (summary) {
            summary.innerHTML = `
                <span class="tally-bullish">${bullCount} Bullish</span>
                <span class="tally-neutral">${neutCount} Neutral</span>
                <span class="tally-bearish">${bearCount} Bearish</span>
            `;
            summary.classList.remove('hidden');
        }
    }

    function escapeHTML(str) {
        const div = document.createElement('div');
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }

    function showError(msg) {
        signalsContainer.innerHTML = `<div class="error-state"><p>${escapeHTML(msg)}</p></div>`;
    }

    // ── Load Ticker Data (With Circuit Breaker) ─────────────
    let circuitBrokenUntil = 0;

    async function loadTickerData(ticker) {
        if (Date.now() < circuitBrokenUntil) {
            showError("Server is unreachable. Circuit breaker active. Please try again later.");
            return;
        }

        showLoading(`Loading analysis & charts for ${ticker}...`);
        const tf = currentTf;
        
        // Reset toggles on new ticker
        const checkboxesContainer = document.getElementById('setup-checkboxes');
        const toggleAll = document.getElementById('toggle-all');
        if (checkboxesContainer) checkboxesContainer.innerHTML = '';
        if (toggleAll) toggleAll.checked = true;
        enabledSetups.clear();
        
        try {
            let indicatorsResult = null;
            let setupsResult = null;

            for (let attempt = 1; attempt <= 3; attempt++) {
                if (attempt > 1) {
                    showLoading(`Syncing historical data from Yahoo Finance (${attempt}/3)...`);
                    await new Promise(r => setTimeout(r, 1500));
                }

                if (!indicatorsResult || indicatorsResult instanceof Error) {
                    indicatorsResult = await fetchIndicators(ticker, tf).catch(e => e);
                }
                if (!setupsResult || setupsResult instanceof Error) {
                    setupsResult = await fetchSetups(ticker, tf).catch(e => e);
                }

                if (!(indicatorsResult instanceof Error) && !(setupsResult instanceof Error)) {
                    break;
                }
            }

            if (indicatorsResult instanceof Error && setupsResult instanceof Error) {
                throw new Error(indicatorsResult.message || setupsResult.message);
            }

            if (!(indicatorsResult instanceof Error)) {
                renderCharts(indicatorsResult, tf, ticker);
            } else {
                if (indicatorsResult.message && indicatorsResult.message.includes('Failed to fetch')) {
                    circuitBrokenUntil = Date.now() + 30000; // Break for 30s
                }
                showError("Error loading charts: " + indicatorsResult.message);
            }

            if (!(setupsResult instanceof Error)) {
                renderSignals(setupsResult);
            } else {
                if (setupsResult.message && setupsResult.message.includes('Failed to fetch')) {
                    circuitBrokenUntil = Date.now() + 30000; // Break for 30s
                }
                if (!(indicatorsResult instanceof Error)) {
                    showError("Charts loaded, but setups failed: " + setupsResult.message);
                }
            } 
            
            lastUpdatedEl.textContent = `Updated ${new Date().toLocaleTimeString()} (${tf})`;
        } catch (err) {
            console.error(err);
            showError(`Error loading data for ${ticker} (${tf}): ${err.message}`);
        } finally {
            hideLoading();
        }
    }

    // ── Window Resize ────────────────────────────────────────
    let resizeTimer;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
            if (priceChart) priceChart.applyOptions({ width: priceChartEl.clientWidth });
            if (rsiChart)   rsiChart.applyOptions({ width: rsiChartEl.clientWidth });
            if (macdChart)  macdChart.applyOptions({ width: macdChartEl.clientWidth });
        }, 100);
    });

    // ── Event Listeners ──────────────────────────────────────
    tickerSelect.addEventListener('change', () => {
        const ticker = tickerSelect.value;
        if (ticker) loadTickerData(ticker);
    });

    const tfButtons = document.querySelectorAll('.tf-btn');
    tfButtons.forEach(btn => {
        btn.addEventListener('click', (e) => {
            tfButtons.forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
            currentTf = e.target.getAttribute('data-tf');
            const ticker = tickerSelect.value;
            if (ticker) loadTickerData(ticker);
        });
    });

    // ── Pane Resizers ────────────────────────────────────────
    let isResizing = false;
    let currentResizer = null;
    let startY = 0;
    let startHeight = 0;
    let targetPane = null;

    document.querySelectorAll('.pane-resizer').forEach(resizer => {
        resizer.addEventListener('pointerdown', e => {
            isResizing = true;
            currentResizer = resizer;
            resizer.classList.add('dragging');
            startY = e.clientY;
            if (resizer.id === 'resizer-1') targetPane = document.getElementById('rsi-chart');
            if (resizer.id === 'resizer-2') targetPane = document.getElementById('macd-chart');
            if (targetPane) startHeight = targetPane.offsetHeight;
            
            document.body.style.userSelect = 'none';
            document.body.style.cursor = 'row-resize';
        });
    });

    window.addEventListener('pointermove', e => {
        if (!isResizing || !targetPane) return;
        const diff = e.clientY - startY;
        const newHeight = Math.max(50, Math.min(400, startHeight - diff));
        targetPane.style.height = `${newHeight}px`;
        targetPane.style.flex = `0 0 ${newHeight}px`;
        
        // Trigger resize on the actual chart object
        if (targetPane.id === 'rsi-chart' && rsiChart) rsiChart.resize(targetPane.clientWidth, newHeight);
        if (targetPane.id === 'macd-chart' && macdChart) macdChart.resize(targetPane.clientWidth, newHeight);
    });

    window.addEventListener('pointerup', () => {
        if (isResizing) {
            isResizing = false;
            if (currentResizer) currentResizer.classList.remove('dragging');
            document.body.style.userSelect = '';
            document.body.style.cursor = '';
        }
    });

    // ── Autocomplete Suggestions & Search ────────────────────
    let debounceTimer = null;

    async function fetchSuggestions(query) {
        if (!query || query.length < 1 || !searchSuggestions) {
            if (searchSuggestions) searchSuggestions.classList.remove('active');
            return;
        }
        const market = marketModeSelect ? marketModeSelect.value : 'all';
        try {
            const res = await fetch(`${BASE}/api/v1/search?q=${encodeURIComponent(query)}&market=${market}`);
            if (!res.ok) return;
            const data = await res.json();
            renderSuggestions(data.suggestions || []);
        } catch (e) {
            console.error('Error fetching suggestions:', e);
        }
    }

    function renderSuggestions(list) {
        if (!searchSuggestions) return;
        searchSuggestions.innerHTML = '';
        if (!list || list.length === 0) {
            searchSuggestions.classList.remove('active');
            return;
        }

        list.forEach(item => {
            const li = document.createElement('li');
            li.className = 'suggestion-item';
            li.innerHTML = `
                <div class="suggestion-item__left">
                    <span class="suggestion-item__sym">${escapeHTML(String(item.symbol || ''))}</span>
                    <span class="suggestion-item__name">${escapeHTML(String(item.name || ''))}</span>
                </div>
                <span class="suggestion-item__badge">${escapeHTML(String(item.exchange || ''))}</span>
            `;
            li.addEventListener('click', () => {
                tickerSearch.value = item.symbol;
                searchSuggestions.classList.remove('active');
                selectOrAddSymbolAndLoad(item.symbol);
            });
            searchSuggestions.appendChild(li);
        });
        searchSuggestions.classList.add('active');
    }

    function selectOrAddSymbolAndLoad(symbol) {
        const val = symbol.trim().toUpperCase();
        if (!val) return;

        let exists = false;
        for (let i = 0; i < tickerSelect.options.length; i++) {
            if (tickerSelect.options[i].value.toUpperCase() === val) {
                tickerSelect.value = tickerSelect.options[i].value;
                exists = true;
                break;
            }
        }

        if (!exists) {
            const opt = document.createElement('option');
            opt.value = val;
            opt.textContent = val;
            tickerSelect.appendChild(opt);
            tickerSelect.value = val;
        }

        loadTickerData(val);
    }

    function handleSearch() {
        if (!tickerSearch) return;
        let val = tickerSearch.value.trim().toUpperCase();
        if (!val) return;
        if (searchSuggestions) searchSuggestions.classList.remove('active');

        // If India region is selected and user types a plain symbol without suffix, auto-append .NS
        const market = marketModeSelect ? marketModeSelect.value : 'all';
        if (market === 'india' && !val.includes('.') && !val.startsWith('^') && val !== 'NIFTY' && val !== 'BANKNIFTY' && val !== 'SENSEX') {
            val = `${val}.NS`;
            tickerSearch.value = val;
        }

        selectOrAddSymbolAndLoad(val);
    }

    if (tickerSearch) {
        tickerSearch.addEventListener('input', (e) => {
            const val = e.target.value.trim();
            clearTimeout(debounceTimer);
            if (!val) {
                if (searchSuggestions) searchSuggestions.classList.remove('active');
                return;
            }
            debounceTimer = setTimeout(() => fetchSuggestions(val), 180);
        });

        tickerSearch.addEventListener('keydown', (e) => {
            const items = searchSuggestions ? searchSuggestions.querySelectorAll('.suggestion-item') : [];
            const activeItem = searchSuggestions ? searchSuggestions.querySelector('.suggestion-item.highlighted') : null;

            if (e.key === 'ArrowDown') {
                e.preventDefault();
                if (!items.length) return;
                let nextIndex = 0;
                if (activeItem) {
                    activeItem.classList.remove('highlighted');
                    const idx = Array.from(items).indexOf(activeItem);
                    nextIndex = (idx + 1) % items.length;
                }
                items[nextIndex].classList.add('highlighted');
                items[nextIndex].scrollIntoView({ block: 'nearest' });
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                if (!items.length) return;
                let nextIndex = items.length - 1;
                if (activeItem) {
                    activeItem.classList.remove('highlighted');
                    const idx = Array.from(items).indexOf(activeItem);
                    nextIndex = (idx - 1 + items.length) % items.length;
                }
                items[nextIndex].classList.add('highlighted');
                items[nextIndex].scrollIntoView({ block: 'nearest' });
            } else if (e.key === 'Enter') {
                e.preventDefault();
                if (activeItem) {
                    activeItem.click();
                } else {
                    handleSearch();
                }
            } else if (e.key === 'Escape') {
                if (searchSuggestions) searchSuggestions.classList.remove('active');
            }
        });
    }

    if (searchBtn) {
        searchBtn.addEventListener('click', handleSearch);
    }

    if (marketModeSelect) {
        marketModeSelect.addEventListener('change', () => {
            if (tickerSearch && tickerSearch.value.trim()) {
                fetchSuggestions(tickerSearch.value.trim());
            }
        });
    }

    // Hide suggestions when clicking outside
    document.addEventListener('click', (e) => {
        if (searchSuggestions && !e.target.closest('#search-container')) {
            searchSuggestions.classList.remove('active');
        }
    });

    // ── TradingView Zoom/Pan Toggle (Ctrl Key) ───────────────
    let ctrlPressed = false;
    
    function updateChartInteractions() {
        const options = {
            handleScroll: { 
                mouseWheel: !ctrlPressed,
                pressedMouseMove: true,
                horzTouchDrag: true,
                vertTouchDrag: true,
            },
            handleScale: { 
                mouseWheel: ctrlPressed,
                pinch: true,
                axisPressedMouseMove: { time: true, price: true },
                axisDoubleClickReset: true,
            },
        };
        if (priceChart) priceChart.applyOptions(options);
        if (rsiChart) rsiChart.applyOptions(options);
        if (macdChart) macdChart.applyOptions(options);
    }

    window.addEventListener('keydown', (e) => {
        if (e.key === 'Control' && !ctrlPressed) {
            ctrlPressed = true;
            updateChartInteractions();
        }
    });

    window.addEventListener('keyup', (e) => {
        if (e.key === 'Control' && ctrlPressed) {
            ctrlPressed = false;
            updateChartInteractions();
        }
    });
    
    // Fallback if window loses focus while Ctrl is held
    window.addEventListener('blur', () => {
        if (ctrlPressed) {
            ctrlPressed = false;
            updateChartInteractions();
        }
    });

    // ── Setup Toggles (Global Listener) ──────────────────────
    const globalToggleAll = document.getElementById('toggle-all');
    if (globalToggleAll) {
        globalToggleAll.addEventListener('change', (e) => {
            const isChecked = e.target.checked;
            const checkboxesContainer = document.getElementById('setup-checkboxes');
            if (checkboxesContainer) {
                checkboxesContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                    cb.checked = isChecked;
                    if (isChecked) enabledSetups.add(cb.value);
                    else enabledSetups.delete(cb.value);
                });
            }
            renderFilteredSignals();
        });
    }

    // ── Init ─────────────────────────────────────────────────
    populateSymbols();
})();
