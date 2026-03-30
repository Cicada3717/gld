"""
lfv_dashboard.py - LFV Strategy Live Dashboard (GLD + BTC-USD)
"""
import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="LFV Strategy",
    page_icon="chart_with_upwards_trend",
    layout="wide",
)

st.markdown(
    """
<style>
body, .stApp { background-color: #0d1117; color: #e6edf3; }
.metric-card {
    background: #161b22; border: 1px solid #30363d;
    border-radius: 8px; padding: 18px 20px; text-align: center;
}
.metric-label { font-size: 12px; color: #8b949e; text-transform: uppercase; letter-spacing: 1px; }
.metric-value { font-size: 28px; font-weight: 700; margin-top: 4px; }
.green { color: #3fb950; } .red { color: #f85149; } .grey { color: #8b949e; }
hr { border-color: #21262d; }
div[data-testid="stHorizontalBlock"] > div { gap: 0.5rem; }
</style>
""",
    unsafe_allow_html=True,
)

DATA_DIR = Path(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", Path(__file__).parent))

ASSETS = {
    "GLD": {
        "label": "GLD - Gold ETF",
        "state": DATA_DIR / "zone_state.json",
        "trades": DATA_DIR / "zone_trades.csv",
        "timeframe": "1H bars - Mon-Fri 09:30-16:00 ET",
        "signal": "Supply & Demand Zones (4H/1H refinement)",
        "params": "min_rr=3.0  trailing 0.5R",
    },
    "BTC-USD": {
        "label": "BTC-USD - Bitcoin",
        "state": DATA_DIR / "lfv_state_BTCUSD.json",
        "trades": DATA_DIR / "lfv_trades_BTCUSD.csv",
        "timeframe": "5-min bars - 24/7",
        "signal": "Liquidity sweep + AVWAP + Volume Profile",
        "params": "swing_n=8  min_rr=3.5  stop_buf=1.0 ATR",
    },
}


def card(col, label, value, color="grey"):
    col.markdown(
        f"""
    <div class="metric-card">
      <div class="metric-label">{label}</div>
      <div class="metric-value {color}">{value}</div>
    </div>""",
        unsafe_allow_html=True,
    )


def load_csv(path):
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    for col in ["pnl", "balance", "price"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def load_state(path):
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def render_asset(asset_key):
    cfg = ASSETS[asset_key]
    df = load_csv(cfg["trades"])
    state = load_state(cfg["state"])

    if df.empty:
        st.info(f"Paper trader running for {asset_key} - no trades yet.")
        return

    closed = df[df["action"] == "CLOSE"].copy()

    initial = state.get("capital", 10_000.0)
    balance = state.get("balance", df["balance"].iloc[-1] if not df.empty else initial)
    total_pnl = balance - initial
    roi = total_pnl / initial * 100
    n_trades = state.get("total_trades", len(closed))
    wins = state.get("wins", len(closed[closed["pnl"] > 0]) if not closed.empty else 0)
    losses = state.get("losses", len(closed[closed["pnl"] <= 0]) if not closed.empty else 0)
    win_rate = wins / n_trades * 100 if n_trades else 0
    open_pos = state.get("position")

    pnl_color = "green" if total_pnl >= 0 else "red"
    wr_color = "green" if win_rate >= 50 else "red"

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    card(c1, "Balance", f"${balance:,.2f}", pnl_color)
    card(c2, "Net P&L", f"${total_pnl:+,.2f}", pnl_color)
    card(c3, "ROI", f"{roi:+.2f}%", pnl_color)
    card(c4, "Trades", str(n_trades), "grey")
    card(c5, "Win Rate", f"{win_rate:.1f}%", wr_color)
    card(c6, "W / L", f"{wins} / {losses}", "grey")

    st.markdown("<br>", unsafe_allow_html=True)

    if open_pos:
        phase_names = {1: "Hard stop", 2: "Breakeven", 3: "Trailing"}
        phase_str = phase_names.get(open_pos.get("phase", 1), "?")
        st.info(
            f"Open {open_pos.get('dir', '?')} - "
            f"{open_pos.get('shares', '?')} units @ ${open_pos.get('entry', 0):,.3f}  |  "
            f"Stop: ${open_pos.get('stop', 0):,.3f} [{phase_str}]  |  "
            f"Entered: {open_pos.get('entry_time', '?')}  |  "
            f"Swept: {open_pos.get('swept_lvl', 0):,.3f}  "
            f"AVWAP: {open_pos.get('avwap', 0):,.3f}  "
            f"POC: {open_pos.get('poc', 0):,.3f}"
        )

    st.subheader("Equity Curve")
    if not closed.empty and "balance" in closed.columns:
        eq = closed.copy()
        eq["dt"] = pd.to_datetime(
            eq["date"].astype(str) + " " + eq["time"].astype(str), errors="coerce"
        )
        eq = eq.dropna(subset=["dt"]).sort_values("dt")
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=eq["dt"],
                y=eq["balance"],
                mode="lines+markers",
                line=dict(color="#3fb950", width=2),
                marker=dict(
                    color=["#3fb950" if p > 0 else "#f85149" for p in eq["pnl"].fillna(0)],
                    size=8,
                ),
                hovertemplate="<b>%{x}</b><br>Balance: $%{y:,.2f}<extra></extra>",
            )
        )
        fig.add_hline(
            y=initial,
            line_dash="dot",
            line_color="#8b949e",
            annotation_text=f"Start ${initial:,.0f}",
        )
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#0d1117",
            plot_bgcolor="#0d1117",
            height=300,
            margin=dict(l=0, r=0, t=20, b=0),
            xaxis=dict(gridcolor="#21262d"),
            yaxis=dict(gridcolor="#21262d", tickprefix="$"),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Equity curve will appear after the first closed trade.")

    st.subheader("Closed Trades")
    if not closed.empty:
        rows = []
        entry_map = {}
        for _, row in df.iterrows():
            if row["action"] in ("BUY", "SELL"):
                entry_map[row["date"] + row["time"]] = row
            elif row["action"] == "CLOSE":
                entry = None
                for key, value in reversed(list(entry_map.items())):
                    if key[:10] == row["date"]:
                        entry = value
                        break
                pnl_val = row["pnl"]
                entry_price = entry["price"] if entry is not None else ""
                rows.append(
                    {
                        "Date": row["date"],
                        "Entry": entry["time"] if entry is not None else "",
                        "Exit": row["time"],
                        "Dir": entry["dir"] if entry is not None else row.get("dir", ""),
                        "Units": int(entry["shares"] if entry is not None else row.get("shares", 0)),
                        "Entry $": f"${float(entry_price):,.3f}" if entry_price != "" else "---",
                        "Exit $": f"${row['price']:,.3f}",
                        "Stop $": f"${float(entry['stop']):,.3f}" if entry is not None else "---",
                        "Net P&L": f"${pnl_val:+,.2f}" if pd.notna(pnl_val) else "---",
                        "Balance": f"${row['balance']:,.2f}",
                        "Reason": row.get("reason", ""),
                        "Result": "WIN" if (pd.notna(pnl_val) and pnl_val > 0) else "LOSS",
                    }
                )

        table = pd.DataFrame(rows[::-1])

        def _color_result(val):
            if "WIN" in str(val):
                return "color:#3fb950;font-weight:bold"
            if "LOSS" in str(val):
                return "color:#f85149;font-weight:bold"
            return ""

        def _color_pnl(val):
            try:
                parsed = float(str(val).replace("$", "").replace(",", "").replace("+", ""))
                return "color:#3fb950" if parsed > 0 else "color:#f85149"
            except Exception:
                return ""

        styled = (
            table.style.applymap(_color_result, subset=["Result"])
            .applymap(_color_pnl, subset=["Net P&L"])
        )
        st.dataframe(styled, use_container_width=True, height=400)

        st.subheader("Daily P&L")
        daily = closed.groupby("date")["pnl"].sum().reset_index()
        colors = ["#3fb950" if v > 0 else "#f85149" for v in daily["pnl"]]
        fig2 = go.Figure(
            go.Bar(
                x=daily["date"],
                y=daily["pnl"],
                marker_color=colors,
                hovertemplate="<b>%{x}</b><br>P&L: $%{y:+,.2f}<extra></extra>",
            )
        )
        fig2.update_layout(
            template="plotly_dark",
            paper_bgcolor="#0d1117",
            plot_bgcolor="#0d1117",
            height=240,
            margin=dict(l=0, r=0, t=20, b=0),
            xaxis=dict(gridcolor="#21262d"),
            yaxis=dict(gridcolor="#21262d", tickprefix="$"),
        )
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("No closed trades yet.")


st.title("LFV Strategy - Live Paper Trading")
st.caption(
    f"Liquidity + Fair Value (AVWAP) + Volume Profile  |  "
    f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
)
st.markdown("---")

selected_view = st.radio(
    "Asset View",
    options=["Both", "GLD", "BTC-USD"],
    horizontal=True,
    index=0,
    label_visibility="collapsed",
)

if selected_view in ("Both", "GLD"):
    st.subheader("GLD - Gold ETF")
    render_asset("GLD")

if selected_view == "Both":
    st.markdown("---")

if selected_view in ("Both", "BTC-USD"):
    st.subheader("BTC-USD - Bitcoin")
    render_asset("BTC-USD")

with st.sidebar:
    st.header("Strategy Info")

    for _, cfg in ASSETS.items():
        st.markdown(f"**{cfg['label']}**")
        st.markdown(f"- Timeframe: {cfg['timeframe']}")
        st.markdown(f"- Signal: {cfg['signal']}")
        st.markdown(f"- Params: {cfg['params']}")
        st.markdown("- Trail: BE@2R -> ATR trail@3R")
        st.markdown("---")

    st.markdown(f"**Last refresh**: {datetime.now().strftime('%H:%M:%S')}")
    if st.button("Refresh Now"):
        st.rerun()

    st.markdown("**Auto-refresh every 60s**")
    st.markdown('<meta http-equiv="refresh" content="60">', unsafe_allow_html=True)
