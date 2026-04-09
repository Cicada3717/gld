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
    page_icon="chart_with_upwards_trend",
    layout="wide",
)

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&family=Instrument+Serif:ital@0;1&display=swap');

:root {
    --bg: #f4f1ea;
    --panel: rgba(255, 255, 255, 0.72);
    --panel-strong: rgba(255, 255, 255, 0.88);
    --stroke: rgba(23, 30, 47, 0.08);
    --text: #171d2c;
    --muted: #697487;
    --green: #14835f;
    --red: #c45d48;
    --gold: #a47a1f;
    --shadow: 0 22px 50px rgba(26, 37, 56, 0.10);
}

html, body, [class*="css"]  {
    font-family: "DM Sans", "SF Pro Text", "Segoe UI", "Helvetica Neue", sans-serif;
}

body, .stApp {
    color: var(--text);
    background:
        radial-gradient(circle at top left, rgba(240, 213, 157, 0.45), transparent 28%),
        radial-gradient(circle at top right, rgba(171, 198, 255, 0.35), transparent 24%),
        linear-gradient(180deg, #fbfaf7 0%, #f2eee6 100%);
}

[data-testid="stAppViewContainer"] {
    background: transparent;
}

[data-testid="stHeader"] {
    background: rgba(255,255,255,0);
}

[data-testid="stSidebar"] {
    background: rgba(255, 255, 255, 0.58);
    border-left: 1px solid rgba(23, 30, 47, 0.08);
    backdrop-filter: blur(22px);
}

[data-testid="stSidebar"] > div:first-child {
    padding-top: 1.5rem;
}

.block-container {
    padding-top: 2rem;
    padding-bottom: 2rem;
    max-width: 1360px;
}

.hero-shell {
    position: relative;
    overflow: hidden;
    padding: 1.75rem 1.75rem 1.55rem 1.75rem;
    border-radius: 30px;
    background: linear-gradient(145deg, rgba(255,255,255,0.78), rgba(255,255,255,0.58));
    border: 1px solid rgba(255,255,255,0.55);
    box-shadow: var(--shadow);
    backdrop-filter: blur(24px);
}

.hero-shell:before {
    content: "";
    position: absolute;
    inset: -20% auto auto -10%;
    width: 280px;
    height: 280px;
    border-radius: 999px;
    background: radial-gradient(circle, rgba(240, 211, 142, 0.70), transparent 68%);
    pointer-events: none;
}

.hero-shell:after {
    content: "";
    position: absolute;
    inset: auto -8% -28% auto;
    width: 320px;
    height: 320px;
    border-radius: 999px;
    background: radial-gradient(circle, rgba(151, 177, 239, 0.42), transparent 68%);
    pointer-events: none;
}

.eyebrow {
    position: relative;
    z-index: 1;
    display: inline-block;
    padding: 0.38rem 0.7rem;
    border-radius: 999px;
    background: rgba(255,255,255,0.72);
    border: 1px solid rgba(23, 30, 47, 0.08);
    color: var(--muted);
    font-size: 0.77rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

.hero-grid {
    position: relative;
    z-index: 1;
    display: grid;
    grid-template-columns: minmax(0, 1.45fr) minmax(260px, 0.8fr);
    gap: 1.25rem;
    margin-top: 1rem;
}

.hero-title {
    margin: 0.55rem 0 0.4rem 0;
    font-family: "Instrument Serif", "Georgia", serif;
    font-size: clamp(2.6rem, 5vw, 4.8rem);
    line-height: 0.95;
    letter-spacing: -0.04em;
}

.hero-copy {
    max-width: 720px;
    color: var(--muted);
    font-size: 1rem;
    line-height: 1.7;
    margin: 0;
}

.hero-stack {
    display: grid;
    gap: 0.85rem;
}

.mini-panel {
    padding: 1rem 1.1rem;
    border-radius: 24px;
    background: rgba(255, 255, 255, 0.62);
    border: 1px solid rgba(23, 30, 47, 0.08);
    backdrop-filter: blur(18px);
}

.mini-label {
    color: var(--muted);
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-weight: 700;
}

.mini-value {
    margin-top: 0.25rem;
    font-size: 1.7rem;
    font-weight: 700;
    letter-spacing: -0.04em;
}

.mini-sub {
    margin-top: 0.2rem;
    color: var(--muted);
    font-size: 0.88rem;
}

.asset-shell {
    margin-top: 1.25rem;
    padding: 1.2rem;
    border-radius: 28px;
    background: linear-gradient(180deg, rgba(255,255,255,0.78), rgba(255,255,255,0.60));
    border: 1px solid rgba(255,255,255,0.55);
    box-shadow: var(--shadow);
    backdrop-filter: blur(20px);
}

.asset-header {
    display: flex;
    align-items: end;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: 1rem;
}

.asset-kicker {
    color: var(--muted);
    font-size: 0.78rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

.asset-title {
    margin: 0.18rem 0 0.2rem 0;
    font-size: clamp(1.7rem, 2vw, 2.4rem);
    letter-spacing: -0.04em;
}

.asset-meta {
    color: var(--muted);
    font-size: 0.95rem;
}

.badge-row {
    display: flex;
    gap: 0.55rem;
    flex-wrap: wrap;
}

.soft-badge {
    padding: 0.48rem 0.8rem;
    border-radius: 999px;
    background: rgba(255,255,255,0.72);
    border: 1px solid rgba(23, 30, 47, 0.08);
    color: var(--muted);
    font-size: 0.82rem;
    font-weight: 600;
}

.metric-card {
    padding: 1rem 1.05rem 1.05rem 1.05rem;
    border-radius: 24px;
    background: var(--panel);
    border: 1px solid rgba(23, 30, 47, 0.07);
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.6);
    backdrop-filter: blur(16px);
}

.metric-label {
    color: var(--muted);
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-weight: 700;
}

.metric-value {
    margin-top: 0.4rem;
    font-size: 1.75rem;
    font-weight: 700;
    letter-spacing: -0.05em;
    color: var(--text);
}

.metric-sub {
    margin-top: 0.18rem;
    color: var(--muted);
    font-size: 0.84rem;
}

.positive { color: var(--green); }
.negative { color: var(--red); }
.neutral { color: var(--text); }

.panel-title {
    margin: 0.2rem 0 0.85rem 0;
    font-size: 1.05rem;
    font-weight: 700;
    letter-spacing: -0.02em;
}

.position-banner {
    margin: 1rem 0 1.15rem 0;
    padding: 1rem 1.05rem;
    border-radius: 24px;
    background: linear-gradient(135deg, rgba(255,255,255,0.76), rgba(255,255,255,0.56));
    border: 1px solid rgba(23, 30, 47, 0.08);
    color: var(--text);
}

.position-title {
    font-size: 0.82rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-weight: 700;
}

.position-copy {
    margin-top: 0.38rem;
    line-height: 1.6;
    color: var(--text);
}

.empty-state {
    padding: 1.1rem 1.15rem;
    border-radius: 24px;
    background: rgba(255,255,255,0.58);
    border: 1px solid rgba(23, 30, 47, 0.08);
    color: var(--muted);
}

.divider-space {
    height: 1rem;
}

.stRadio [role="radiogroup"] {
    gap: 0.6rem;
    padding: 0.45rem;
    width: fit-content;
    border-radius: 999px;
    background: rgba(255,255,255,0.6);
    border: 1px solid rgba(23, 30, 47, 0.08);
    box-shadow: var(--shadow);
}

.stRadio [role="radiogroup"] label {
    min-width: 124px;
    justify-content: center;
    border-radius: 999px;
    padding: 0.55rem 1rem;
    background: transparent;
    border: 1px solid transparent;
    transition: all 180ms ease;
}

.stRadio [role="radiogroup"] label:has(input:checked) {
    background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(243,240,234,0.98));
    border-color: rgba(23, 30, 47, 0.08);
    box-shadow: 0 10px 24px rgba(26, 37, 56, 0.10);
}

.stRadio [role="radiogroup"] p {
    font-size: 0.92rem;
    font-weight: 700;
    color: var(--text);
}

div[data-testid="stHorizontalBlock"] > div {
    gap: 0.8rem;
}

div[data-testid="stDataFrame"] {
    border-radius: 22px;
    overflow: hidden;
    border: 1px solid rgba(23, 30, 47, 0.08);
    background: rgba(255,255,255,0.70);
}

@media (max-width: 980px) {
    .hero-grid {
        grid-template-columns: 1fr;
    }
    .asset-header {
        flex-direction: column;
        align-items: start;
    }
    .stRadio [role="radiogroup"] {
        width: 100%;
    }
}
</style>
""",
    unsafe_allow_html=True,
)

DATA_DIR = Path(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", Path(__file__).parent))

ASSETS = {
    "GC=F": {
        "label": "GLD",
        "name": "Gold ETF (Alpaca live)",
        "state": DATA_DIR / "zone_state.json",    # replay → paper trader state
        "trades": DATA_DIR / "zone_trades.csv",   # replay → paper trader log
        "timeframe": "1H bars",
        "schedule": "Sun 18:00 ET to Fri 17:00 ET",
        "signal": "Supply & Demand zone refinement — ATR regime + crash filter + hour filter",
        "params": "min_rr=2.5  trail_act=2.5R  trail_dist=0.15R  slope=8  max2/day  72H-crash-filter",
        "accent": "#a47a1f",
        "title": "Zone Strategy — GC=F (from Mar 18)",
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
    cfg        = snapshot["cfg"]
    open_pos   = snapshot["open_pos"]
    live_price = snapshot.get("live_price")
    unreal_pnl = snapshot.get("unreal_pnl")

    open_status = "Open trade" if open_pos else "No open trade"
    qty_val = open_pos.get("qty", open_pos.get("shares", "?")) if open_pos else "?"
    open_sub = (
        f"{open_pos.get('dir','?')} {format_units(qty_val)} shares "
        f"@ ${open_pos.get('entry',0):,.2f}"
        + (f" | Unreal: {format_signed_money(unreal_pnl)}" if unreal_pnl is not None else "")
        if open_pos else "Watching for the next signal"
    )

    live_str = f"${live_price:,.2f}" if live_price else "market closed"

    st.markdown(
        f"""
<div class="hero-shell">
  <div class="eyebrow">GC=F Zone Strategy — replaying from Mar 18 2026</div>
  <div class="hero-grid">
      <div>
        <div class="hero-title">{cfg['title']}</div>
        <p class="hero-copy">GLD live: {live_str} &nbsp;|&nbsp; Updated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
      </div>
    <div class="hero-stack">
      <div class="mini-panel">
        <div class="mini-label">Today's P&amp;L</div>
        <div class="mini-value">{format_signed_money(snapshot["today_pnl"])}</div>
        <div class="mini-sub">{snapshot["today_trades"]} closed trades on {snapshot["today_date"]}</div>
      </div>
      <div class="mini-panel">
        <div class="mini-label">Balance</div>
        <div class="mini-value">{format_money(snapshot["balance"])}</div>
        <div class="mini-sub">{format_signed_money(snapshot["total_pnl"])} total | win rate {snapshot["win_rate"]:.1f}%</div>
      </div>
      <div class="mini-panel">
        <div class="mini-label">{open_status}</div>
        <div class="mini-value">{"LIVE" if open_pos else "FLAT"}</div>
        <div class="mini-sub">{open_sub}</div>
      </div>
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
    unreal_str = f" | Unrealised P&L: <b>{format_signed_money(unreal_pnl)}</b>" if unreal_pnl is not None else ""
    live_str   = f" | GLD now: <b>${live_price:,.2f}</b>" if live_price else ""
    copy = (
        f"{open_pos.get('dir', '?')} {format_units(qty_val)} shares "
        f"@ ${open_pos.get('entry', 0):,.2f} "
        f"| Stop ${open_pos.get('stop', 0):,.2f} "
        f"| Target ${open_pos.get('target', 0):,.2f}<br>"
        f"Entered {open_pos.get('entry_time', '?')} | Zone: {open_pos.get('zone_type', '?')}"
        f"{live_str}{unreal_str}"
    )
    st.markdown(
        f"""
<div class="position-banner">
  <div class="position-title">Open position</div>
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
            line=dict(color="#1f6f5d", width=3),
            marker=dict(
                size=8,
                color=["#1f8c69" if p > 0 else "#c45d48" for p in eq["pnl"].fillna(0)],
                line=dict(width=1, color="rgba(255,255,255,0.75)"),
            ),
            fill="tozeroy",
            fillcolor="rgba(31, 111, 93, 0.08)",
            hovertemplate="<b>%{x}</b><br>Balance %{y:$,.2f}<extra></extra>",
        )
    )
    fig.add_hline(
        y=snapshot["initial"],
        line_dash="dot",
        line_color="rgba(105,116,135,0.8)",
        annotation_text=f"Start {format_money(snapshot['initial'])}",
        annotation_position="top left",
    )
    fig.update_layout(
        height=320,
        margin=dict(l=8, r=8, t=8, b=8),
        paper_bgcolor="rgba(255,255,255,0.0)",
        plot_bgcolor="rgba(255,255,255,0.0)",
        xaxis=dict(
            title="",
            showgrid=True,
            gridcolor="rgba(23,30,47,0.08)",
            zeroline=False,
            color="#5d6778",
        ),
        yaxis=dict(
            title="",
            showgrid=True,
            gridcolor="rgba(23,30,47,0.08)",
            zeroline=False,
            tickprefix="$",
            color="#5d6778",
        ),
        font=dict(color="#171d2c", family="DM Sans, sans-serif"),
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
                    "Date": row["date"],
                    "Entry": entry["time"] if entry is not None else "",
                    "Exit": row["time"],
                    "Dir": entry["dir"] if entry is not None else row.get("dir", ""),
                    "Units": format_units(entry["shares"] if entry is not None else row.get("shares", 0)),
                    "Entry $": f"${float(entry_price):,.3f}" if entry_price is not None and pd.notna(entry_price) else "---",
                    "Exit $": f"${row['price']:,.3f}" if pd.notna(row.get("price")) else "---",
                    "Stop $": f"${float(entry['stop']):,.3f}" if entry is not None and pd.notna(entry.get("stop")) else "---",
                    "Net P&L": f"${pnl_val:+,.2f}" if pd.notna(pnl_val) else "---",
                    "Balance": f"${row['balance']:,.2f}" if pd.notna(row.get("balance")) else "---",
                    "Reason": row.get("reason", ""),
                    "Result": "WIN" if (pd.notna(pnl_val) and pnl_val > 0) else "LOSS",
                }
            )
    return pd.DataFrame(rows[::-1])


def render_trade_table(snapshot):
    closed = snapshot["closed"]
    st.markdown('<div class="panel-title">Closed Trades</div>', unsafe_allow_html=True)
    if closed.empty:
        st.markdown(
            '<div class="empty-state">No closed trades yet. The table will populate after the first completed position.</div>',
            unsafe_allow_html=True,
        )
        return

    table = build_trade_table(snapshot["df"])

    def color_result(val):
        if "WIN" in str(val):
            return "color:#14835f;font-weight:700"
        if "LOSS" in str(val):
            return "color:#c45d48;font-weight:700"
        return ""

    def color_pnl(val):
        try:
            parsed = float(str(val).replace("$", "").replace(",", "").replace("+", ""))
            return "color:#14835f" if parsed > 0 else "color:#c45d48"
        except Exception:
            return ""

    try:
        styled = table.style.map(color_result, subset=["Result"]).map(color_pnl, subset=["Net P&L"])
    except AttributeError:
        styled = table.style.applymap(color_result, subset=["Result"]).applymap(color_pnl, subset=["Net P&L"])
    st.dataframe(styled, width="stretch", height=360)


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
    colors = ["#14835f" if v > 0 else "#c45d48" for v in daily["pnl"]]
    fig = go.Figure(
        go.Bar(
            x=daily["date"],
            y=daily["pnl"],
            marker=dict(color=colors, line=dict(color="rgba(255,255,255,0.7)", width=1)),
            hovertemplate="<b>%{x}</b><br>P&L %{y:$+,.2f}<extra></extra>",
        )
    )
    fig.update_layout(
        height=280,
        margin=dict(l=8, r=8, t=8, b=8),
        paper_bgcolor="rgba(255,255,255,0.0)",
        plot_bgcolor="rgba(255,255,255,0.0)",
        xaxis=dict(showgrid=False, color="#5d6778"),
        yaxis=dict(showgrid=True, gridcolor="rgba(23,30,47,0.08)", tickprefix="$", color="#5d6778"),
        font=dict(color="#171d2c", family="DM Sans, sans-serif"),
    )
    st.plotly_chart(fig, width="stretch")


def render_asset(snapshot, asset_key):
    cfg = snapshot["cfg"]
    st.markdown(
        f"""
<div class="asset-shell">
  <div class="asset-header">
    <div>
      <div class="asset-kicker">{cfg['label']}</div>
      <div class="asset-title">{cfg['name']}</div>
      <div class="asset-meta">{cfg['signal']}</div>
    </div>
    <div class="badge-row">
      <div class="soft-badge">{cfg['timeframe']}</div>
      <div class="soft-badge">{cfg['schedule']}</div>
      <div class="soft-badge">{cfg['params']}</div>
    </div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    card(c1, "Balance", format_money(snapshot["balance"]), "Live marked balance", tone_class(snapshot["total_pnl"]))
    card(c2, "Net P&L", format_signed_money(snapshot["total_pnl"]), "Versus starting capital", tone_class(snapshot["total_pnl"]))
    card(c3, "ROI", format_pct(snapshot["roi"]), "Portfolio return", tone_class(snapshot["roi"]))
    card(c4, "Trades", str(snapshot["n_trades"]), "Closed positions", "neutral")
    card(c5, "Win rate", f"{snapshot['win_rate']:.1f}%", f"{snapshot['wins']} wins / {snapshot['losses']} losses", tone_class(snapshot["win_rate"], 50))
    card(c6, "Status", "Active" if snapshot["open_pos"] else "Monitoring", "Position manager state", "neutral")

    if snapshot["open_pos"]:
        render_position_banner(snapshot)

    left, right = st.columns([1.45, 1])
    with left:
        render_equity_curve(snapshot)
    with right:
        render_daily_pnl(snapshot)

    render_trade_table(snapshot)
    st.markdown('<div class="divider-space"></div>', unsafe_allow_html=True)


def render_sidebar():
    cfg = ASSETS["GC=F"]
    with st.sidebar:
        st.markdown("## Strategy Notes")
        st.markdown(
            f"""
**{cfg['label']} — {cfg['name']}**
Timeframe: {cfg['timeframe']}
Schedule: {cfg['schedule']}
Signal: {cfg['signal']}
Parameters: `{cfg['params']}`
"""
        )
        st.markdown("---")
        st.markdown("**Filters active**")
        st.markdown(
            "- ATR regime 0.85–1.2× (no low/spike vol)\n"
            "- Skip body 0.3–0.7× ATR (weak confirm)\n"
            "- Block hours 7,10,11,12,15,19 UTC\n"
            "- 72H crash filter: no LONG if 72H drop > 1.5%"
        )
        st.markdown("---")

        # ── Alpaca live execution status ──────────────────────────────
        st.markdown("**Alpaca Live Execution**")
        alpaca_state_path = DATA_DIR / "alpaca_state.json"
        alpaca_trades_path = DATA_DIR / "alpaca_trades.csv"
        if alpaca_state_path.exists():
            try:
                with open(alpaca_state_path) as _f:
                    _as = json.load(_f)
                _mode   = _as.get("mode", "?").upper()
                _bal    = _as.get("balance", 0)
                _trades = _as.get("total_trades", 0)
                _pnl    = _as.get("total_pnl", 0)
                _pos    = _as.get("position")
                _pos_str = (f"{_pos['dir']} {_pos.get('qty','')} shares "
                            f"@ ${_pos.get('entry',0):.2f}" if _pos else "Flat")
                st.markdown(
                    f"Mode: `{_mode}` | Capital: `${_as.get('capital',0):,.0f}`\n\n"
                    f"Balance: `${_bal:,.2f}` | P&L: `${_pnl:+,.2f}`\n\n"
                    f"Trades: `{_trades}` | Position: `{_pos_str}`"
                )
            except Exception:
                st.markdown("_Alpaca state unreadable_")
        else:
            st.markdown("_No Alpaca trades yet — waiting for market open_")

        live_price = _fetch_live_gld_price()
        if live_price:
            st.markdown(f"GLD live price: **${live_price:,.2f}**")

        st.markdown("---")
        st.markdown(f"**Last refresh**  \n{datetime.now().strftime('%H:%M:%S')}")
        if st.button("Refresh now", use_container_width=False):
            st.rerun()
        st.markdown("Auto-refresh every 60 seconds.")
        st.markdown('<meta http-equiv="refresh" content="60">', unsafe_allow_html=True)


def render_zone_levels():
    """Live nearest zone levels panel — fetches fresh GC=F data each render."""
    st.markdown('<div class="panel-title">Nearest Entry Zones — GC=F Live</div>', unsafe_allow_html=True)
    try:
        import yfinance as yf
        import numpy as np
        from zone_refinement_backtest import detect_zones, _clean

        FILTER_ATR_LOW=0.85; FILTER_ATR_HIGH=1.20
        FILTER_BODY_LOW=0.30; FILTER_BODY_HIGH=0.70
        FILTER_BAD_HOURS={7,10,11,12,15,19}
        FILTER_TREND_PCT=-0.015; FILTER_TREND_BARS=72

        end  = pd.Timestamp.now()
        start= end - pd.DateOffset(months=6)
        df1h = _clean(yf.download("GC=F", start=start.strftime("%Y-%m-%d"),
                                   end=end.strftime("%Y-%m-%d"),
                                   interval="1h", progress=False))
        if df1h.empty:
            st.info("Waiting for GC=F data…")
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

        # Current conditions summary
        bos_str   = "Bullish" if bull else ("Bearish" if bear else "Neutral")
        atr_ok    = FILTER_ATR_LOW <= f_ratio <= FILTER_ATR_HIGH
        hour_ok   = dt.hour not in FILTER_BAD_HOURS
        crash_ok  = t72p >= FILTER_TREND_PCT

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("GC=F Price", f"${price:,.1f}")
        c2.metric("BOS", bos_str, delta=None)
        c3.metric("ATR Regime", f"{f_ratio:.2f}x", delta="OK" if atr_ok else "BLOCKED")
        c4.metric("72H Trend", f"{t72p*100:+.1f}%", delta="OK" if crash_ok else "BLOCKED")
        c5.metric("Hour UTC", str(dt.hour), delta="OK" if hour_ok else "BLOCKED")

        st.markdown(f"*Last bar: {str(ts)[:16]} UTC  |  Active zones: {len(active)}*")
        st.markdown("---")

        # Build zone table
        rows = []
        for z in sorted(active, key=lambda z: abs(price - (z["htf_top"]+z["htf_bottom"])/2))[:10]:
            mid  = (z["htf_top"] + z["htf_bottom"]) / 2
            dist = price - mid
            inside = z["htf_bottom"] <= price <= z["htf_top"]
            loc    = "◀ INSIDE" if inside else ("▲ above" if price > z["htf_top"] else "▼ below")

            # Check if signal would fire
            blocks = []
            if z["type"] == "demand":
                if not bull:       blocks.append("BOS↓")
                if trend20 < 0:    blocks.append("trend20-")
                if t72p < FILTER_TREND_PCT: blocks.append("crash")
            else:
                if not bear:       blocks.append("BOS↑")
                if trend20 > 0:    blocks.append("trend20+")
            if not atr_ok:         blocks.append(f"ATR {f_ratio:.2f}")
            if dt.hour in FILTER_BAD_HOURS: blocks.append(f"hr{dt.hour}")
            signed = f_body if (z["type"]=="demand" and f_bull) or (z["type"]=="supply" and not f_bull) else -f_body
            if FILTER_BODY_LOW <= signed < FILTER_BODY_HIGH: blocks.append(f"body")

            if inside and not blocks:
                signal = "SIGNAL READY"
            elif inside:
                signal = "Blocked: " + " | ".join(blocks)
            else:
                signal = "—"

            rows.append({
                "Type":    z["type"].upper(),
                "HTF Zone":f"${z['htf_bottom']:,.0f} – ${z['htf_top']:,.0f}",
                "Entry (refined)": f"${z['refined_bottom']:,.1f} – ${z['refined_top']:,.1f}",
                "Dist $":  f"{dist:+,.1f}",
                "Location":loc,
                "Signal":  signal,
            })

        df_zones = pd.DataFrame(rows)

        def color_rows(row):
            base = "background-color:#1a2e1a;color:#14835f" if row["Type"] == "DEMAND" \
                   else "background-color:#2e1a1a;color:#c45d48"
            styles = [base] * len(row)
            if "SIGNAL READY" in row["Signal"]:
                styles[-1] = "background-color:#14835f;color:#fff;font-weight:700"
            elif "Blocked" in row["Signal"]:
                styles[-1] = "color:#888"
            return styles

        styled = df_zones.style.apply(color_rows, axis=1)
        st.dataframe(styled, width="stretch", height=380)

    except Exception as e:
        st.warning(f"Zone data unavailable: {e}")


# ── Main render ──────────────────────────────────────────────────────────────
snapshot = build_snapshot("GC=F")
render_hero(snapshot)
st.markdown('<div class="divider-space"></div>', unsafe_allow_html=True)
render_zone_levels()
st.markdown('<div class="divider-space"></div>', unsafe_allow_html=True)
render_asset(snapshot, "GC=F")
render_sidebar()
