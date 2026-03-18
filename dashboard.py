"""
dashboard.py — ClaudeAPEX v12 Live Dashboard
Runs on Railway, reads paper_trades.csv written by paper_trader.py
"""
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="ClaudeAPEX | GLD Dashboard",
    page_icon="📈",
    layout="wide",
)

# ── dark theme ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
body, .stApp { background-color: #0d1117; color: #e6edf3; }
.metric-card {
    background: #161b22; border: 1px solid #30363d;
    border-radius: 8px; padding: 18px 20px; text-align: center;
}
.metric-label { font-size: 12px; color: #8b949e; text-transform: uppercase; letter-spacing: 1px; }
.metric-value { font-size: 28px; font-weight: 700; margin-top: 4px; }
.green { color: #3fb950; }
.red   { color: #f85149; }
.grey  { color: #8b949e; }
hr { border-color: #21262d; }
</style>
""", unsafe_allow_html=True)

# ── data path ───────────────────────────────────────────────────────────────
DATA_DIR  = Path(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "D:/trdng"))
TRADE_LOG = DATA_DIR / "paper_trades.csv"
STATE_FILE = DATA_DIR / "paper_state.json"

st.title("📈 ClaudeAPEX v12 — GLD Live Paper Trader")
st.caption(f"Strategy: Gap Momentum + VWAP + VEI filter | Commission: 0.01% (IB) | Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# ── load data ───────────────────────────────────────────────────────────────
if not TRADE_LOG.exists():
    st.info("No trades yet. Paper trader will log here once first signal fires (Mon–Fri 9:30–4:00 PM ET).")
    st.stop()

df = pd.read_csv(TRADE_LOG)
df["pnl"] = pd.to_numeric(df["pnl"], errors="coerce")
df["balance"] = pd.to_numeric(df["balance"], errors="coerce")
df["price"] = pd.to_numeric(df["price"], errors="coerce")

if df.empty:
    st.warning("Log file exists but no rows yet.")
    st.stop()

# Closed trades only for stats
closed = df[df["action"] == "CLOSE"].copy()
entries = df[df["action"].isin(["BUY", "SELL"])].copy()

# ── load state for current balance ──────────────────────────────────────────
import json
state = {}
if STATE_FILE.exists():
    with open(STATE_FILE) as f:
        state = json.load(f)

initial_capital = state.get("capital", 500.0)
current_balance = state.get("balance", df["balance"].iloc[-1])
total_pnl       = current_balance - initial_capital
roi_pct         = total_pnl / initial_capital * 100
n_trades        = state.get("total_trades", len(closed))
wins            = state.get("wins", len(closed[closed["pnl"] > 0]))
losses          = state.get("losses", len(closed[closed["pnl"] <= 0]))
win_rate        = wins / n_trades * 100 if n_trades else 0
open_position   = state.get("position")

# ── KPI row ─────────────────────────────────────────────────────────────────
c1, c2, c3, c4, c5, c6 = st.columns(6)

pnl_color  = "green" if total_pnl >= 0 else "red"
roi_color  = "green" if roi_pct   >= 0 else "red"
wr_color   = "green" if win_rate  >= 50 else "red"

def card(col, label, value, color="grey"):
    col.markdown(f"""
    <div class="metric-card">
      <div class="metric-label">{label}</div>
      <div class="metric-value {color}">{value}</div>
    </div>""", unsafe_allow_html=True)

card(c1, "Balance",    f"${current_balance:,.2f}", pnl_color)
card(c2, "Net P&L",    f"${total_pnl:+,.2f}",      pnl_color)
card(c3, "ROI",        f"{roi_pct:+.2f}%",          roi_color)
card(c4, "Trades",     str(n_trades),               "grey")
card(c5, "Win Rate",   f"{win_rate:.1f}%",          wr_color)
card(c6, "W / L",      f"{wins} / {losses}",        "grey")

st.markdown("<br>", unsafe_allow_html=True)

# open position banner
if open_position:
    pos = open_position
    st.info(f"🟢 **Open Position**: {pos['dir']}  {pos['shares']} shares @ ${pos['entry']:.2f}  |  Stop: ${pos['trail']:.2f}  |  Entered: {pos.get('entry_time','?')}")

# ── equity curve ────────────────────────────────────────────────────────────
st.subheader("Equity Curve")

if not closed.empty:
    eq = closed[["date", "time", "balance", "pnl"]].copy()
    eq["dt"] = pd.to_datetime(eq["date"] + " " + eq["time"], errors="coerce")
    eq = eq.sort_values("dt")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=eq["dt"], y=eq["balance"],
        mode="lines+markers",
        line=dict(color="#3fb950", width=2),
        marker=dict(
            color=["#3fb950" if p > 0 else "#f85149" for p in eq["pnl"]],
            size=8,
        ),
        hovertemplate="<b>%{x}</b><br>Balance: $%{y:,.2f}<extra></extra>",
        name="Balance",
    ))
    fig.add_hline(y=initial_capital, line_dash="dot", line_color="#8b949e",
                  annotation_text=f"Start ${initial_capital:,.0f}")
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0d1117",
        plot_bgcolor="#0d1117",
        height=320,
        margin=dict(l=0, r=0, t=20, b=0),
        xaxis=dict(gridcolor="#21262d"),
        yaxis=dict(gridcolor="#21262d", tickprefix="$"),
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No closed trades yet — equity curve will appear after first close.")

# ── trade table ─────────────────────────────────────────────────────────────
st.subheader("All Trades")

if not closed.empty:
    # Build clean display table by merging entries + closes
    display_rows = []
    entry_map = {}

    for _, row in df.iterrows():
        key = row["date"]
        if row["action"] in ("BUY", "SELL"):
            entry_map[key] = row
        elif row["action"] == "CLOSE":
            entry_row = entry_map.get(key, {})
            entry_price = entry_row.get("price", row.get("price", ""))
            entry_time  = entry_row.get("time", "")
            pnl_val = row["pnl"]
            display_rows.append({
                "Date":        row["date"],
                "Entry Time":  entry_time,
                "Exit Time":   row["time"],
                "Direction":   entry_row.get("dir", row.get("dir", "")),
                "Shares":      int(entry_row.get("shares", row.get("shares", 0))),
                "Entry $":     f"${float(entry_price):.2f}" if entry_price != "" else "—",
                "Exit $":      f"${row['price']:.2f}",
                "Stop $":      f"${float(entry_row.get('stop', 0)):.2f}" if entry_row else "—",
                "Net P&L":     f"${pnl_val:+,.2f}" if pd.notna(pnl_val) else "—",
                "Balance":     f"${row['balance']:,.2f}",
                "Exit Reason": row.get("reason", ""),
                "Result":      "WIN ✅" if (pd.notna(pnl_val) and pnl_val > 0) else "LOSS ❌",
            })

    tbl = pd.DataFrame(display_rows[::-1])  # latest first

    def style_result(val):
        if "WIN" in str(val):   return "color: #3fb950; font-weight: bold"
        if "LOSS" in str(val):  return "color: #f85149; font-weight: bold"
        return ""

    def style_pnl(val):
        try:
            v = float(str(val).replace("$","").replace(",",""))
            return "color: #3fb950" if v > 0 else "color: #f85149"
        except Exception:
            return ""

    styled = tbl.style.applymap(style_result, subset=["Result"]) \
                       .applymap(style_pnl, subset=["Net P&L"])

    st.dataframe(styled, use_container_width=True, height=450)

    # ── daily P&L bar chart ────────────────────────────────────────────────
    st.subheader("Daily P&L")
    daily = closed.groupby("date")["pnl"].sum().reset_index()
    daily.columns = ["Date", "P&L"]
    colors = ["#3fb950" if v > 0 else "#f85149" for v in daily["P&L"]]
    fig2 = go.Figure(go.Bar(
        x=daily["Date"], y=daily["P&L"],
        marker_color=colors,
        hovertemplate="<b>%{x}</b><br>P&L: $%{y:+,.2f}<extra></extra>",
    ))
    fig2.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0d1117",
        plot_bgcolor="#0d1117",
        height=260,
        margin=dict(l=0, r=0, t=20, b=0),
        xaxis=dict(gridcolor="#21262d"),
        yaxis=dict(gridcolor="#21262d", tickprefix="$"),
    )
    st.plotly_chart(fig2, use_container_width=True)

else:
    st.info("No closed trades to display yet.")

# ── sidebar ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Strategy Info")
    st.markdown("""
    **ClaudeAPEX v12**
    - Asset: GLD (Gold ETF)
    - Timeframe: 5m bars
    - Signal: Gap Momentum
    - Filter: VEI (volatility regime)
    - Confirmation: VWAP + EMA
    - Commission: 0.01% (IB)
    - Leverage: 5×
    - Capital: $500
    """)
    st.markdown("---")
    st.markdown(f"**Market Hours**: Mon–Fri 9:30–4:00 PM ET")
    st.markdown(f"**Last Refresh**: {datetime.now().strftime('%H:%M:%S')}")
    if st.button("🔄 Refresh"):
        st.rerun()
