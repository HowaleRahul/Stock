// frontend/portfolio.js

export async function fetchPortfolioData() {
    try {
        const response = await fetch('/api/v1/dashboard/portfolio');
        if (!response.ok) throw new Error('Failed to fetch portfolio data');
        return await response.json();
    } catch (error) {
        console.error('Error fetching portfolio:', error);
        return { account: {}, open_trades: [] };
    }
}

export function renderPortfolio(data) {
    const container = document.getElementById('portfolio-content');
    if (!container) return;
    
    const account = data.account || {};
    const trades = data.open_trades || [];
    
    let html = `
        <div class="portfolio-summary">
            <h3>Account Summary</h3>
            <p><strong>Capital:</strong> $${(account.capital || 0).toLocaleString()}</p>
            <p><strong>Peak Capital:</strong> $${(account.peak_capital || 0).toLocaleString()}</p>
            <p><strong>Status:</strong> ${account.status || 'UNKNOWN'}</p>
        </div>
        <div class="portfolio-trades">
            <h3>Open Paper Trades</h3>
            ${trades.length === 0 ? '<p>No open trades.</p>' : `
            <table class="trades-table">
                <thead>
                    <tr>
                        <th>Ticker</th>
                        <th>Direction</th>
                        <th>Entry Price</th>
                        <th>Quantity</th>
                        <th>Invested</th>
                        <th>Take Profit</th>
                        <th>Stop Loss</th>
                        <th>P&L</th>
                    </tr>
                </thead>
                <tbody>
                    ${trades.map(t => {
                        return `
                        <tr>
                            <td>${t.ticker}</td>
                            <td class="${t.direction === 'bullish' ? 'text-green' : 'text-red'}">${t.direction.toUpperCase()}</td>
                            <td>$${t.entry_price}</td>
                            <td>${t.quantity}</td>
                            <td>$${t.invested}</td>
                            <td>$${t.take_profit}</td>
                            <td>$${t.stop_loss}</td>
                            <td>-</td>
                        </tr>
                        `;
                    }).join('')}
                </tbody>
            </table>
            `}
        </div>
    `;
    
    container.innerHTML = html;
}
