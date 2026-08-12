"""
Streamlit Dashboard for Trading Bot — Phase 9
Provides interactive UI for config editing, portfolio metrics, and trade logs.
Run via: streamlit run dashboard.py
"""

import streamlit as st
import pandas as pd
import json
import os
import plotly.express as px

from ml.performance_dashboard import PerformanceDashboard
from ml.trade_logger import TradeLogger

CONFIG_PATH = "config.json"

st.set_page_config(page_title="AI Trading Dashboard", layout="wide", page_icon="📈")

# -----------------------------------------------------------------------------
# Data Loading Functions
# -----------------------------------------------------------------------------

@st.cache_data(ttl=5)
def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    return {}

def save_config(config_data):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config_data, f, indent=4)
    st.toast("Configuration Saved Successfully!", icon="✅")

@st.cache_data(ttl=10)
def load_performance_data():
    perf_board = PerformanceDashboard()
    summary = perf_board.portfolio_summary()
    setup_perf = perf_board.per_setup_performance()
    regime_perf = perf_board.per_regime_performance()
    rolling = perf_board.rolling_win_rate()
    
    entries = TradeLogger.get_all_entries()
    exits = TradeLogger.get_all_exits()
    
    return summary, setup_perf, regime_perf, rolling, entries, exits

# -----------------------------------------------------------------------------
# Main Application
# -----------------------------------------------------------------------------

st.title("📈 AI Algorithmic Trading Control Center")
st.markdown("Monitor performance, toggle ML setups, and manage risk limits in real-time.")

# Load Data
config = load_config()
summary, setup_perf, regime_perf, rolling, entries, exits = load_performance_data()

# -----------------------------------------------------------------------------
# SIDEBAR: Configuration & Control
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Configuration")
    
    # Environment Toggle (Hard separation logic flag)
    env_mode = st.radio("Execution Environment", ["PAPER", "LIVE"], 
                        index=0 if config.get("environment", "PAPER") == "PAPER" else 1,
                        help="LIVE mode will route trades to the Broker API instead of local JSON.")
    
    st.divider()
    
    st.subheader("Account & Risk")
    capital = st.number_input("Starting Capital (Budget)", min_value=10000.0, value=config.get("capital", 100000.0), step=10000.0)
    risk_pct = st.number_input("Max Risk Per Trade (%)", min_value=0.1, max_value=5.0, 
                               value=config.get("risk_per_trade_pct", 0.02) * 100, step=0.1) / 100.0
    
    min_rr = st.number_input("Min Risk:Reward Ratio", min_value=1.0, max_value=5.0, 
                             value=config.get("min_risk_reward_ratio", 1.5), step=0.1)
    
    st.divider()
    
    st.subheader("Watchlist")
    watchlist_str = st.text_area("Symbols (comma separated)", value=", ".join(config.get("watchlist", ["^NSEI", "^NSEBANK"])))
    watchlist = [s.strip() for s in watchlist_str.split(",") if s.strip()]
    
    st.divider()
    
    st.subheader("Active Setups")
    st.caption("Toggle which ML setups are allowed to fire.")
    
    # We dynamically load toggles from config or default them
    # For phase 9, we assume standard setups exist
    available_setups = ["BreakoutSetup", "FibonacciSetup", "RsiDivergenceSetup", "MeanReversionSetup"]
    active_setups = config.get("active_setups", available_setups)
    
    new_active_setups = []
    for s in available_setups:
        if st.checkbox(s, value=(s in active_setups)):
            new_active_setups.append(s)
            
    st.divider()
    
    if st.button("Save Configuration", use_container_width=True):
        config["environment"] = env_mode
        config["capital"] = capital
        config["risk_per_trade_pct"] = risk_pct
        config["min_risk_reward_ratio"] = min_rr
        config["watchlist"] = watchlist
        config["active_setups"] = new_active_setups
        save_config(config)

# -----------------------------------------------------------------------------
# MAIN DASHBOARD TABS
# -----------------------------------------------------------------------------

tab1, tab2, tab3 = st.tabs(["📊 Performance Metrics", "📔 Trade Journal", "🚨 Live API (SEBI)"])

with tab1:
    st.subheader("Portfolio Summary (Paper)")
    
    if summary.get("total_trades", 0) == 0:
        st.info("No closed trades yet. The system is waiting for trade outcomes.")
    else:
        # Top-level metrics
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total P&L", f"₹{summary.get('total_cash_pnl', 0):,.2f}")
        col2.metric("Win Rate", f"{summary.get('win_rate', 0)*100:.1f}%")
        col3.metric("Sharpe Ratio", f"{summary.get('sharpe_ratio', 0):.2f}")
        col4.metric("Profit Factor", f"{summary.get('profit_factor', 0):.2f}")
        
        st.divider()
        
        # Equity Curve Chart
        if exits:
            df_exits = pd.DataFrame(exits)
            df_exits['cumulative_pnl'] = df_exits['cash_pnl'].cumsum()
            df_exits['trade_number'] = range(1, len(df_exits) + 1)
            
            fig = px.line(df_exits, x='trade_number', y='cumulative_pnl', title="Equity Curve (Cash P&L)", markers=True)
            st.plotly_chart(fig, use_container_width=True)
            
        col_s1, col_s2 = st.columns(2)
        
        with col_s1:
            st.subheader("Setup Performance")
            if setup_perf:
                df_setups = pd.DataFrame.from_dict(setup_perf, orient='index').reset_index()
                df_setups.rename(columns={'index': 'Setup'}, inplace=True)
                st.dataframe(df_setups, use_container_width=True)
            else:
                st.write("Not enough data.")
                
        with col_s2:
            st.subheader("Regime Performance")
            if regime_perf:
                df_regimes = pd.DataFrame.from_dict(regime_perf, orient='index').reset_index()
                df_regimes.rename(columns={'index': 'Regime'}, inplace=True)
                st.dataframe(df_regimes, use_container_width=True)
            else:
                st.write("Not enough data.")

with tab2:
    st.subheader("Active & Closed Trades")
    
    # Merge entries and exits to show open vs closed
    if entries:
        df_entries = pd.DataFrame(entries)
        
        # Filter for OPEN trades
        open_trades = df_entries[df_entries['status'] == 'OPEN']
        if not open_trades.empty:
            st.markdown("#### Open Trades")
            st.dataframe(open_trades[['ticker', 'direction', 'entry_price', 'quantity', 'invested', 'opened_at']], use_container_width=True)
        else:
            st.info("No open trades currently.")
            
        st.divider()
        
        # Show closed trades
        if exits:
            st.markdown("#### Closed Trades History")
            df_exits_disp = pd.DataFrame(exits)
            st.dataframe(df_exits_disp[['ticker', 'direction', 'exit_price', 'exit_reason', 'pnl_pct', 'cash_pnl', 'closed_at']].sort_values(by="closed_at", ascending=False), use_container_width=True)
            
    else:
        st.info("No trades recorded yet.")

with tab3:
    st.subheader("Live Broker Configuration")
    st.warning("SEBI 2026 Compliant Framework Active. Ensure static IP whitelisting before generating OAuth tokens.")
    
    with st.expander("Zerodha Kite Connect Setup", expanded=True):
        st.text_input("API Key (OAuth)", type="password", help="Client ID from Zerodha Developer portal.")
        st.text_input("API Secret", type="password")
        st.text_input("TOTP Secret (2FA)", type="password", help="Required for automated daily login.")
        st.text_input("Algo-ID", help="Exchange issued ID if executing >10 orders/sec.")
        
        st.button("Validate Credentials & Whitelist IP", type="primary", disabled=True)
        st.caption("Live broker connections are administratively locked until Paper Trading track record exceeds 90 days.")
