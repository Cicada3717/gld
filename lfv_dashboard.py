"""
lfv_dashboard.py - Premium live dashboard for GC=F and BTC-USD.
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
        "label": "GC=F",
        "name": "Gold Futures",
        "state": DATA_DIR / "zone_state.json",
        "trades": DATA_DIR / "zone_trades.csv",
        "timeframe": "1H bars",
        "schedule": "Sun 18:00 ET to Fri 17:00 ET",
        "signal": "Supply and Demand zone refinement",
        "params": "min_rr=2.5  trail_act=1.5R  trail_dist=0.3R  slope=5",
        "accent": "#a47a1f",
        "title": "Zone Strategy",
    },
    "BTC-USD": {
        "label": "BTC-USD",
        "name": "Bitcoin",
        "state": DATA_DIR / "lfv_state_BTCUSD.json",
        "trades": DATA_DIR / "lfv_trades_BTCUSD.csv",
        "timeframe": "5-minute bars",
        "schedule": "24/7 continuous scan",
        "signal": "Liquidity sweep, AVWAP and volume profile",
        "params": "swing_n=8  sweep_atr=0.25  min_rr=3.0  be=1.5R  trail=2.5R/0.5ATR",
        "accent": "#b46a3a",
        "title": "LFV Strategy",
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
    for col in ["pnl", "balance", "price", "shares", "stop"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
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
        "open_pos": state.get("position"),
    }


def render_hero(snapshot):
    cfg = snapshot["cfg"]
    open_pos = snapshot["open_pos"]
    open_status = "Open trade" if open_pos else "No open trade"
    open_sub = (
        f"{open_pos.get('dir', '?')} {format_units(open_pos.get('shares'))} units at ${open_pos.get('entry', 0):,.3f}"
        if open_pos
        else "Watching for the next signal"
    )
    st.markdown(
        f"""
<div class="hero-shell">
  <div class="eyebrow">Live paper trading</div>
  <div class="hero-grid">
      <div>
        <div class="hero-title">{cfg['title']}</div>
        <p class="hero-copy">Updated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
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
    open_pos = snapshot["open_pos"]
    if snapshot["cfg"]["label"] == "BTC-USD":
        phase_names = {1: "Hard stop", 2: "Breakeven", 3: "Trailing"}
        phase_str = phase_names.get(open_pos.get("phase", 1), "?")
        copy = (
            f"{open_pos.get('dir', '?')} {format_units(open_pos.get('shares'))} units at ${open_pos.get('entry', 0):,.3f} "
            f"with stop ${open_pos.get('stop', 0):,.3f} in {phase_str} mode.<br>"
            f"Entered {open_pos.get('entry_time', '?')} | Swept {open_pos.get('swept_lvl', 0):,.3f} "
            f"| AVWAP {open_pos.get('avwap', 0):,.3f} | POC {open_pos.get('poc', 0):,.3f}"
        )
    else:
        copy = (
            f"{open_pos.get('dir', '?')} {format_units(open_pos.get('shares'))} contracts at ${open_pos.get('entry', 0):,.3f} "
            f"with stop ${open_pos.get('stop', 0):,.3f} and target ${open_pos.get('target', 0):,.3f}.<br>"
            f"Entered {open_pos.get('entry_time', '?')} | Zone {open_pos.get('zone_type', '?')} "
            f"| Trigger ${open_pos.get('entry_trigger', open_pos.get('entry', 0)):.3f}"
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
    st.plotly_chart(fig, use_container_width=True)


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
    st.dataframe(styled, use_container_width=True, height=360)


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
    st.plotly_chart(fig, use_container_width=True)


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
    if asset_key == "GC=F":
        st.markdown('<div class="divider-space"></div>', unsafe_allow_html=True)


def render_sidebar():
    with st.sidebar:
        st.markdown("## Strategy Notes")
        for cfg in ASSETS.values():
            st.markdown(
                f"""
**{cfg['label']} - {cfg['name']}**  
Timeframe: {cfg['timeframe']}  
Schedule: {cfg['schedule']}  
Signal: {cfg['signal']}  
Parameters: {cfg['params']}
"""
            )
            st.markdown("---")

        st.markdown(f"**Last refresh**  \n{datetime.now().strftime('%H:%M:%S')}")
        if st.button("Refresh now", use_container_width=True):
            st.rerun()
        st.markdown("Auto-refresh every 60 seconds.")
        st.markdown('<meta http-equiv="refresh" content="60">', unsafe_allow_html=True)


selected_view = st.radio(
    "Asset View",
    options=["GC=F", "BTC-USD"],
    horizontal=True,
    index=0,
    label_visibility="collapsed",
)

snapshot = build_snapshot(selected_view)

render_hero(snapshot)
st.markdown('<div class="divider-space"></div>', unsafe_allow_html=True)
render_asset(snapshot, selected_view)

render_sidebar()
