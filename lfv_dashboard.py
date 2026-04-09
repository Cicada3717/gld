"""
lfv_dashboard.py - Live dashboard for GC=F Zone Refinement strategy (Alpaca execution).
"""
import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ── Live price via Alpaca data API (real-time, same feed as the trader) ───────
def _fetch_live_gld_price():
    """Return live GLD price from Alpaca IEX feed, or None on any failure."""
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockLatestTradeRequest
        key = os.environ.get("ALPACA_API_KEY", "")
        sec = os.environ.get("ALPACA_SECRET_KEY", "")
        if not key or "YOUR_KEY" in key:
            return None
        client = StockHistoricalDataClient(key, sec)
        req    = StockLatestTradeRequest(symbol_or_symbols="GLD")
        trade  = client.get_stock_latest_trade(req)
        return float(trade["GLD"].price)
    except Exception:
        return None



st.set_page_config(
    page_title="LFV Strategy",
    page_icon="📈",
    layout="wide",
)

st.markdown(
    """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">

<style>
:root {
    --bg:        #0a0a0a;
    --card:      #111111;
    --stroke:    #1e1e1e;
    --gold:      #d4a843;
    --green:     #30d158;
    --red:       #ff453a;
    --text:      #f5f5f7;
    --muted:     #6e6e73;
    --shadow:    0 1px 3px rgba(0,0,0,0.4);
    --r-card:    12px;
    --r-sm:      8px;
}

html, body, [class*="css"] {
    font-family: -apple-system, "SF Pro Display", "Inter", sans-serif;
}

body, .stApp {
    background-color: var(--bg) !important;
    color: var(--text) !important;
}

[data-testid="stAppViewContainer"] {
    background-color: var(--bg) !important;
}

[data-testid="stHeader"] {
    background-color: var(--bg) !important;
    border-bottom: 1px solid var(--stroke);
}

[data-testid="stSidebar"] {
    background-color: #0d0d0d !important;
    border-right: 1px solid var(--stroke);
}

[data-testid="stSidebar"] > div:first-child {
    padding-top: 1.5rem;
}

.block-container {
    padding-top: 1.75rem;
    padding-bottom: 2rem;
    padding-left: 2rem;
    padding-right: 2rem;
    max-width: 1400px;
}

/* ── Topbar / Hero ────────────────────────────────────────────────── */
.topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 1.25rem 1.5rem;
    background: var(--card);
    border: 1px solid var(--stroke);
    border-radius: var(--r-card);
    box-shadow: var(--shadow);
    margin-bottom: 1.25rem;
}

.topbar-left {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
}

.topbar-strategy {
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--gold);
}

.topbar-title {
    font-size: 1.3rem;
    font-weight: 700;
    letter-spacing: -0.025em;
    color: var(--text);
    margin: 0;
}

.topbar-sub {
    font-size: 0.82rem;
    color: var(--muted);
    margin: 0;
}

.topbar-metrics {
    display: flex;
    gap: 0.5rem;
    align-items: stretch;
}

.topbar-metric {
    padding: 0.7rem 1.1rem;
    background: var(--bg);
    border: 1px solid var(--stroke);
    border-radius: var(--r-sm);
    text-align: right;
    min-width: 110px;
}

.topbar-metric-label {
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 0.3rem;
}

.topbar-metric-value {
    font-size: 1.05rem;
    font-weight: 700;
    letter-spacing: -0.03em;
    color: var(--text);
}

.topbar-metric-value.pos { color: var(--green); }
.topbar-metric-value.neg { color: var(--red); }
.topbar-metric-value.gold { color: var(--gold); }

/* ── Cards ────────────────────────────────────────────────────────── */
.metric-card {
    padding: 1rem 1.1rem 1rem 1.1rem;
    background: var(--card);
    border: 1px solid var(--stroke);
    border-radius: var(--r-card);
    box-shadow: var(--shadow);
}

.metric-label {
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--muted);
}

.metric-value {
    margin-top: 0.35rem;
    font-size: 1.55rem;
    font-weight: 700;
    letter-spacing: -0.04em;
    color: var(--text);
}

.metric-value.positive { color: var(--green); }
.metric-value.negative { color: var(--red); }
.metric-value.neutral  { color: var(--text); }

.metric-sub {
    margin-top: 0.2rem;
    font-size: 0.78rem;
    color: var(--muted);
}

/* ── Zone pills ───────────────────────────────────────────────────── */
.pill-row {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
    margin-bottom: 0.9rem;
}

.pill {
    padding: 0.32rem 0.75rem;
    border-radius: 999px;
    border: 1px solid var(--stroke);
    background: var(--bg);
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--muted);
    letter-spacing: 0.03em;
}

.pill.ok    { border-color: var(--green); color: var(--green); background: rgba(48,209,88,0.07); }
.pill.warn  { border-color: var(--red);   color: var(--red);   background: rgba(255,69,58,0.07); }
.pill.gold  { border-color: var(--gold);  color: var(--gold);  background: rgba(212,168,67,0.08); }

/* ── Section headers ──────────────────────────────────────────────── */
.section-header {
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--muted);
    margin: 1.5rem 0 0.7rem 0;
}

.panel-title {
    font-size: 0.88rem;
    font-weight: 600;
    letter-spacing: -0.01em;
    color: var(--text);
    margin: 0 0 0.75rem 0;
}

/* ── Position banner ──────────────────────────────────────────────── */
.position-banner {
    margin: 1rem 0 1rem 0;
    padding: 0.9rem 1.1rem;
    border-radius: var(--r-card);
    border: 1px solid rgba(212,168,67,0.25);
    background: rgba(212,168,67,0.05);
}

.position-title {
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--gold);
    margin-bottom: 0.35rem;
}

.position-copy {
    font-size: 0.88rem;
    line-height: 1.7;
    color: var(--text);
}

/* ── Empty states ─────────────────────────────────────────────────── */
.empty-state {
    padding: 1rem 1.1rem;
    border-radius: var(--r-sm);
    border: 1px solid var(--stroke);
    background: var(--bg);
    font-size: 0.85rem;
    color: var(--muted);
}

/* ── Sidebar ──────────────────────────────────────────────────────── */
.sb-label {
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--muted);
    margin: 1.1rem 0 0.4rem 0;
}

.sb-value {
    font-size: 1.1rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    color: var(--text);
}

.sb-badge {
    display: inline-block;
    padding: 0.22rem 0.65rem;
    border-radius: 999px;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
}

.sb-badge.live   { background: rgba(48,209,88,0.12);  color: var(--green); border: 1px solid rgba(48,209,88,0.25); }
.sb-badge.paper  { background: rgba(212,168,67,0.12); color: var(--gold);  border: 1px solid rgba(212,168,67,0.25); }
.sb-badge.replay { background: rgba(110,110,115,0.12); color: var(--muted); border: 1px solid var(--stroke); }

.sb-filter {
    font-size: 0.8rem;
    color: var(--muted);
    line-height: 1.9;
    padding-left: 0;
    list-style: none;
    margin: 0;
}

.sb-filter li::before {
    content: "–  ";
    color: var(--stroke);
}

.sb-divider {
    height: 1px;
    background: var(--stroke);
    margin: 1rem 0;
}

/* ── Dataframe dark override ──────────────────────────────────────── */
div[data-testid="stDataFrame"] {
    border-radius: var(--r-card);
    overflow: hidden;
    border: 1px solid var(--stroke) !important;
}

div[data-testid="stDataFrame"] iframe {
    border-radius: var(--r-card);
}

/* ── Plotly chart containers ──────────────────────────────────────── */
div[data-testid="stPlotlyChart"] {
    border-radius: var(--r-card);
    overflow: hidden;
    background: var(--card);
    border: 1px solid var(--stroke);
    box-shadow: var(--shadow);
}

/* ── Streamlit button ─────────────────────────────────────────────── */
.stButton > button {
    background: var(--card) !important;
    border: 1px solid var(--stroke) !important;
    color: var(--text) !important;
    border-radius: var(--r-sm) !important;
    font-size: 0.82rem !important;
    font-weight: 600 !important;
    padding: 0.45rem 1rem !important;
    transition: border-color 150ms ease, background 150ms ease;
}

.stButton > button:hover {
    border-color: var(--gold) !important;
    background: rgba(212,168,67,0.07) !important;
}

/* ── Streamlit metric widget ──────────────────────────────────────── */
[data-testid="metric-container"] {
    background: var(--card);
    border: 1px solid var(--stroke);
    border-radius: var(--r-card);
    padding: 0.75rem 1rem;
}

[data-testid="metric-container"] label {
    color: var(--muted) !important;
    font-size: 0.68rem !important;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-weight: 600 !important;
}

[data-testid="metric-container"] [data-testid="stMetricValue"] {
    color: var(--text) !important;
    font-size: 1.3rem !important;
    font-weight: 700 !important;
    letter-spacing: -0.03em !important;
}

[data-testid="metric-container"] [data-testid="stMetricDelta"] {
    font-size: 0.75rem !important;
}

/* ── Misc cleanup ─────────────────────────────────────────────────── */
.stMarkdown p { color: var(--muted); font-size: 0.85rem; }
div[data-testid="stHorizontalBlock"] { gap: 0.75rem; }
.divider-space { height: 1.25rem; }
</style>
""",
    unsafe_allow_html=True,
)

DATA_DIR = Path(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", Path(__file__).parent))

ASSETS = {
    "GC=F": {
        "label": "GLD",
        "name": "Gold ETF (Alpaca live)",
        "state": DATA_DIR / "zone_state.json",
        "trades": DATA_DIR / "zone_trades.csv",
        "timeframe": "1H bars",
        "schedule": "Sun 18:00 ET to Fri 17:00 ET",
        "signal": "Supply & Demand zone refinement — ATR regime + crash filter + hour filter",
        "params": "min_rr=2.5  trail_act=2.5R  trail_dist=0.15R  slope=8  max2/day  72H-crash-filter",
        "accent": "#d4a843",
        "title": "Zone Strategy — GLD (from Mar 18)",
    },
}


def format_money(value):
    if value is None or pd.isna(value):
        return "---"
    return f"${value:,.2f}"


def format_signed_money(value):
    if value is None or pd.isna(value):
        return "---"
    return f"${value:+,.2f}"


def format_pct(value):
    if value is None or pd.isna(value):
        return "---"
    return f"{value:+.2f}%"


def format_units(value):
    if value is None or pd.isna(value):
        return "---"
    if abs(float(value) - round(float(value))) < 1e-9:
        return f"{int(round(float(value)))}"
    return f"{float(value):,.6f}"


def tone_class(value, positive_threshold=0):
    if value is None or pd.isna(value):
        return "neutral"
    if value > positive_threshold:
        return "positive"
    if value < positive_threshold:
        return "negative"
    return "neutral"


def card(col, label, value, subtext="", tone="neutral"):
    col.markdown(
        f"""
<div class="metric-card">
  <div class="metric-label">{label}</div>
  <div class="metric-value {tone}">{value}</div>
  <div class="metric-sub">{subtext}</div>
</div>
""",
        unsafe_allow_html=True,
    )


def load_csv(path):
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    for col in ["pnl", "balance", "price", "qty", "shares", "stop", "target"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    # normalise: Alpaca trader uses "qty"; old paper trader used "shares"
    if "qty" in df.columns and "shares" not in df.columns:
        df["shares"] = df["qty"]
    # normalise: Alpaca trader closes show as CLOSED_BY_ALPACA
    if "action" in df.columns:
        df["action"] = df["action"].replace("CLOSED_BY_ALPACA", "CLOSE")
    return df


def load_state(path):
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def build_snapshot(asset_key):
    cfg = ASSETS[asset_key]
    df = load_csv(cfg["trades"])
    state = load_state(cfg["state"])
    closed = df[df["action"] == "CLOSE"].copy() if not df.empty else pd.DataFrame()

    initial = float(state.get("capital", 10_000.0))
    balance = float(state.get("balance", df["balance"].iloc[-1] if not df.empty and "balance" in df.columns else initial))
    total_pnl = balance - initial
    roi = (total_pnl / initial * 100) if initial else 0.0
    n_trades = int(state.get("total_trades", len(closed)))
    wins = int(state.get("wins", len(closed[closed["pnl"] > 0]) if not closed.empty else 0))
    losses = int(state.get("losses", len(closed[closed["pnl"] <= 0]) if not closed.empty else 0))
    win_rate = (wins / n_trades * 100) if n_trades else 0.0
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_closed = closed[closed["date"].astype(str) == today_str].copy() if not closed.empty else pd.DataFrame()
    today_pnl = float(today_closed["pnl"].sum()) if not today_closed.empty else 0.0

    live_price = _fetch_live_gld_price()

    # Unrealised P&L on open position using live price
    open_pos   = state.get("position")
    unreal_pnl = None
    if open_pos and live_price:
        qty = float(open_pos.get("qty", open_pos.get("shares", 0)))
        entry = float(open_pos.get("entry", 0))
        if open_pos.get("dir") == "LONG":
            unreal_pnl = (live_price - entry) * qty
        else:
            unreal_pnl = (entry - live_price) * qty

    return {
        "cfg": cfg,
        "df": df,
        "state": state,
        "closed": closed,
        "initial": initial,
        "balance": balance,
        "total_pnl": total_pnl,
        "roi": roi,
        "n_trades": n_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "today_pnl": today_pnl,
        "today_trades": len(today_closed),
        "today_date": today_str,
        "open_pos": open_pos,
        "live_price": live_price,
        "unreal_pnl": unreal_pnl,
    }


def render_hero(snapshot):
    live_price = snapshot.get("live_price")
    price_str  = f"GLD&nbsp;${live_price:,.2f}" if live_price else "GLD&nbsp;closed"
    roi_val    = snapshot["roi"]
    roi_cls    = "pos" if roi_val > 0 else ("neg" if roi_val < 0 else "gold")
    pnl_cls    = "pos" if snapshot["total_pnl"] > 0 else ("neg" if snapshot["total_pnl"] < 0 else "gold")
    updated    = datetime.now().strftime("%H:%M:%S")

    st.markdown(
        f"""
<div class="topbar">
  <div class="topbar-left">
    <div class="topbar-strategy">Zone Refinement Strategy</div>
    <div class="topbar-title">LFV Dashboard</div>
    <div class="topbar-sub">{price_str}&nbsp;&nbsp;&nbsp;·&nbsp;&nbsp;&nbsp;Updated {updated}</div>
  </div>
  <div class="topbar-metrics">
    <div class="topbar-metric">
      <div class="topbar-metric-label">Balance</div>
      <div class="topbar-metric-value gold">{format_money(snapshot["balance"])}</div>
    </div>
    <div class="topbar-metric">
      <div class="topbar-metric-label">ROI</div>
      <div class="topbar-metric-value {roi_cls}">{format_pct(roi_val)}</div>
    </div>
    <div class="topbar-metric">
      <div class="topbar-metric-label">Win Rate</div>
      <div class="topbar-metric-value {'pos' if snapshot['win_rate'] >= 50 else 'neg'}">{snapshot["win_rate"]:.1f}%</div>
    </div>
    <div class="topbar-metric">
      <div class="topbar-metric-label">Trades</div>
      <div class="topbar-metric-value">{snapshot["n_trades"]}</div>
    </div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def render_position_banner(snapshot):
    open_pos   = snapshot["open_pos"]
    live_price = snapshot.get("live_price")
    unreal_pnl = snapshot.get("unreal_pnl")
    qty_val    = open_pos.get("qty", open_pos.get("shares", "?"))
    unreal_str = f"&nbsp;&nbsp;·&nbsp;&nbsp;Unrealised <b>{format_signed_money(unreal_pnl)}</b>" if unreal_pnl is not None else ""
    live_str   = f"&nbsp;&nbsp;·&nbsp;&nbsp;GLD <b>${live_price:,.2f}</b>" if live_price else ""
    copy = (
        f"{open_pos.get('dir', '?')} &nbsp;{format_units(qty_val)} shares "
        f"@ ${open_pos.get('entry', 0):,.2f}"
        f"&nbsp;&nbsp;·&nbsp;&nbsp;Stop ${open_pos.get('stop', 0):,.2f}"
        f"&nbsp;&nbsp;·&nbsp;&nbsp;Target ${open_pos.get('target', 0):,.2f}<br>"
        f"<span style='color:var(--muted);font-size:0.8rem'>"
        f"Entered {open_pos.get('entry_time', '?')}"
        f"&nbsp;&nbsp;·&nbsp;&nbsp;Zone: {open_pos.get('zone_type', '?')}"
        f"{live_str}{unreal_str}</span>"
    )
    st.markdown(
        f"""
<div class="position-banner">
  <div class="position-title">Open Position</div>
  <div class="position-copy">{copy}</div>
</div>
""",
        unsafe_allow_html=True,
    )


def render_equity_curve(snapshot):
    closed = snapshot["closed"]
    st.markdown('<div class="panel-title">Equity Curve</div>', unsafe_allow_html=True)
    if closed.empty or "balance" not in closed.columns:
        st.markdown(
            '<div class="empty-state">Equity will appear after the first closed trade.</div>',
            unsafe_allow_html=True,
        )
        return

    eq = closed.copy()
    eq["dt"] = pd.to_datetime(eq["date"].astype(str) + " " + eq["time"].astype(str), errors="coerce")
    eq = eq.dropna(subset=["dt"]).sort_values("dt")

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=eq["dt"],
            y=eq["balance"],
            mode="lines+markers",
            line=dict(color="#d4a843", width=2),
            marker=dict(
                size=6,
                color=["#30d158" if p > 0 else "#ff453a" for p in eq["pnl"].fillna(0)],
                line=dict(width=1, color="rgba(255,255,255,0.1)"),
            ),
            fill="tozeroy",
            fillcolor="rgba(212,168,67,0.06)",
            hovertemplate="<b>%{x}</b><br>Balance %{y:$,.2f}<extra></extra>",
        )
    )
    fig.add_hline(
        y=snapshot["initial"],
        line_dash="dot",
        line_color="rgba(110,110,115,0.5)",
        annotation_text=f"Start {format_money(snapshot['initial'])}",
        annotation_font_color="#6e6e73",
        annotation_position="top left",
    )
    fig.update_layout(
        height=300,
        margin=dict(l=12, r=12, t=12, b=12),
        paper_bgcolor="#111111",
        plot_bgcolor="#111111",
        xaxis=dict(
            title="",
            showgrid=True,
            gridcolor="rgba(255,255,255,0.04)",
            zeroline=False,
            color="#6e6e73",
            tickfont=dict(size=11, color="#6e6e73"),
        ),
        yaxis=dict(
            title="",
            showgrid=True,
            gridcolor="rgba(255,255,255,0.04)",
            zeroline=False,
            tickprefix="$",
            color="#6e6e73",
            tickfont=dict(size=11, color="#6e6e73"),
        ),
        font=dict(color="#6e6e73", family="-apple-system, 'SF Pro Display', 'Inter', sans-serif"),
    )
    st.plotly_chart(fig, width="stretch")


def build_trade_table(df):
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
            pnl_val = row.get("pnl")
            entry_price = entry["price"] if entry is not None else None
            rows.append(
                {
                    "Date":   row["date"],
                    "Dir":    entry["dir"] if entry is not None else row.get("dir", ""),
                    "Entry":  f"${float(entry_price):,.3f}" if entry_price is not None and pd.notna(entry_price) else "---",
                    "Exit":   f"${row['price']:,.3f}" if pd.notna(row.get("price")) else "---",
                    "Stop":   f"${float(entry['stop']):,.3f}" if entry is not None and pd.notna(entry.get("stop")) else "---",
                    "P&L":    f"${pnl_val:+,.2f}" if pd.notna(pnl_val) else "---",
                    "Result": "WIN" if (pd.notna(pnl_val) and pnl_val > 0) else "LOSS",
                }
            )
    return pd.DataFrame(rows[::-1])


def render_trade_table(snapshot):
    closed = snapshot["closed"]
    st.markdown('<div class="panel-title">Trade Log</div>', unsafe_allow_html=True)
    if closed.empty:
        st.markdown(
            '<div class="empty-state">No closed trades yet. The table will populate after the first completed position.</div>',
            unsafe_allow_html=True,
        )
        return

    table = build_trade_table(snapshot["df"])

    def color_row(row):
        if row["Result"] == "WIN":
            return ["background-color:rgba(48,209,88,0.07)"] * len(row)
        return ["background-color:rgba(255,69,58,0.06)"] * len(row)

    def color_result(val):
        if "WIN" in str(val):
            return "color:#30d158;font-weight:700"
        if "LOSS" in str(val):
            return "color:#ff453a;font-weight:700"
        return ""

    def color_pnl(val):
        try:
            parsed = float(str(val).replace("$", "").replace(",", "").replace("+", ""))
            return "color:#30d158;font-weight:600" if parsed > 0 else "color:#ff453a;font-weight:600"
        except Exception:
            return ""

    try:
        styled = (
            table.style
            .apply(color_row, axis=1)
            .map(color_result, subset=["Result"])
            .map(color_pnl, subset=["P&L"])
        )
    except AttributeError:
        styled = (
            table.style
            .apply(color_row, axis=1)
            .applymap(color_result, subset=["Result"])
            .applymap(color_pnl, subset=["P&L"])
        )
    st.dataframe(styled, width="stretch", height=340)


def render_daily_pnl(snapshot):
    closed = snapshot["closed"]
    st.markdown('<div class="panel-title">Daily P&amp;L</div>', unsafe_allow_html=True)
    if closed.empty:
        st.markdown(
            '<div class="empty-state">Daily performance will appear after trades start closing.</div>',
            unsafe_allow_html=True,
        )
        return

    daily = closed.groupby("date")["pnl"].sum().reset_index()
    colors = ["#30d158" if v > 0 else "#ff453a" for v in daily["pnl"]]
    fig = go.Figure(
        go.Bar(
            x=daily["date"],
            y=daily["pnl"],
            marker=dict(color=colors, line=dict(color="rgba(255,255,255,0.04)", width=0.5)),
            hovertemplate="<b>%{x}</b><br>P&L %{y:$+,.2f}<extra></extra>",
        )
    )
    fig.update_layout(
        height=300,
        margin=dict(l=12, r=12, t=12, b=12),
        paper_bgcolor="#111111",
        plot_bgcolor="#111111",
        xaxis=dict(
            showgrid=False,
            color="#6e6e73",
            tickfont=dict(size=11, color="#6e6e73"),
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor="rgba(255,255,255,0.04)",
            tickprefix="$",
            color="#6e6e73",
            tickfont=dict(size=11, color="#6e6e73"),
        ),
        font=dict(color="#6e6e73", family="-apple-system, 'SF Pro Display', 'Inter', sans-serif"),
    )
    st.plotly_chart(fig, width="stretch")


def render_asset(snapshot, asset_key):
    # Metric row
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    card(c1, "Balance",  format_money(snapshot["balance"]),          "Live balance",                   tone_class(snapshot["total_pnl"]))
    card(c2, "Net P&L",  format_signed_money(snapshot["total_pnl"]), "vs starting capital",            tone_class(snapshot["total_pnl"]))
    card(c3, "ROI",      format_pct(snapshot["roi"]),                "Portfolio return",               tone_class(snapshot["roi"]))
    card(c4, "Trades",   str(snapshot["n_trades"]),                  "Closed positions",               "neutral")
    card(c5, "Win Rate", f"{snapshot['win_rate']:.1f}%",             f"{snapshot['wins']}W / {snapshot['losses']}L", tone_class(snapshot["win_rate"], 50))
    card(c6, "Status",   "LIVE" if snapshot["open_pos"] else "FLAT", "Position manager state",         "neutral")

    if snapshot["open_pos"]:
        render_position_banner(snapshot)

    # Charts row
    left, right = st.columns([1.55, 1])
    with left:
        render_equity_curve(snapshot)
    with right:
        render_daily_pnl(snapshot)

    st.markdown('<div class="divider-space"></div>', unsafe_allow_html=True)
    render_trade_table(snapshot)
    st.markdown('<div class="divider-space"></div>', unsafe_allow_html=True)


def render_sidebar():
    cfg = ASSETS["GC=F"]
    with st.sidebar:
        st.markdown(
            '<div class="sb-label">Mode</div>'
            '<span class="sb-badge replay">Replay — Mar 18 2026</span>',
            unsafe_allow_html=True,
        )

        snapshot = build_snapshot("GC=F")
        st.markdown(
            f'<div class="sb-label">Balance</div>'
            f'<div class="sb-value">{format_money(snapshot["balance"])}</div>',
            unsafe_allow_html=True,
        )

        st.markdown('<div class="sb-divider"></div>', unsafe_allow_html=True)

        st.markdown(
            '<div class="sb-label">Active Filters</div>'
            '<ul class="sb-filter">'
            '<li>ATR regime 0.85 – 1.2×</li>'
            '<li>Body confirm 0.3 – 0.7× ATR</li>'
            '<li>Block hours 7,10,11,12,15,19 UTC</li>'
            '<li>72H crash: no LONG if drop &gt; 1.5%</li>'
            '</ul>',
            unsafe_allow_html=True,
        )

        st.markdown('<div class="sb-divider"></div>', unsafe_allow_html=True)

        # ── Alpaca live execution status ──────────────────────────────
        st.markdown('<div class="sb-label">Alpaca Live Status</div>', unsafe_allow_html=True)
        alpaca_state_path = DATA_DIR / "alpaca_state.json"
        if alpaca_state_path.exists():
            try:
                with open(alpaca_state_path) as _f:
                    _as = json.load(_f)
                _mode   = _as.get("mode", "?").upper()
                _bal    = _as.get("balance", 0)
                _trades = _as.get("total_trades", 0)
                _pnl    = _as.get("total_pnl", 0)
                _pos    = _as.get("position")
                _pos_str = (f"{_pos['dir']} {_pos.get('qty','')} @ ${_pos.get('entry',0):.2f}" if _pos else "Flat")
                badge_cls = "live" if _mode == "LIVE" else "paper"
                st.markdown(
                    f'<span class="sb-badge {badge_cls}">{_mode}</span>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'<div style="font-size:0.8rem;color:var(--muted);line-height:2;margin-top:0.4rem">'
                    f'Balance&nbsp;&nbsp;<span style="color:var(--text);font-weight:600">${_bal:,.2f}</span><br>'
                    f'P&amp;L&nbsp;&nbsp;<span style="color:{"var(--green)" if _pnl >= 0 else "var(--red)"};font-weight:600">${_pnl:+,.2f}</span><br>'
                    f'Trades&nbsp;&nbsp;<span style="color:var(--text);font-weight:600">{_trades}</span><br>'
                    f'Position&nbsp;&nbsp;<span style="color:var(--text);font-weight:600">{_pos_str}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            except Exception:
                st.markdown('<span style="color:var(--muted);font-size:0.8rem">State unreadable</span>', unsafe_allow_html=True)
        else:
            st.markdown('<span style="color:var(--muted);font-size:0.8rem">Waiting for market open</span>', unsafe_allow_html=True)

        live_price = _fetch_live_gld_price()
        if live_price:
            st.markdown(
                f'<div style="margin-top:0.5rem;font-size:0.8rem;color:var(--muted)">'
                f'GLD&nbsp;&nbsp;<span style="color:var(--gold);font-weight:700">${live_price:,.2f}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

        st.markdown('<div class="sb-divider"></div>', unsafe_allow_html=True)

        st.markdown(
            f'<div style="font-size:0.72rem;color:var(--muted);margin-bottom:0.6rem">'
            f'Last refresh&nbsp;&nbsp;{datetime.now().strftime("%H:%M:%S")}</div>',
            unsafe_allow_html=True,
        )
        if st.button("Refresh", use_container_width=False):
            st.rerun()
        st.markdown(
            '<div style="font-size:0.72rem;color:var(--muted);margin-top:0.4rem">Auto-refresh every 60s</div>'
            '<meta http-equiv="refresh" content="60">',
            unsafe_allow_html=True,
        )


def _fetch_gld_bars_alpaca():
    """Fetch 6 months of GLD 1H bars from Alpaca. Returns a clean DataFrame or empty."""
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        key = os.environ.get("ALPACA_API_KEY", "")
        sec = os.environ.get("ALPACA_SECRET_KEY", "")
        if not key or "YOUR_KEY" in key:
            return pd.DataFrame()
        client = StockHistoricalDataClient(key, sec)
        end   = pd.Timestamp.now(tz="UTC")
        start = end - pd.DateOffset(months=6)
        req   = StockBarsRequest(
            symbol_or_symbols="GLD",
            timeframe=TimeFrame.Hour,
            start=start,
            end=end,
            feed="iex",
        )
        bars = client.get_stock_bars(req).df
        if bars.empty:
            return pd.DataFrame()
        if isinstance(bars.index, pd.MultiIndex):
            bars = bars.xs("GLD", level="symbol")
        bars.index = pd.to_datetime(bars.index, utc=True).tz_localize(None)
        bars.columns = [c.capitalize() for c in bars.columns]
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col not in bars.columns:
                return pd.DataFrame()
        return bars[["Open", "High", "Low", "Close", "Volume"]].dropna()
    except Exception:
        return pd.DataFrame()


def render_zone_levels():
    """Live nearest zone levels panel — fetches GLD bars from Alpaca."""
    st.markdown('<div class="panel-title">Nearest Entry Zones — GLD</div>', unsafe_allow_html=True)
    try:
        import numpy as np
        from zone_refinement_backtest import detect_zones

        FILTER_ATR_LOW=0.85; FILTER_ATR_HIGH=1.20
        FILTER_BODY_LOW=0.30; FILTER_BODY_HIGH=0.70
        FILTER_BAD_HOURS={7,10,11,12,15,19}
        FILTER_TREND_PCT=-0.015; FILTER_TREND_BARS=72

        df1h = _fetch_gld_bars_alpaca()
        if df1h.empty:
            st.info("Waiting for GLD data from Alpaca…")
            return

        df4h = (df1h.resample("4h")
                .agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"})
                .dropna())
        zones = detect_zones(df4h, df1h, strength_bars=3, strength_mult=1.5)
        active = [z for z in zones if not z.get("consumed")]

        closes = df1h["Close"].tolist()
        highs  = df1h["High"].tolist()
        lows   = df1h["Low"].tolist()
        price  = float(df1h["Close"].iloc[-1])
        ts     = df1h.index[-1]
        dt     = ts.to_pydatetime()

        # BOS
        def ema_s(v, p):
            out = [float("nan")] * len(v)
            if len(v) < p: return out
            k = 2/(p+1); e = float(np.mean(v[:p])); out[p-1] = e
            for i in range(p, len(v)): e = v[i]*k+e*(1-k); out[i] = e
            return out
        ev = ema_s(closes, 21); valid = [x for x in ev if x == x]
        bull = len(valid) > 8 and valid[-1] > valid[-9]
        bear = len(valid) > 8 and valid[-1] < valid[-9]
        trend20 = closes[-1] - closes[-20] if len(closes) >= 20 else 0
        n = len(closes)
        t72 = closes[-1] - closes[-FILTER_TREND_BARS] if n >= FILTER_TREND_BARS else closes[-1] - closes[0]
        t72p = t72 / closes[-1] if closes[-1] > 0 else 0

        # ATR
        h = np.array(highs[-16:]); l = np.array(lows[-16:]); c = np.array(closes[-16:])
        tr = np.maximum(h[1:]-l[1:], np.maximum(abs(h[1:]-c[:-1]), abs(l[1:]-c[:-1])))
        f_atr = float(np.mean(tr[-14:])) if len(tr) >= 14 else float(np.mean(tr))
        h2 = np.array(highs[-32:]); l2 = np.array(lows[-32:]); c2 = np.array(closes[-32:])
        tr2 = np.maximum(h2[1:]-l2[1:], np.maximum(abs(h2[1:]-c2[:-1]), abs(l2[1:]-c2[:-1])))
        f_avg = float(np.mean(tr2[-20:])) if len(tr2) >= 20 else float(np.mean(tr2))
        f_ratio = f_atr / f_avg if f_avg > 0 else 1.0
        f_body = abs(float(df1h["Close"].iloc[-1]) - float(df1h["Open"].iloc[-1])) / f_atr if f_atr > 0 else 0
        f_bull = float(df1h["Close"].iloc[-1]) >= float(df1h["Open"].iloc[-1])

        # Current conditions
        bos_str  = "Bullish" if bull else ("Bearish" if bear else "Neutral")
        atr_ok   = FILTER_ATR_LOW <= f_ratio <= FILTER_ATR_HIGH
        hour_ok  = dt.hour not in FILTER_BAD_HOURS
        crash_ok = t72p >= FILTER_TREND_PCT

        # Pill row
        price_pill  = f"Price ${price:,.1f}"
        bos_pill    = f"BOS {bos_str}"
        atr_pill    = f"ATR {f_ratio:.2f}×"
        t72_pill    = f"72H {t72p*100:+.1f}%"
        hour_pill   = f"Hour {dt.hour}:00"

        atr_cls   = "ok" if atr_ok   else "warn"
        t72_cls   = "ok" if crash_ok else "warn"
        hour_cls  = "ok" if hour_ok  else "warn"
        bos_cls   = "ok" if (bull or bear) else "gold"

        st.markdown(
            f'<div class="pill-row">'
            f'<span class="pill gold">{price_pill}</span>'
            f'<span class="pill {bos_cls}">{bos_pill}</span>'
            f'<span class="pill {atr_cls}">{atr_pill}</span>'
            f'<span class="pill {t72_cls}">{t72_pill}</span>'
            f'<span class="pill {hour_cls}">{hour_pill}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Zone table (max 8 rows)
        rows = []
        for z in sorted(active, key=lambda z: abs(price - (z["htf_top"]+z["htf_bottom"])/2))[:8]:
            mid   = (z["htf_top"] + z["htf_bottom"]) / 2
            dist  = price - mid
            inside = z["htf_bottom"] <= price <= z["htf_top"]
            loc    = "INSIDE" if inside else ("above" if price > z["htf_top"] else "below")

            blocks = []
            if z["type"] == "demand":
                if not bull:       blocks.append("BOS")
                if trend20 < 0:    blocks.append("trend")
                if t72p < FILTER_TREND_PCT: blocks.append("crash")
            else:
                if not bear:       blocks.append("BOS")
                if trend20 > 0:    blocks.append("trend")
            if not atr_ok:         blocks.append(f"ATR")
            if dt.hour in FILTER_BAD_HOURS: blocks.append(f"hr")
            signed = f_body if (z["type"]=="demand" and f_bull) or (z["type"]=="supply" and not f_bull) else -f_body
            if FILTER_BODY_LOW <= signed < FILTER_BODY_HIGH: blocks.append("body")

            if inside and not blocks:
                signal = "SIGNAL READY"
            elif inside:
                signal = "Blocked: " + " | ".join(blocks)
            else:
                signal = "—"

            rows.append({
                "Type":       z["type"].upper(),
                "Zone Range": f"${z['htf_bottom']:,.0f} – ${z['htf_top']:,.0f}",
                "Entry Range":f"${z['refined_bottom']:,.1f} – ${z['refined_top']:,.1f}",
                "Distance":   f"{dist:+,.1f}",
                "Status":     loc,
                "Signal":     signal,
            })

        df_zones = pd.DataFrame(rows)

        def color_zone_rows(row):
            if row["Type"] == "DEMAND":
                base = "background-color:rgba(48,209,88,0.05);color:#f5f5f7"
            else:
                base = "background-color:rgba(255,69,58,0.05);color:#f5f5f7"
            styles = [base] * len(row)
            if "SIGNAL READY" in row["Signal"]:
                styles[-1] = "background-color:rgba(48,209,88,0.2);color:#30d158;font-weight:700"
            elif "Blocked" in row["Signal"]:
                styles[-1] = "color:#6e6e73"
            return styles

        styled = df_zones.style.apply(color_zone_rows, axis=1)
        st.dataframe(styled, width="stretch", height=320)

        st.markdown(
            f'<div style="font-size:0.72rem;color:var(--muted);margin-top:0.4rem">'
            f'Last bar: {str(ts)[:16]} UTC&nbsp;&nbsp;·&nbsp;&nbsp;Active zones: {len(active)}'
            f'</div>',
            unsafe_allow_html=True,
        )

    except Exception as e:
        st.warning(f"Zone data unavailable: {e}")


# ── Main render ──────────────────────────────────────────────────────────────
snapshot = build_snapshot("GC=F")
render_hero(snapshot)
st.markdown('<div class="section-header">Zones</div>', unsafe_allow_html=True)
render_zone_levels()
st.markdown('<div class="section-header">Performance</div>', unsafe_allow_html=True)
render_asset(snapshot, "GC=F")
render_sidebar()
