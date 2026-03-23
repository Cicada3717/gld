"""
dashboard.py — Dual Strategy Dashboard
ClaudeAPEX v12 (5m Gap Momentum) vs Zone Refinement (1H Supply/Demand)
Toggle at the top to switch between them.
"""
import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="GLD Strategy Dashboard",
    page_icon="📈",
    layout="wide",
)

# ── Dark theme ────────────────────────────────────────────────────────────────
st.markdown("""
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
div[data-testid="stRadio"] > div { gap: 8px; }
div[data-testid="stRadio"] label {
    background: #161b22; border: 1px solid #30363d;
    border-radius: 6px; padding: 6px 18px; cursor: pointer;
}
div[data-testid="stRadio"] label:has(input:checked) {
    border-color: #3fb950; color: #3fb950;
}
</style>
""", unsafe_allow_html=True)

DATA_DIR = Path(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", Path(__file__).parent))

STRATEGIES = {
    "ClaudeAPEX v12  (5m)": {
        "trade_log":  DATA_DIR / "paper_trades.csv",
        "state_file": DATA_DIR / "paper_state.json",
        "info": {
            "name":      "ClaudeAPEX v12",
            "asset":     "GC=F (Gold Futures)",
            "timeframe": "5m bars",
            "signal":    "Gap Momentum",
            "filters":   "VEI regime + VWAP + EMA",
            "session":   "09:30–16:00 ET Mon–Fri",
            "leverage":  "5x",
        },
    },
    "Zone Refinement  (1H)": {
        "trade_log":  DATA_DIR / "zone_trades.csv",
        "state_file": DATA_DIR / "zone_state.json",
        "info": {
            "name":      "Zone Refinement",
            "asset":     "GC=F (Gold Futures)",
            "timeframe": "1H bars",
            "signal":    "Supply & Demand Zones",
            "filters":   "4H HTF zones + 1H refinement + EMA BOS",
            "session":   "24/5 (Sun 18:00 – Fri 17:00 ET)",
            "leverage":  "5x",
        },
    },
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def card(col, label, value, color="grey"):
    col.markdown(f"""
    <div class="metric-card">
      <div class="metric-label">{label}</div>
      <div class="metric-value {color}">{value}</div>
    </div>""", unsafe_allow_html=True)


def load_csv(path):
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    for col in ["pnl", "balance", "price"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def load_json(path):
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


# ── Main dashboard renderer ───────────────────────────────────────────────────

def render(cfg):
    df      = load_csv(cfg["trade_log"])
    state   = load_json(cfg["state_file"])
    info    = cfg["info"]

    if df.empty:
        st.info("No trades yet. Paper trader will log here once the first signal fires.")
        return

    closed  = df[df["action"] == "CLOSE"].copy()
    entries = df[df["action"].isin(["BUY", "SELL"])].copy()

    # ── KPIs ─────────────────────────────────────────────────────────────────
    initial  = state.get("capital", 500.0)
    balance  = state.get("balance", df["balance"].iloc[-1] if not df.empty else initial)
    total_pnl = balance - initial
    roi       = total_pnl / initial * 100
    n_trades  = state.get("total_trades", len(closed))
    wins      = state.get("wins",   len(closed[closed["pnl"] > 0]) if not closed.empty else 0)
    losses    = state.get("losses", len(closed[closed["pnl"] <= 0]) if not closed.empty else 0)
    win_rate  = wins / n_trades * 100 if n_trades else 0
    open_pos  = state.get("position")

    pnl_color = "green" if total_pnl >= 0 else "red"
    wr_color  = "green" if win_rate  >= 50 else "red"

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    card(c1, "Balance",  f"${balance:,.2f}",    pnl_color)
    card(c2, "Net P&L",  f"${total_pnl:+,.2f}", pnl_color)
    card(c3, "ROI",      f"{roi:+.2f}%",         pnl_color)
    card(c4, "Trades",   str(n_trades),           "grey")
    card(c5, "Win Rate", f"{win_rate:.1f}%",      wr_color)
    card(c6, "W / L",    f"{wins} / {losses}",    "grey")

    st.markdown("<br>", unsafe_allow_html=True)

    # Open position banner
    if open_pos:
        pos = open_pos
        entry = pos.get("entry", pos.get("entry_price", "?"))
        stop  = pos.get("stop", pos.get("trail", "?"))
        st.info(
            f"**Open**: {pos.get('dir','?')}  {pos.get('shares','?')} shares "
            f"@ ${entry:.3f}  |  Stop: ${stop:.3f}  |  "
            f"Entered: {pos.get('entry_time','?')}"
        )

    # ── Equity curve ──────────────────────────────────────────────────────────
    st.subheader("Equity Curve")
    if not closed.empty and "balance" in closed.columns:
        eq = closed.copy()
        eq["dt"] = pd.to_datetime(
            eq["date"].astype(str) + " " + eq["time"].astype(str), errors="coerce"
        )
        eq = eq.dropna(subset=["dt"]).sort_values("dt")

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=eq["dt"], y=eq["balance"],
            mode="lines+markers",
            line=dict(color="#3fb950", width=2),
            marker=dict(
                color=["#3fb950" if p > 0 else "#f85149" for p in eq["pnl"].fillna(0)],
                size=8,
            ),
            hovertemplate="<b>%{x}</b><br>Balance: $%{y:,.2f}<extra></extra>",
            name="Balance",
        ))
        fig.add_hline(y=initial, line_dash="dot", line_color="#8b949e",
                      annotation_text=f"Start ${initial:,.0f}")
        fig.update_layout(
            template="plotly_dark", paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
            height=320, margin=dict(l=0, r=0, t=20, b=0),
            xaxis=dict(gridcolor="#21262d"),
            yaxis=dict(gridcolor="#21262d", tickprefix="$"),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No closed trades yet — equity curve will appear after first close.")

    # ── Trade table ───────────────────────────────────────────────────────────
    st.subheader("All Trades")
    if not closed.empty:
        rows      = []
        entry_map = {}
        for _, row in df.iterrows():
            if row["action"] in ("BUY", "SELL"):
                entry_map[row["date"]] = row
            elif row["action"] == "CLOSE":
                e        = entry_map.get(row["date"])
                has_entry = e is not None
                pnl_val  = row["pnl"]
                ep       = e["price"] if has_entry else ""
                rows.append({
                    "Date":        row["date"],
                    "Entry":       e["time"]  if has_entry else "",
                    "Exit":        row["time"],
                    "Dir":         e["dir"]   if has_entry else row.get("dir", ""),
                    "Shares":      int(e["shares"] if has_entry else row.get("shares", 0)),
                    "Entry $":     f"${float(ep):.3f}" if ep != "" else "—",
                    "Exit $":      f"${row['price']:.3f}",
                    "Stop $":      f"${float(e['stop']):.3f}" if has_entry else "—",
                    "Net P&L":     f"${pnl_val:+,.2f}" if pd.notna(pnl_val) else "—",
                    "Balance":     f"${row['balance']:,.2f}",
                    "Reason":      row.get("reason", ""),
                    "Result":      "WIN" if (pd.notna(pnl_val) and pnl_val > 0) else "LOSS",
                })

        tbl = pd.DataFrame(rows[::-1])

        def _color_result(val):
            if "WIN"  in str(val): return "color:#3fb950;font-weight:bold"
            if "LOSS" in str(val): return "color:#f85149;font-weight:bold"
            return ""

        def _color_pnl(val):
            try:
                v = float(str(val).replace("$", "").replace(",", ""))
                return "color:#3fb950" if v > 0 else "color:#f85149"
            except Exception:
                return ""

        styled = (tbl.style
                  .applymap(_color_result, subset=["Result"])
                  .applymap(_color_pnl,    subset=["Net P&L"]))
        st.dataframe(styled, use_container_width=True, height=420)

        # ── Daily P&L ─────────────────────────────────────────────────────────
        st.subheader("Daily P&L")
        daily  = closed.groupby("date")["pnl"].sum().reset_index()
        colors = ["#3fb950" if v > 0 else "#f85149" for v in daily["pnl"]]
        fig2   = go.Figure(go.Bar(
            x=daily["date"], y=daily["pnl"],
            marker_color=colors,
            hovertemplate="<b>%{x}</b><br>P&L: $%{y:+,.2f}<extra></extra>",
        ))
        fig2.update_layout(
            template="plotly_dark", paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
            height=260, margin=dict(l=0, r=0, t=20, b=0),
            xaxis=dict(gridcolor="#21262d"),
            yaxis=dict(gridcolor="#21262d", tickprefix="$"),
        )
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("No closed trades to display yet.")

    # ── Sidebar info ──────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("Strategy Info")
        for k, v in info.items():
            st.markdown(f"**{k.title()}**: {v}")
        st.markdown("---")
        st.markdown(f"**Last Refresh**: {datetime.now().strftime('%H:%M:%S')}")
        if st.button("Refresh"):
            st.rerun()


# ── Page ──────────────────────────────────────────────────────────────────────

st.title("GLD Paper Trading Dashboard")
st.caption(f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
st.markdown("---")

choice = st.radio(
    "Strategy",
    list(STRATEGIES.keys()),
    horizontal=True,
    label_visibility="collapsed",
)

st.markdown("<br>", unsafe_allow_html=True)

render(STRATEGIES[choice])
