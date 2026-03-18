import streamlit as st
import pandas as pd
import plotly.express as px
from pathlib import Path
import os
from datetime import datetime

st.set_page_config(
    page_title="APEX Live Performance",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom Styling
st.markdown("""
<style>
    .reportview-container {
        background: #0e1117;
    }
    .metric-box {
        background-color: #1e212a;
        padding: 20px;
        border-radius: 10px;
        border: 1px solid #30363d;
        text-align: center;
    }
</style>
""", unsafe_allow_safe_html=True)

# Path setup (matches paper_trader.py)
DATA_DIR = Path(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "D:/trdng"))
TRADE_LOG = DATA_DIR / "paper_trades.csv"

st.title("📊 ClaudeAPEX v12 Live Dashboard")
st.markdown("---")

if not TRADE_LOG.exists():
    st.info("💡 **No trades logged yet.** The dashboard will automatically update once the paper trader records its first signal.")
    st.stop()

# Load Data
try:
    df = pd.read_csv(TRADE_LOG)
except Exception as e:
    st.error(f"Error loading logs: {e}")
    st.stop()

if df.empty:
    st.warning("Logs exist but are empty. Waiting for trades...")
    st.stop()

# --- 1. Metrics / KPIs ---
st.subheader("📈 Performance Metrics")

# Compute KPIs
total_trades = len(df[df['action'] == 'CLOSE'])
wins = len(df[(df['action'] == 'CLOSE') & (df['pnl'].astype(float) > 0)])
losses = total_trades - wins
win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

# Get current balance from last row
current_balance = df['balance'].iloc[-1]
initial_capital = df['balance'].iloc[0] if not df.empty else 500.0  # Fallback
net_pnl = current_balance - initial_capital

# Layout KPIs
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.metric(label="Current Balance", value=f"${current_balance:,.2f}", delta=f"${net_pnl:+,.2f}")
with c2:
    st.metric(label="Total Trades", value=str(total_trades))
with c3:
    st.metric(label="Win Rate", value=f"{win_rate:.1f}%")
with c4:
    st.metric(label="Wins / Losses", value=f"{wins} / {losses}")

st.markdown("---")

# --- 2. Charts ---
st.subheader("📊 Equity Curve")

# Filter for CLOSE rows to track Equity over time
equity_df = df[df['action'] == 'CLOSE'].copy()
if not equity_df.empty:
    # Plotly Line Chart
    fig = px.line(equity_df, x='time', y='balance', 
                  title="Cumulative Balance / Equity curve",
                  labels={'time': 'Time', 'balance': 'Balance ($)'},
                  template="plotly_dark")
    fig.update_traces(line_color='#00d488', line_width=3)
    fig.update_layout(hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No closed trades to build equity curve yet.")

st.markdown("---")

# --- 3. Trade Log ---
st.subheader("📋 Recent Activity")

# Reverse for latest first
display_df = df.iloc[::-1].copy()

# Style DataFrame
def color_pnl(val):
    if pd.isna(val) or val == "":
        return ""
    try:
        color = 'green' if float(val) > 0 else 'red'
        return f'color: {color}'
    except ValueError:
        return ""

# Format for display
display_df['pnl'] = pd.to_numeric(display_df['pnl'], errors='coerce')
st.dataframe(
    display_df[['date', 'time', 'action', 'dir', 'shares', 'price', 'pnl', 'balance', 'reason']],
    use_container_width=True,
    height=400
)

# Auto-refresh
st.sidebar.markdown(f"**Last Update:** {datetime.now().strftime('%H:%M:%S')}")
if st.sidebar.button("Refresh Dashboard"):
    st.rerun()
st.sidebar.caption("Script runs 24/7 on Railway Volume storage.")
st.sidebar.caption("Mon-Fri 9:30 AM - 4:00 PM ET")
st.sidebar.markdown("[Go to Railway.app Dashboard](https://railway.app)")
st.sidebar.caption("Dashboard uses Streamlit")
st.sidebar.caption("Build by Antigravity AI")
