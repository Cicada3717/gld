"""
zone_live_alpaca.py  —  Zone Refinement LIVE Trader via Alpaca API
===================================================================
Signal  : GLD 1H bars via Alpaca data API  (real-time, zero delay)
Execution: GLD ETF orders via Alpaca broker API

Why Alpaca data instead of yfinance?
  yfinance free tier is 15-min delayed.  When the bot detects a zone touch
  at price $280 (delayed), the real market is already at $285 — entry,
  stop, and R:R are all wrong before the trade even starts.
  Alpaca's IEX data feed is real-time and free with any Alpaca account.

Setup
-----
1.  pip install alpaca-py
2.  Set env vars (or edit the CONFIG block below):
      ALPACA_API_KEY     = "PKxxxxxxxx"
      ALPACA_SECRET_KEY  = "xxxxxxxx"
      ALPACA_PAPER       = "true"      # → "false" for real money
      ALPACA_CAPITAL     = "1000"      # starting capital in USD
      ALPACA_ALLOW_SHORT = "false"     # "true" only if you have a margin account

Usage
-----
  python zone_live_alpaca.py
  python zone_live_alpaca.py --capital 1000 --paper
"""

import argparse
import csv
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    StopLossRequest,
    TakeProfitRequest,
    GetOrdersRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestTradeRequest
from alpaca.data.timeframe import TimeFrame

from zone_refinement_backtest import detect_zones, _clean

# ── CONFIG ────────────────────────────────────────────────────────────────────
# Edit these OR set environment variables (env vars take priority)

ALPACA_API_KEY    = os.environ.get("ALPACA_API_KEY",     "YOUR_KEY_HERE")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY",  "YOUR_SECRET_HERE")
PAPER             = os.environ.get("ALPACA_PAPER",       "true").lower() == "true"
CAPITAL           = float(os.environ.get("ALPACA_CAPITAL",      "1000"))
ALLOW_SHORT       = os.environ.get("ALPACA_ALLOW_SHORT", "false").lower() == "true"

# Single ticker: signal detection AND execution both on GLD via Alpaca (real-time)
TRADE_TICKER  = "GLD"

ET = ZoneInfo("America/New_York")

# ── STRATEGY PARAMS (matches backtest exactly) ────────────────────────────────
PARAMS = {
    "strength_bars":      3,
    "strength_mult":      1.5,
    "bos_ema":            21,
    "bos_slope_bars":     8,
    "stop_buffer":        0.001,
    "target_lookback":    60,
    "target_skip":        5,
    "min_rr":             2.5,
    "risk_pct":           0.02,       # 2% of capital per trade
    "trail_activation_r": 2.5,
    "trail_distance_r":   0.2,
    "max_trades_day":     2,
    "commission":         0.0,        # Alpaca is commission-free
}

# ── ENTRY FILTERS ─────────────────────────────────────────────────────────────
FILTER_ATR_LOW    = 0.80
FILTER_ATR_HIGH   = 1.20
FILTER_BODY_LOW   = 0.30
FILTER_BODY_HIGH  = 0.70
FILTER_BAD_HOURS  = {10, 11, 12, 15, 19}   # UTC hours with negative EV
FILTER_TREND_BARS = 72
FILTER_TREND_PCT  = -0.015   # block LONG only when 72H drop > 1.5% (crash mode)

# ── PATHS ─────────────────────────────────────────────────────────────────────
DATA_DIR   = Path(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", Path(__file__).parent))
TRADE_LOG  = DATA_DIR / "alpaca_trades.csv"
STATE_FILE = DATA_DIR / "alpaca_state.json"

# ─────────────────────────────────────────────────────────────────────────────
#  INDICATORS  (identical to zone_paper_trader.py)
# ─────────────────────────────────────────────────────────────────────────────

def _ema_series(values, period):
    out = [float("nan")] * len(values)
    if len(values) < period:
        return out
    k = 2 / (period + 1)
    e = float(np.mean(values[:period]))
    out[period - 1] = e
    for i in range(period, len(values)):
        e = values[i] * k + e * (1 - k)
        out[i] = e
    return out


def _bos_bullish(closes, period, slope_bars):
    ev = _ema_series(closes, period)
    valid = [v for v in ev if v == v]
    return len(valid) > slope_bars and valid[-1] > valid[-1 - slope_bars]


def _bos_bearish(closes, period, slope_bars):
    ev = _ema_series(closes, period)
    valid = [v for v in ev if v == v]
    return len(valid) > slope_bars and valid[-1] < valid[-1 - slope_bars]


def _prior_high(highs, skip, lookback):
    n = min(lookback, len(highs))
    s = max(0, len(highs) - n)
    e = max(0, len(highs) - skip)
    return max(highs[s:e]) if s < e and highs[s:e] else (max(highs[s:]) if highs[s:] else 0)


def _prior_low(lows, skip, lookback):
    n = min(lookback, len(lows))
    s = max(0, len(lows) - n)
    e = max(0, len(lows) - skip)
    return min(lows[s:e]) if s < e and lows[s:e] else (min(lows[s:]) if lows[s:] else 9e9)


def _atr14(highs, lows, closes, period=14):
    h = np.array(highs[-period - 2:])
    l = np.array(lows[-period - 2:])
    c = np.array(closes[-period - 2:])
    if len(h) < 2:
        return 1.0
    tr = np.maximum(h[1:] - l[1:],
                    np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    return float(np.mean(tr[-period:])) if len(tr) >= period else float(np.mean(tr))


# ─────────────────────────────────────────────────────────────────────────────
#  DATA  —  Alpaca real-time bars (replaces yfinance entirely for live feed)
# ─────────────────────────────────────────────────────────────────────────────

def _data_client():
    """Alpaca market-data client (free IEX feed — real-time US stocks)."""
    return StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)


def fetch_gld_bars(months=6):
    """
    Fetch GLD 1H bars from Alpaca data API — real-time, no 15-min delay.
    Returns a clean DataFrame with columns Open/High/Low/Close/Volume
    and a UTC DatetimeIndex, ready for zone detection.
    """
    start = pd.Timestamp.now(tz="UTC") - pd.DateOffset(months=months)
    req   = StockBarsRequest(
        symbol_or_symbols=TRADE_TICKER,
        timeframe=TimeFrame.Hour,
        start=start,
        feed="iex",           # free real-time feed included with all Alpaca accounts
    )
    bars = _data_client().get_stock_bars(req)
    df   = bars.df

    # Alpaca returns MultiIndex (symbol, timestamp) — drop symbol level
    if isinstance(df.index, pd.MultiIndex):
        df = df.loc[TRADE_TICKER]

    df = df.rename(columns={"open": "Open", "high": "High",
                             "low":  "Low",  "close": "Close", "volume": "Volume"})
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    df.index = pd.to_datetime(df.index, utc=True)
    return df


def build_zones(df_1h):
    df_4h = (df_1h.resample("4h")
             .agg({"Open": "first", "High": "max", "Low": "min",
                   "Close": "last", "Volume": "sum"})
             .dropna())
    return detect_zones(df_4h, df_1h,
                        strength_bars=PARAMS["strength_bars"],
                        strength_mult=PARAMS["strength_mult"])


def get_realtime_price():
    """Current GLD trade price from Alpaca (millisecond-fresh)."""
    try:
        req   = StockLatestTradeRequest(symbol_or_symbols=TRADE_TICKER)
        trade = _data_client().get_stock_latest_trade(req)
        return float(trade[TRADE_TICKER].price)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
#  POSITION SIZING
# ─────────────────────────────────────────────────────────────────────────────

def calc_qty(balance, price, risk_per_share):
    """
    How many GLD shares to buy.
    risk_per_share = entry_price - stop_price (dollars per share)
    Caps at: balance * risk_pct / risk_per_share  AND  balance / price (no leverage for cash)
    Returns float for fractional shares (Alpaca supports it).
    """
    if risk_per_share <= 0 or price <= 0:
        return 0.0
    dollar_risk  = balance * PARAMS["risk_pct"]     # e.g. $1000 * 2% = $20
    risk_shares  = dollar_risk / risk_per_share      # e.g. $20 / $4 = 5 shares
    max_shares   = balance / price                   # cash cap (no leverage)
    qty = min(risk_shares, max_shares)
    return round(qty, 4)                              # Alpaca accepts fractional


# ─────────────────────────────────────────────────────────────────────────────
#  PERSISTENCE
# ─────────────────────────────────────────────────────────────────────────────

def _zones_to_json(zones):
    out = []
    for z in zones:
        zc = dict(z)
        if hasattr(zc.get("formed_at"), "isoformat"):
            zc["formed_at"] = zc["formed_at"].isoformat()
        out.append(zc)
    return out


def _zones_from_json(lst):
    zones = []
    for z in lst:
        zc = dict(z)
        if isinstance(zc.get("formed_at"), str):
            zc["formed_at"] = datetime.fromisoformat(zc["formed_at"])
        zones.append(zc)
    return zones


def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            s = json.load(f)
        if "zones" in s:
            s["zones"] = _zones_from_json(s["zones"])
        return s
    return None


def save_state(state):
    s = dict(state)
    if "zones" in s:
        s["zones"] = _zones_to_json(s["zones"])
    with open(STATE_FILE, "w") as f:
        json.dump(s, f, indent=2, default=str)


def log_trade(row):
    exists = TRADE_LOG.exists()
    with open(TRADE_LOG, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "date", "time", "action", "dir", "qty", "price",
            "stop", "target", "alpaca_order_id", "reason", "pnl", "balance"
        ])
        if not exists:
            w.writeheader()
        w.writerow(row)


# ─────────────────────────────────────────────────────────────────────────────
#  ALPACA ORDER HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def submit_bracket(client, side, qty, stop_price, target_price):
    """
    Submit a market bracket order: entry + stop loss + take profit.
    Returns the Alpaca order object.
    """
    order_data = MarketOrderRequest(
        symbol=TRADE_TICKER,
        qty=qty,
        side=OrderSide.BUY if side == "LONG" else OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
        order_class=OrderClass.BRACKET,
        stop_loss=StopLossRequest(stop_price=round(stop_price, 2)),
        take_profit=TakeProfitRequest(limit_price=round(target_price, 2)),
    )
    order = client.submit_order(order_data)
    print(f"  [ALPACA] {side} bracket submitted | qty={qty} stop=${stop_price:.2f} target=${target_price:.2f}")
    print(f"  [ALPACA] Order ID: {order.id}")
    return order


def cancel_all_for_symbol(client):
    """Cancel all open orders for TRADE_TICKER."""
    try:
        open_orders = client.get_orders(
            GetOrdersRequest(status=QueryOrderStatus.OPEN, symbol=TRADE_TICKER)
        )
        for o in open_orders:
            client.cancel_order_by_id(str(o.id))
            print(f"  [ALPACA] Cancelled order {o.id}")
    except Exception as e:
        print(f"  [ALPACA] Cancel error: {e}")


def get_open_position(client):
    """Return Alpaca position for TRADE_TICKER, or None."""
    try:
        pos = client.get_open_position(TRADE_TICKER)
        return pos
    except Exception:
        return None


def close_position_market(client):
    """Market-close the entire TRADE_TICKER position."""
    try:
        cancel_all_for_symbol(client)
        time.sleep(1)
        client.close_position(TRADE_TICKER)
        print(f"  [ALPACA] Position closed at market")
    except Exception as e:
        print(f"  [ALPACA] Close error: {e}")


def update_stop_order(client, stop_order_id, new_stop_price):
    """Replace the stop leg with a new stop price."""
    try:
        from alpaca.trading.requests import ReplaceOrderRequest
        client.replace_order_by_id(
            stop_order_id,
            ReplaceOrderRequest(stop_price=round(new_stop_price, 2)),
        )
        print(f"  [ALPACA] Stop updated to ${new_stop_price:.2f}")
    except Exception as e:
        print(f"  [ALPACA] Stop update error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
#  MARKET HOURS CHECK
# ─────────────────────────────────────────────────────────────────────────────

def market_is_open(client):
    """True if NYSE is open right now (Alpaca clock)."""
    try:
        clock = client.get_clock()
        return clock.is_open
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN LOOP
# ─────────────────────────────────────────────────────────────────────────────

def run(capital=CAPITAL, paper=PAPER):
    mode = "PAPER" if paper else "*** LIVE REAL MONEY ***"
    print(f"\n{'='*70}")
    print(f"  Zone Live Trader  |  Alpaca  |  {mode}")
    print(f"  Signal: {SIGNAL_TICKER} (GC=F gold futures data)")
    print(f"  Trade : {TRADE_TICKER} ETF  |  Capital: ${capital:,.0f}")
    print(f"  Risk/trade: {PARAMS['risk_pct']*100:.0f}%  |  Shorts: {'enabled' if ALLOW_SHORT else 'disabled (cash acct)'}")
    print(f"  Log: {TRADE_LOG}")
    print(f"{'='*70}\n")

    if not paper and "YOUR_KEY" in ALPACA_API_KEY:
        print("  ERROR: Set ALPACA_API_KEY and ALPACA_SECRET_KEY before going live!")
        return

    # Connect to Alpaca
    client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=paper)
    try:
        acct = client.get_account()
        buying_power = float(acct.buying_power)
        portfolio_val = float(acct.portfolio_value)
        print(f"  Alpaca account connected")
        print(f"  Portfolio value : ${portfolio_val:,.2f}")
        print(f"  Buying power    : ${buying_power:,.2f}")
        if not paper:
            print(f"\n  *** LIVE MODE — real orders will be placed ***")
            print(f"  You have 10 seconds to Ctrl+C if this is unintentional...")
            time.sleep(10)
    except Exception as e:
        print(f"  ERROR connecting to Alpaca: {e}")
        print(f"  Check your API keys and paper/live setting.")
        return

    # Load or init state
    state = load_state()
    if state and state.get("mode") == ("paper" if paper else "live"):
        print(f"  Resuming state | Trades: {state.get('total_trades', 0)} | P&L: ${state.get('total_pnl', 0):+,.2f}")
        if "zones" not in state:
            state["zones"] = []
        state.setdefault("last_processed_bar", None)
        state.setdefault("trades_today_date", None)
        state.setdefault("trades_today_count", 0)
        state.setdefault("open_order_id", None)
        state.setdefault("stop_order_id", None)
        state.setdefault("trail_activated", False)
    else:
        state = {
            "mode":               "paper" if paper else "live",
            "capital":            capital,
            "balance":            capital,        # tracked locally (mirror of Alpaca)
            "position":           None,           # our position metadata
            "open_order_id":      None,           # Alpaca bracket order ID
            "stop_order_id":      None,           # Alpaca stop leg ID (for trailing)
            "trail_activated":    False,
            "zones":              [],
            "zones_date":         None,
            "last_processed_bar": None,
            "trades_today_date":  None,
            "trades_today_count": 0,
            "total_trades":       0,
            "total_pnl":          0.0,
            "wins":               0,
            "losses":             0,
        }
        save_state(state)
        print(f"  Starting fresh | ${capital:,.0f}")

    print()

    while True:
        try:
            now      = datetime.now(ET)
            date_str = now.strftime("%Y-%m-%d")

            # ── Check if market is open ───────────────────────────────
            if not market_is_open(client):
                print(f"  [{now.strftime('%H:%M ET')}] Market closed — sleeping 5 min")
                time.sleep(300)
                continue

            # ── Refresh zones once per day ────────────────────────────
            if state["zones_date"] != date_str:
                print(f"  [{now.strftime('%H:%M')}] Refreshing zones (GLD Alpaca bars, 6 months 1H)...")
                df_1h = fetch_gld_bars(months=6)
                if df_1h.empty:
                    print("  No data — retry in 60s")
                    time.sleep(60)
                    continue

                # Preserve consumed zones < 7 days old
                old_consumed = {}
                for z in state.get("zones", []):
                    if not z.get("consumed"):
                        continue
                    cd = z.get("consumed_date")
                    if cd:
                        age = (datetime.now(ET).date() -
                               datetime.fromisoformat(str(cd)).date()).days
                        if age > 7:
                            continue
                    key = (z["type"], round(z["htf_top"], 3), round(z["htf_bottom"], 3))
                    old_consumed[key] = cd

                new_zones = build_zones(df_1h)
                for z in new_zones:
                    key = (z["type"], round(z["htf_top"], 3), round(z["htf_bottom"], 3))
                    z["consumed"]      = key in old_consumed
                    z["consumed_date"] = old_consumed.get(key)

                state["zones"]      = new_zones
                state["zones_date"] = date_str
                d = sum(1 for z in new_zones if z["type"] == "demand")
                s = sum(1 for z in new_zones if z["type"] == "supply")
                print(f"  Zones loaded: {len(new_zones)} ({d} demand, {s} supply)")
                save_state(state)

            # ── Fetch latest GLD 1H bars — real-time via Alpaca ──────
            df_1h = fetch_gld_bars(months=2)
            if df_1h.empty:
                time.sleep(60)
                continue

            # ── Sync position with Alpaca reality ─────────────────────
            alpaca_pos = get_open_position(client)

            # If we think we have a position but Alpaca shows none → it closed
            if state["position"] and not alpaca_pos:
                pos = state["position"]
                print(f"\n  *** {pos['dir']} position closed by Alpaca (stop or target hit) ***")
                # Best-effort P&L from Alpaca account
                try:
                    acct2 = client.get_account()
                    new_equity = float(acct2.portfolio_value)
                    pnl_est = new_equity - state["balance"]
                    state["balance"]      = new_equity
                    state["total_pnl"]   += pnl_est
                    state["total_trades"] += 1
                    if pnl_est > 0:
                        state["wins"] += 1
                    else:
                        state["losses"] += 1
                    print(f"  Equity: ${new_equity:,.2f}  Est P&L: ${pnl_est:+.2f}")
                    log_trade({
                        "date": date_str, "time": now.strftime("%H:%M"),
                        "action": "CLOSED_BY_ALPACA", "dir": pos["dir"],
                        "qty": pos["qty"], "price": "", "stop": pos["stop"],
                        "target": pos["target"], "alpaca_order_id": state.get("open_order_id", ""),
                        "reason": "STOP_OR_TARGET", "pnl": round(pnl_est, 2),
                        "balance": round(new_equity, 2),
                    })
                except Exception as ex:
                    print(f"  P&L sync error: {ex}")

                state["position"]      = None
                state["open_order_id"] = None
                state["stop_order_id"] = None
                state["trail_activated"] = False
                save_state(state)

            latest_close = float(df_1h["Close"].iloc[-1])
            print(f"  [{now.strftime('%H:%M ET')}] GLD ${latest_close:.2f}  "
                  f"{'[IN POSITION]' if state['position'] else '[FLAT]'}")

            last_raw = state.get("last_processed_bar")
            last_bar = pd.Timestamp(last_raw) if last_raw else df_1h.index[-2]
            pending  = df_1h.index[df_1h.index > last_bar]

            if len(pending) == 0:
                time.sleep(120)
                continue

            for current_ts in pending:
                hist   = df_1h.loc[:current_ts]
                if len(hist) < 50:
                    continue

                closes = hist["Close"].tolist()
                highs  = hist["High"].tolist()
                lows   = hist["Low"].tolist()
                price  = float(hist["Close"].iloc[-1])
                high   = float(hist["High"].iloc[-1])
                low    = float(hist["Low"].iloc[-1])
                ts     = pd.Timestamp(current_ts).to_pydatetime()
                bdate  = pd.Timestamp(current_ts).strftime("%Y-%m-%d")
                btime  = pd.Timestamp(current_ts).strftime("%H:%M")

                if state.get("trades_today_date") != bdate:
                    state["trades_today_date"]  = bdate
                    state["trades_today_count"] = 0

                # ── Manage open position: trailing stop ───────────────
                if state["position"] and alpaca_pos:
                    pos = state["position"]
                    initial_risk   = pos.get("initial_risk", 1.0)
                    trail_activate = initial_risk * PARAMS["trail_activation_r"]
                    trail_dist     = initial_risk * PARAMS["trail_distance_r"]

                    if pos["dir"] == "LONG":
                        best = max(pos.get("best_price", pos["entry"]), high)
                        pos["best_price"] = best
                        if best >= pos["entry"] + trail_activate and not state["trail_activated"]:
                            new_stop = best - trail_dist
                            if new_stop > pos["stop"] and state.get("stop_order_id"):
                                print(f"  Trail activated: stop ${pos['stop']:.2f} -> ${new_stop:.2f}")
                                update_stop_order(client, state["stop_order_id"], new_stop)
                                pos["stop"] = new_stop
                                state["trail_activated"] = True
                                save_state(state)
                        elif state["trail_activated"] and best >= pos["entry"] + trail_activate:
                            new_stop = best - trail_dist
                            if new_stop > pos["stop"] + 0.01 and state.get("stop_order_id"):
                                update_stop_order(client, state["stop_order_id"], new_stop)
                                pos["stop"] = new_stop
                                save_state(state)
                    else:
                        best = min(pos.get("best_price", pos["entry"]), low)
                        pos["best_price"] = best
                        if best <= pos["entry"] - trail_activate and not state["trail_activated"]:
                            new_stop = best + trail_dist
                            if new_stop < pos["stop"] and state.get("stop_order_id"):
                                print(f"  Trail activated: stop ${pos['stop']:.2f} -> ${new_stop:.2f}")
                                update_stop_order(client, state["stop_order_id"], new_stop)
                                pos["stop"] = new_stop
                                state["trail_activated"] = True
                                save_state(state)

                    unreal = float(alpaca_pos.unrealized_pl) if alpaca_pos else 0
                    print(f"    {pos['dir']} {pos['qty']}sh | stop:${pos['stop']:.2f} "
                          f"{'(T)' if state['trail_activated'] else ''} | "
                          f"target:${pos['target']:.2f} | unreal:${unreal:+.2f}")

                # ── Zone scan for entry ───────────────────────────────
                if state["position"]:
                    state["last_processed_bar"] = str(current_ts)
                    save_state(state)
                    continue

                p = PARAMS
                if state.get("trades_today_count", 0) >= p["max_trades_day"]:
                    state["last_processed_bar"] = str(current_ts)
                    save_state(state)
                    continue

                bull = _bos_bullish(closes, p["bos_ema"], p["bos_slope_bars"])
                bear = _bos_bearish(closes, p["bos_ema"], p["bos_slope_bars"])
                trend_20 = closes[-1] - closes[-20] if len(closes) >= 20 else 0

                # Filter pre-compute
                n_bars = len(closes)
                trend_72h = (closes[-1] - closes[-FILTER_TREND_BARS]
                             if n_bars >= FILTER_TREND_BARS
                             else closes[-1] - closes[0])
                trend_72h_pct  = trend_72h / closes[-1] if closes[-1] > 0 else 0
                f_atr          = _atr14(highs, lows, closes)
                f_atr_avg      = _atr14(highs[-30:], lows[-30:], closes[-30:], 20) if len(closes) >= 22 else f_atr
                f_atr_ratio    = f_atr / f_atr_avg if f_atr_avg > 0 else 1.0
                f_body_raw     = float(hist["Close"].iloc[-1]) - float(hist["Open"].iloc[-1])
                f_body_pct     = abs(f_body_raw) / f_atr if f_atr > 0 else 0.0
                f_body_bull    = f_body_raw >= 0

                entered = False
                for zone in state["zones"]:
                    if zone.get("consumed"):
                        continue
                    formed = zone["formed_at"]
                    if not isinstance(formed, datetime):
                        formed = datetime.fromisoformat(str(formed))
                    if formed >= ts:
                        continue

                    ztop = zone["htf_top"]
                    zbot = zone["htf_bottom"]
                    rtop = zone["refined_top"]
                    rbot = zone["refined_bottom"]
                    buf  = p["stop_buffer"]

                    # ── LONG (demand zone) ────────────────────────────
                    if zone["type"] == "demand":
                        if not (zbot <= price <= ztop):       continue
                        if not bull:                           continue
                        if low > rtop:                         continue
                        if price < rbot:                       continue
                        if trend_20 < 0:                       continue

                        stop   = rbot * (1 - buf)
                        risk   = price - stop
                        if risk <= 0:                          continue

                        target = _prior_high(highs, p["target_skip"], p["target_lookback"])
                        if target <= price:
                            target = price + risk * p["min_rr"]
                        rr = (target - price) / risk
                        if rr < p["min_rr"]:                   continue

                        # ── Real-time price check (no ratio needed — zones in GLD space) ──
                        # Bar close (price) is the last CLOSED 1H candle.
                        # gld_now is the actual current market price from Alpaca (millisecond fresh).
                        # If price has drifted > 0.3% since bar close the signal is stale → skip.
                        gld_now = get_realtime_price()
                        if not gld_now:
                            print("  Could not fetch real-time GLD price — skipping entry")
                            break
                        drift = abs(gld_now - price) / price
                        if drift > 0.003:
                            print(f"    STALE: bar close ${price:.2f} vs live ${gld_now:.2f} "
                                  f"({drift*100:.2f}% drift) — skip")
                            zone["consumed"] = True; zone["consumed_date"] = bdate; break

                        qty = calc_qty(capital, gld_now, (gld_now - stop))
                        if qty < 0.01:
                            print(f"    Qty too small ({qty:.4f} shares) — skip")
                            continue

                        # ── Filters ───────────────────────────────────
                        signed_body = f_body_pct if f_body_bull else -f_body_pct
                        if ts.hour in FILTER_BAD_HOURS:
                            print(f"    FILTER: bad hour {ts.hour}:00 UTC — skip LONG")
                            zone["consumed"] = True; zone["consumed_date"] = bdate; break
                        if not (FILTER_ATR_LOW <= f_atr_ratio <= FILTER_ATR_HIGH):
                            print(f"    FILTER: ATR ratio {f_atr_ratio:.2f} outside range — skip")
                            zone["consumed"] = True; zone["consumed_date"] = bdate; break
                        if FILTER_BODY_LOW <= signed_body < FILTER_BODY_HIGH:
                            print(f"    FILTER: small-confirm body {signed_body:.2f} — skip")
                            zone["consumed"] = True; zone["consumed_date"] = bdate; break
                        if trend_72h_pct < FILTER_TREND_PCT:
                            print(f"    FILTER: 72H drop {trend_72h_pct*100:+.2f}% crash — skip LONG")
                            zone["consumed"] = True; zone["consumed_date"] = bdate; break
                        # ─────────────────────────────────────────────

                        print(f"\n  *** SIGNAL: LONG GLD @ ~${gld_now:.2f}  stop=${stop:.2f}  target=${target:.2f}  R:R={rr:.1f} ***")
                        order = submit_bracket(client, "LONG", qty, stop, target)

                        # Find the stop leg order ID from the bracket legs
                        stop_oid = None
                        try:
                            legs = client.get_order_by_id(str(order.id)).legs
                            for leg in (legs or []):
                                if leg.type.value in ("stop", "stop_limit"):
                                    stop_oid = str(leg.id)
                        except Exception:
                            pass

                        state["position"] = {
                            "dir":          "LONG",
                            "qty":          qty,
                            "entry":        gld_now,
                            "stop":         stop,
                            "target":       target,
                            "initial_risk": gld_now - stop,
                            "best_price":   gld_now,
                            "zone_type":    "demand",
                            "entry_time":   f"{bdate} {btime}",
                        }
                        state["open_order_id"]  = str(order.id)
                        state["stop_order_id"]  = stop_oid
                        state["trail_activated"] = False
                        state["trades_today_count"] = state.get("trades_today_count", 0) + 1
                        zone["consumed"] = True; zone["consumed_date"] = bdate
                        save_state(state)

                        log_trade({
                            "date": bdate, "time": btime, "action": "BUY",
                            "dir": "LONG", "qty": qty, "price": round(gld_px, 2),
                            "stop": round(gld_stop, 2), "target": round(gld_target, 2),
                            "alpaca_order_id": str(order.id),
                            "reason": "ZONE_DEMAND", "pnl": "", "balance": "",
                        })
                        entered = True
                        break

                    # ── SHORT (supply zone) ──────────────────────────────
                    elif zone["type"] == "supply" and ALLOW_SHORT:
                        if not (zbot <= price <= ztop):       continue
                        if not bear:                           continue
                        if high < rbot:                        continue
                        if price > rtop:                       continue
                        if trend_20 > 0:                       continue

                        stop   = rtop * (1 + buf)
                        risk   = stop - price
                        if risk <= 0:                          continue

                        target = _prior_low(lows, p["target_skip"], p["target_lookback"])
                        if target >= price:
                            target = price - risk * p["min_rr"]
                        rr = (price - target) / risk
                        if rr < p["min_rr"]:                   continue

                        # ── Real-time price check ──────────────────────
                        gld_now = get_realtime_price()
                        if not gld_now:
                            break
                        drift = abs(gld_now - price) / price
                        if drift > 0.003:
                            print(f"    STALE: bar close ${price:.2f} vs live ${gld_now:.2f} "
                                  f"({drift*100:.2f}% drift) — skip")
                            zone["consumed"] = True; zone["consumed_date"] = bdate; break

                        qty = calc_qty(capital, gld_now, (stop - gld_now))
                        if qty < 0.01:
                            continue

                        # ── Filters ───────────────────────────────────
                        signed_body = f_body_pct if not f_body_bull else -f_body_pct
                        if ts.hour in FILTER_BAD_HOURS:
                            print(f"    FILTER: bad hour {ts.hour}:00 UTC — skip SHORT")
                            zone["consumed"] = True; zone["consumed_date"] = bdate; break
                        if not (FILTER_ATR_LOW <= f_atr_ratio <= FILTER_ATR_HIGH):
                            print(f"    FILTER: ATR ratio {f_atr_ratio:.2f} outside range — skip")
                            zone["consumed"] = True; zone["consumed_date"] = bdate; break
                        if FILTER_BODY_LOW <= signed_body < FILTER_BODY_HIGH:
                            print(f"    FILTER: small-confirm body {signed_body:.2f} — skip")
                            zone["consumed"] = True; zone["consumed_date"] = bdate; break
                        # (no 72H crash filter on SHORTs — crashes are good for shorts)
                        # ─────────────────────────────────────────────

                        print(f"\n  *** SIGNAL: SHORT GLD @ ~${gld_now:.2f}  stop=${stop:.2f}  target=${target:.2f}  R:R={rr:.1f} ***")
                        order = submit_bracket(client, "SHORT", qty, stop, target)

                        stop_oid = None
                        try:
                            legs = client.get_order_by_id(str(order.id)).legs
                            for leg in (legs or []):
                                if leg.type.value in ("stop", "stop_limit"):
                                    stop_oid = str(leg.id)
                        except Exception:
                            pass

                        state["position"] = {
                            "dir":          "SHORT",
                            "qty":          qty,
                            "entry":        gld_now,
                            "stop":         stop,
                            "target":       target,
                            "initial_risk": stop - gld_now,
                            "best_price":   gld_now,
                            "zone_type":    "supply",
                            "entry_time":   f"{bdate} {btime}",
                        }
                        state["open_order_id"]  = str(order.id)
                        state["stop_order_id"]  = stop_oid
                        state["trail_activated"] = False
                        state["trades_today_count"] = state.get("trades_today_count", 0) + 1
                        zone["consumed"] = True; zone["consumed_date"] = bdate
                        save_state(state)

                        log_trade({
                            "date": bdate, "time": btime, "action": "SELL",
                            "dir": "SHORT", "qty": qty, "price": round(gld_px, 2),
                            "stop": round(gld_stop, 2), "target": round(gld_target, 2),
                            "alpaca_order_id": str(order.id),
                            "reason": "ZONE_SUPPLY",  "pnl": "", "balance": "",
                        })
                        entered = True
                        break

                if not entered and not state["position"]:
                    print(f"    Flat — no zone signal")

                state["last_processed_bar"] = str(current_ts)
                save_state(state)

            time.sleep(120)   # poll every 2 minutes

        except KeyboardInterrupt:
            print(f"\n  Stopping...")
            pos = state.get("position")
            if pos:
                print(f"  WARNING: Open position {pos['dir']} {pos['qty']} GLD "
                      f"— NOT auto-closed. Manage manually in Alpaca dashboard.")
            break
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback; traceback.print_exc()
            time.sleep(60)


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, default=CAPITAL)
    ap.add_argument("--paper",   action="store_true", default=PAPER)
    ap.add_argument("--live",    action="store_true", help="Disable paper mode (real money)")
    args = ap.parse_args()

    go_live = args.live
    run(capital=args.capital, paper=not go_live)
