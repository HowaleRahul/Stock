/* ===========================================================
   AI Trading Dashboard — app.js
   Connects to FastAPI backend, renders TradingView charts,
   and displays setup signal cards.
   =========================================================== */

(() => {
    'use strict';

    // ── DOM refs ──────────────────────────────────────────────
    const tickerSelect     = document.getElementById('ticker-select');
    const timeframeSelect  = document.getElementById('timeframe-select');
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
                background: { color: '#1a1e2e' },
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
                timeVisible: false,
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
    function renderCharts(indicators, tf = '1d') {
        destroyCharts();

        const candles = sanitizeSeriesData(indicators.candles || [], true, tf);

        // ── Price Chart ──────────────────────────────────────
        priceChart = createDarkChart(priceChartEl, 400);

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

        // EMA 20
        if (indicators.ema_20 && indicators.candles) {
            const ema20Series = priceChart.addSeries(LightweightCharts.LineSeries, {
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
            const ema50Series = priceChart.addSeries(LightweightCharts.LineSeries, {
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

        if (indicators.rsi && indicators.candles) {
            const rsiSeries = rsiChart.addSeries(LightweightCharts.LineSeries, {
                color: '#ffd740',
                lineWidth: 1.5,
                priceLineVisible: false,
                lastValueVisible: false,
            });
            rsiSeries.setData(sanitizeSeriesData(
                indicators.rsi.map((v, i) => ({ time: indicators.candles[i]?.time, value: v })),
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
            const histSeries = macdChart.addSeries(LightweightCharts.HistogramSeries, {
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
            const macdLine = macdChart.addSeries(LightweightCharts.LineSeries, {
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
            const signalLine = macdChart.addSeries(LightweightCharts.LineSeries, {
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

        macdChart.timeScale().fitContent();

        // Sync
        syncTimeScales([priceChart, rsiChart, macdChart]);
    }

    // ── Render Signal Cards ──────────────────────────────────
    function renderSignals(setups) {
        const list = setups.setups || setups;

        if (!Array.isArray(list) || list.length === 0) {
            signalsContainer.innerHTML = '<div class="empty-state"><p>No setup signals available</p></div>';
            return;
        }

        signalsContainer.innerHTML = list.map(s => {
            const rawSignal  = (s.signal || 'neutral').toLowerCase();
            const signal     = rawSignal.replace(/[^a-z0-9_-]/g, '') || 'neutral';
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
    }

    function escapeHTML(str) {
        const div = document.createElement('div');
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }

    function showError(msg) {
        signalsContainer.innerHTML = `<div class="error-state"><p>${escapeHTML(msg)}</p></div>`;
    }

    // ── Load Ticker Data ─────────────────────────────────────
    async function loadTickerData(ticker) {
        showLoading(`Loading analysis & charts for ${ticker}...`);
        const tf = timeframeSelect ? timeframeSelect.value : '1d';
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
                renderCharts(indicatorsResult, tf);
            } else {
                console.error("Chart indicator load error:", indicatorsResult);
            }

            if (!(setupsResult instanceof Error)) {
                renderSignals(setupsResult);
            } else {
                showError(`Error loading setup evaluation: ${setupsResult.message}`);
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

    if (timeframeSelect) {
        timeframeSelect.addEventListener('change', () => {
            const ticker = tickerSelect.value;
            if (ticker) loadTickerData(ticker);
        });
    }

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

    // ── Init ─────────────────────────────────────────────────
    populateSymbols();
})();
