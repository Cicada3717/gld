"""
zone_paper_trader.py — Zone Refinement Live Paper Trader (GLD, 1H bars)
=======================================================================
Watches GLD 1H bars in real-time during market hours.
Detects 4H supply/demand zones at startup; re-scans once per day.
Enters on refined-zone touches, manages stop/target each hour.
Logs to zone_trades.csv / zone_state.json (identical format to paper_trades.csv).

Usage:
  python zone_paper_trader.py              # default $500 capital
  python zone_paper_trader.py --capital 1000
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
import yfinance as yf

from zone_refinement_backtest import detect_zones, _clean

ET = ZoneInfo("America/New_York")

PARAMS = {
    "strength_bars":   3,
    "strength_mult":   1.5,
    "bos_ema":         21,
    "bos_slope_bars":  3,
    "stop_buffer":     0.001,
    "target_lookback": 60,
    "target_skip":     5,
    "min_rr":          3.0,
    "risk_pct":        0.02,
    "leverage":        5.0,
    "commission":      0.0001,  # 0.01% each way
}

DATA_DIR   = Path(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", Path(__file__).parent))
TRADE_LOG  = DATA_DIR / "zone_trades.csv"
STATE_FILE = DATA_DIR / "zone_state.json"


# ── Indicators ────────────────────────────────────────────────────────────────

def _ema(values, period):
    if len(values) < period:
        return values[-1] if values else 0.0
    k = 2 / (period + 1)
    e = float(np.mean(values[:period]))
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def _ema_series(values, period):
    """Return list of EMA values same length as input (NaN-padded at start)."""
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
    ema_vals = _ema_series(closes, period)
    valid = [(i, v) for i, v in enumerate(ema_vals) if not (isinstance(v, float) and v != v)]
    if len(valid) < slope_bars + 1:
        return False
    return valid[-1][1] > valid[-1 - slope_bars][1]


def _bos_bearish(closes, period, slope_bars):
    ema_vals = _ema_series(closes, period)
    valid = [(i, v) for i, v in enumerate(ema_vals) if not (isinstance(v, float) and v != v)]
    if len(valid) < slope_bars + 1:
        return False
    return valid[-1][1] < valid[-1 - slope_bars][1]


def _prior_high(highs, skip, lookback):
    n = min(lookback, len(highs))
    start = max(0, len(highs) - n)
    end   = max(0, len(highs) - skip)
    if start >= end:
        return max(highs[start:]) if highs[start:] else 0
    return max(highs[start:end])


def _prior_low(lows, skip, lookback):
    n = min(lookback, len(lows))
    start = max(0, len(lows) - n)
    end   = max(0, len(lows) - skip)
    if start >= end:
        return min(lows[start:]) if lows[start:] else 9e9
    return min(lows[start:end])


# ── Data ──────────────────────────────────────────────────────────────────────

def fetch_1h(ticker, months=6):
    """Download ~6 months of 1H bars (yfinance max for 1H is ~730 days)."""
    end   = pd.Timestamp.now()
    start = end - pd.DateOffset(months=months)
    df = _clean(yf.download(ticker, start=start.strftime("%Y-%m-%d"),
                             end=end.strftime("%Y-%m-%d"),
                             interval="1h", progress=False))
    return df


def build_zones(df_1h):
    """Resample 1H → 4H, detect zones, return zone list."""
    df_4h = (df_1h.resample("4h")
             .agg({"Open": "first", "High": "max", "Low": "min",
                   "Close": "last", "Volume": "sum"})
             .dropna())
    zones = detect_zones(df_4h, df_1h,
                         strength_bars=PARAMS["strength_bars"],
                         strength_mult=PARAMS["strength_mult"])
    return zones


# ── Persistence ───────────────────────────────────────────────────────────────

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
            "date", "time", "action", "dir", "shares", "price",
            "stop", "reason", "pnl", "balance", "signal_details"
        ])
        if not exists:
            w.writeheader()
        w.writerow(row)


# ── Position management ───────────────────────────────────────────────────────

def _qty(balance, price, risk):
    if risk <= 0 or price <= 0:
        return 0
    risk_shares = int(balance * PARAMS["risk_pct"] / risk)
    lev_shares  = int(balance * PARAMS["leverage"] / price)
    return min(risk_shares, lev_shares)


def _close_position(state, price, reason):
    pos = state["position"]
    if not pos:
        return
    if pos["dir"] == "LONG":
        pnl = (price - pos["entry"]) * pos["shares"]
    else:
        pnl = (pos["entry"] - price) * pos["shares"]
    comm    = (pos["entry"] * pos["shares"] + price * pos["shares"]) * PARAMS["commission"]
    net_pnl = pnl - comm

    state["balance"]      += net_pnl
    state["total_pnl"]    += net_pnl
    state["total_trades"] += 1
    if net_pnl > 0:
        state["wins"] += 1
    else:
        state["losses"] += 1
    state["position"] = None

    now = datetime.now(ET)
    tag = "WIN" if net_pnl > 0 else "LOSS"
    print(f"\n  *** CLOSE {pos['dir']} {pos['shares']}sh @ ${price:.3f} ({reason}) [{tag}] ***")
    print(f"      Entry ${pos['entry']:.3f} → Exit ${price:.3f}  Net: ${net_pnl:+.2f}")
    print(f"      Balance: ${state['balance']:,.2f}")

    log_trade({
        "date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M"),
        "action": "CLOSE", "dir": pos["dir"], "shares": pos["shares"],
        "price": round(price, 3), "stop": round(pos["stop"], 3),
        "reason": reason, "pnl": round(net_pnl, 2),
        "balance": round(state["balance"], 2),
        "signal_details": f"entry={pos['entry']:.3f} comm={comm:.2f} zone={pos.get('zone_type','?')}",
    })
    save_state(state)


# ── Main loop ─────────────────────────────────────────────────────────────────

def run(ticker="GLD", capital=500.0):
    print(f"\n{'='*70}")
    print(f"  Zone Refinement Paper Trader")
    print(f"  Ticker: {ticker}  |  Capital: ${capital:,.0f}  |  Timeframe: 1H bars")
    print(f"  Leverage: {PARAMS['leverage']}x  |  Risk/trade: {PARAMS['risk_pct']*100:.0f}%")
    print(f"  Log: {TRADE_LOG}")
    print(f"{'='*70}\n")

    # Load or initialise state
    state = load_state()
    if state and state.get("ticker") == ticker:
        print(f"  Resuming — Balance: ${state['balance']:,.2f}, "
              f"Trades: {state['total_trades']}, P&L: ${state['total_pnl']:+,.2f}")
        if not state.get("zones"):
            state["zones"] = []
    else:
        state = {
            "ticker":        ticker,
            "capital":       capital,
            "balance":       capital,
            "position":      None,
            "zones":         [],
            "zones_date":    None,   # date zones were last computed
            "total_trades":  0,
            "total_pnl":     0.0,
            "wins":          0,
            "losses":        0,
        }
        save_state(state)
        print(f"  Starting fresh — ${capital:,.0f}")

    last_bar_time = None

    while True:
        try:
            now  = datetime.now(ET)
            date_str = now.strftime("%Y-%m-%d")

            # Only Mon-Fri
            if now.weekday() >= 5:
                time.sleep(300)
                continue

            market_open  = now.replace(hour=9, minute=30, second=0, microsecond=0)
            market_close = now.replace(hour=16, minute=30, second=0, microsecond=0)

            # Before market
            if now < market_open:
                wait = (market_open - now).total_seconds()
                if wait > 600:
                    print(f"  Market opens in {wait/60:.0f}m — sleeping...")
                    time.sleep(min(wait - 120, 600))
                else:
                    time.sleep(30)
                continue

            # After market
            if now > market_close:
                if state["position"]:
                    df_tmp = _clean(yf.download(ticker, period="1d",
                                                interval="1h", progress=False))
                    if not df_tmp.empty:
                        _close_position(state, float(df_tmp["Close"].iloc[-1]), "EOD")
                next_open = market_open + timedelta(days=1)
                while next_open.weekday() >= 5:
                    next_open += timedelta(days=1)
                wait = (next_open - now).total_seconds()
                print(f"  Market closed. Next: {next_open.strftime('%Y-%m-%d %H:%M ET')}")
                time.sleep(min(wait, 3600))
                continue

            # ── Refresh zones daily ───────────────────────────────────
            if state["zones_date"] != date_str:
                print(f"  [{now.strftime('%H:%M')}] Refreshing zones ({ticker}, 6 months 1H)...")
                df_1h = fetch_1h(ticker, months=6)
                if df_1h.empty:
                    print("  No 1H data — retrying in 60s")
                    time.sleep(60)
                    continue

                # Preserve consumed status from prior zones (max 7 days — zones reset after a week)
                old_consumed = {}
                for z in state.get("zones", []):
                    if not z.get("consumed", False):
                        continue
                    consumed_date = z.get("consumed_date")
                    if consumed_date:
                        age = (datetime.now(ET).date() -
                               datetime.fromisoformat(consumed_date).date()).days
                        if age > 7:
                            continue  # reset old consumed zones
                    key = (z["type"], round(z["htf_top"], 3), round(z["htf_bottom"], 3))
                    old_consumed[key] = True

                new_zones = build_zones(df_1h)
                for z in new_zones:
                    key = (z["type"], round(z["htf_top"], 3), round(z["htf_bottom"], 3))
                    z["consumed"] = old_consumed.get(key, False)

                state["zones"]      = new_zones
                state["zones_date"] = date_str
                d = sum(1 for z in new_zones if z["type"] == "demand")
                s = sum(1 for z in new_zones if z["type"] == "supply")
                print(f"  Zones loaded: {len(new_zones)} ({d} demand, {s} supply)")
                save_state(state)

            # ── Fetch latest 1H bars ──────────────────────────────────
            df_1h = _clean(yf.download(ticker, period="59d",
                                        interval="1h", progress=False))
            if df_1h.empty:
                time.sleep(60)
                continue

            latest_time = df_1h.index[-1]
            if last_bar_time and latest_time <= last_bar_time:
                time.sleep(120)   # wait for next 1H bar
                continue
            last_bar_time = latest_time

            closes = df_1h["Close"].tolist()
            highs  = df_1h["High"].tolist()
            lows   = df_1h["Low"].tolist()
            price  = closes[-1]
            high   = highs[-1]
            low    = lows[-1]
            ts     = df_1h.index[-1].to_pydatetime()

            print(f"  [{now.strftime('%H:%M')}] Bar closed: ${price:.3f}  "
                  f"(H:{high:.3f} L:{low:.3f})")

            # ── Manage open position ──────────────────────────────────
            if state["position"]:
                pos = state["position"]
                hit_stop   = (pos["dir"] == "LONG"  and price <= pos["stop"]) or \
                             (pos["dir"] == "SHORT" and price >= pos["stop"])
                hit_target = (pos["dir"] == "LONG"  and price >= pos["target"]) or \
                             (pos["dir"] == "SHORT" and price <= pos["target"])
                if hit_stop:
                    _close_position(state, pos["stop"], "STOP")
                elif hit_target:
                    _close_position(state, pos["target"], "TARGET")
                else:
                    unreal = ((price - pos["entry"]) * pos["shares"]
                              if pos["dir"] == "LONG"
                              else (pos["entry"] - price) * pos["shares"])
                    print(f"      {pos['dir']} {pos['shares']}sh @ ${pos['entry']:.3f}  "
                          f"Stop:${pos['stop']:.3f}  Tgt:${pos['target']:.3f}  "
                          f"Unreal:${unreal:+.2f}")
                time.sleep(120)
                continue

            # ── Zone scan ─────────────────────────────────────────────
            p = PARAMS
            bull = _bos_bullish(closes, p["bos_ema"], p["bos_slope_bars"])
            bear = _bos_bearish(closes, p["bos_ema"], p["bos_slope_bars"])

            entered = False
            for zone in state["zones"]:
                if zone.get("consumed"):
                    continue
                # Zone must have formed before this bar
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

                if zone["type"] == "demand":
                    if not (zbot <= price <= ztop):
                        continue
                    if not bull:
                        continue
                    if low > rtop:
                        continue   # hasn't touched refined zone
                    if price < rbot:
                        continue   # blown through
                    stop   = rbot * (1 - buf)
                    risk   = price - stop
                    if risk <= 0:
                        continue
                    target = _prior_high(highs, p["target_skip"], p["target_lookback"])
                    if target <= price:
                        continue
                    rr = (target - price) / risk
                    if rr < p["min_rr"]:
                        continue
                    qty = _qty(state["balance"], price, risk)
                    if qty <= 0:
                        continue

                    state["position"] = {
                        "dir":       "LONG",
                        "shares":    qty,
                        "entry":     price,
                        "stop":      stop,
                        "target":    target,
                        "zone_type": "demand",
                        "entry_time": now.strftime("%H:%M"),
                    }
                    state["traded_today"] = True
                    zone["consumed"] = True
                    zone["consumed_date"] = date_str
                    save_state(state)

                    print(f"\n  *** LONG {qty}sh @ ${price:.3f} (demand zone) ***")
                    print(f"      Stop:${stop:.3f}  Target:${target:.3f}  R:R:{rr:.1f}x")

                    log_trade({
                        "date": date_str, "time": now.strftime("%H:%M"),
                        "action": "BUY", "dir": "LONG", "shares": qty,
                        "price": round(price, 3), "stop": round(stop, 3),
                        "reason": "ZONE", "pnl": "",
                        "balance": round(state["balance"], 2),
                        "signal_details": (
                            f"zone=demand htf=[{zbot:.2f},{ztop:.2f}] "
                            f"refined=[{rbot:.3f},{rtop:.3f}] rr={rr:.1f}"
                        ),
                    })
                    entered = True
                    break

                elif zone["type"] == "supply":
                    if not (zbot <= price <= ztop):
                        continue
                    if not bear:
                        continue
                    if high < rbot:
                        continue
                    if price > rtop:
                        continue
                    stop   = rtop * (1 + buf)
                    risk   = stop - price
                    if risk <= 0:
                        continue
                    target = _prior_low(lows, p["target_skip"], p["target_lookback"])
                    if target >= price:
                        continue
                    rr = (price - target) / risk
                    if rr < p["min_rr"]:
                        continue
                    qty = _qty(state["balance"], price, risk)
                    if qty <= 0:
                        continue

                    state["position"] = {
                        "dir":       "SHORT",
                        "shares":    qty,
                        "entry":     price,
                        "stop":      stop,
                        "target":    target,
                        "zone_type": "supply",
                        "entry_time": now.strftime("%H:%M"),
                    }
                    zone["consumed"] = True
                    zone["consumed_date"] = date_str
                    save_state(state)

                    print(f"\n  *** SHORT {qty}sh @ ${price:.3f} (supply zone) ***")
                    print(f"      Stop:${stop:.3f}  Target:${target:.3f}  R:R:{rr:.1f}x")

                    log_trade({
                        "date": date_str, "time": now.strftime("%H:%M"),
                        "action": "SELL", "dir": "SHORT", "shares": qty,
                        "price": round(price, 3), "stop": round(stop, 3),
                        "reason": "ZONE", "pnl": "",
                        "balance": round(state["balance"], 2),
                        "signal_details": (
                            f"zone=supply htf=[{zbot:.2f},{ztop:.2f}] "
                            f"refined=[{rbot:.3f},{rtop:.3f}] rr={rr:.1f}"
                        ),
                    })
                    entered = True
                    break

            if not entered:
                print(f"      Flat — no zone signal")

            time.sleep(120)

        except KeyboardInterrupt:
            print(f"\n  Stopping zone paper trader...")
            if state["position"]:
                pos = state["position"]
                print(f"  Open: {pos['dir']} {pos['shares']}sh @ ${pos['entry']:.3f}")
            save_state(state)
            break
        except Exception as e:
            print(f"  ERROR: {e}")
            time.sleep(60)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker",  default="GLD")
    ap.add_argument("--capital", type=float, default=500.0)
    args = ap.parse_args()
    run(ticker=args.ticker, capital=args.capital)
