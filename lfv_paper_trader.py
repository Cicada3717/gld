"""
lfv_paper_trader.py — LFV Live Paper Trader (multi-asset)
=========================================================
Runs GLD (market hours) and BTC-USD (24/7) in a single loop.
Each asset has its own state file, trade log, and optimised params.

Usage:
  python lfv_paper_trader.py
  python lfv_paper_trader.py --capital 10000
"""

import argparse
import csv
import json
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

from signal_scanner import detect_signal

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

DATA_DIR = Path(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", Path(__file__).parent))

# ── Per-ticker config ─────────────────────────────────────────────────────────

TICKER_CFG = {
    "GLD": {
        "params": {
            "swing_n":         3,
            "sweep_min_atr":   0.30,
            "avwap_tolerance": 0.010,
            "vp_lookback":     100,
            "vp_buckets":      50,
            "vah_val_pct":     0.80,
            "lvn_ratio":       0.25,
            "stop_atr_buffer": 1.25,
            "min_rr":          3.0,
            "be_after_r":      2.0,
            "trail_after_r":   3.0,
            "trail_atr":       0.75,
            "risk_pct":        0.02,
            "leverage":        5.0,
            "commission":      0.0002,
        },
        "market_hours": True,   # Mon-Fri 09:30-16:00 ET
        "eod_close":    True,
    },
    "BTC-USD": {
        "params": {
            "swing_n":         8,
            "sweep_min_atr":   0.40,
            "avwap_tolerance": 0.007,
            "vp_lookback":     80,
            "vp_buckets":      40,
            "vah_val_pct":     0.75,
            "lvn_ratio":       0.20,
            "stop_atr_buffer": 1.0,
            "min_rr":          3.5,
            "be_after_r":      2.0,
            "trail_after_r":   3.0,
            "trail_atr":       0.75,
            "risk_pct":        0.02,
            "leverage":        5.0,
            "commission":      0.0002,
        },
        "market_hours": False,  # 24/7
        "eod_close":    False,
    },
}


def _state_file(ticker):
    safe = ticker.replace("=", "").replace("-", "")
    return DATA_DIR / f"lfv_state_{safe}.json"


def _trade_file(ticker):
    safe = ticker.replace("=", "").replace("-", "")
    return DATA_DIR / f"lfv_trades_{safe}.csv"


# ── Persistence ───────────────────────────────────────────────────────────────

def load_state(ticker):
    f = _state_file(ticker)
    if f.exists():
        with open(f) as fh:
            return json.load(fh)
    return None


def save_state(ticker, state):
    with open(_state_file(ticker), "w") as f:
        json.dump(state, f, indent=2, default=str)


def log_trade(ticker, row):
    f = _trade_file(ticker)
    exists = f.exists()
    with open(f, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "date", "time", "action", "dir", "shares", "price",
            "stop", "reason", "pnl", "balance", "signal_details"
        ])
        if not exists:
            w.writeheader()
        w.writerow(row)


# ── ATR helper ────────────────────────────────────────────────────────────────

def _current_atr(df, period=14):
    high  = df["High"].values
    low   = df["Low"].values
    close = df["Close"].values
    tr = np.maximum(high[1:] - low[1:],
         np.maximum(np.abs(high[1:] - close[:-1]),
                    np.abs(low[1:]  - close[:-1])))
    if len(tr) < period:
        return float(np.mean(tr)) if len(tr) > 0 else 1.0
    return float(np.mean(tr[-period:]))


# ── Position sizing ───────────────────────────────────────────────────────────

def _qty(balance, price, risk, params):
    if risk <= 0 or price <= 0:
        return 0
    risk_shares = int(balance * params["risk_pct"] / risk)
    lev_shares  = int(balance * params["leverage"] / price)
    return min(risk_shares, lev_shares)


# ── Close position ────────────────────────────────────────────────────────────

def _close_position(ticker, state, price, reason, params):
    pos = state["position"]
    if not pos:
        return
    if pos["dir"] == "LONG":
        pnl = (price - pos["entry"]) * pos["shares"]
    else:
        pnl = (pos["entry"] - price) * pos["shares"]
    comm    = (pos["entry"] + price) * pos["shares"] * params["commission"]
    net_pnl = pnl - comm

    state["balance"]      += net_pnl
    state["total_pnl"]    += net_pnl
    state["total_trades"] += 1
    if net_pnl > 0:
        state["wins"]   += 1
    else:
        state["losses"] += 1
    state["position"] = None

    now = datetime.now(ET)
    tag = "WIN" if net_pnl > 0 else "LOSS"
    print(f"\n  [{ticker}] *** CLOSE {pos['dir']} {pos['shares']}sh @ ${price:.3f} ({reason}) [{tag}] ***")
    print(f"      Entry ${pos['entry']:.3f} -> Exit ${price:.3f}  Net: ${net_pnl:+.2f}")
    print(f"      Balance: ${state['balance']:,.2f}")

    log_trade(ticker, {
        "date":           now.strftime("%Y-%m-%d"),
        "time":           now.strftime("%H:%M"),
        "action":         "CLOSE",
        "dir":            pos["dir"],
        "shares":         pos["shares"],
        "price":          round(price, 3),
        "stop":           round(pos["stop"], 3),
        "reason":         reason,
        "pnl":            round(net_pnl, 2),
        "balance":        round(state["balance"], 2),
        "signal_details": (f"entry={pos['entry']:.3f} phase={pos.get('phase',1)} "
                           f"swept={pos.get('swept_lvl','?')} poc={pos.get('poc','?')}"),
    })
    save_state(ticker, state)


# ── Market hours check ────────────────────────────────────────────────────────

def _is_market_open_gld():
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    if now.hour < 9 or (now.hour == 9 and now.minute < 30):
        return False
    if now.hour >= 16:
        return False
    return True


def _should_eod_close_gld():
    now = datetime.now(ET)
    return now.weekday() < 5 and now.hour >= 16 and now.hour < 17


# ── Process one ticker ────────────────────────────────────────────────────────

def process_ticker(ticker, state, last_signal_bar, cfg):
    params = cfg["params"]
    now    = datetime.now(ET)

    # Market hours gate (GLD only)
    if cfg["market_hours"]:
        if not _is_market_open_gld():
            # EOD close
            if cfg["eod_close"] and state["position"] and _should_eod_close_gld():
                print(f"  [{ticker}] EOD -- closing position")
                df = yf.download(ticker, period="1d", interval="5m",
                                 auto_adjust=True, progress=False)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(1)
                df.dropna(inplace=True)
                if not df.empty:
                    _close_position(ticker, state, float(df["Close"].iloc[-1]), "EOD", params)
            return last_signal_bar  # skip — market closed

    # Fetch data
    df = yf.download(ticker, period="60d", interval="5m",
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    df.dropna(inplace=True)

    if len(df) < 50:
        print(f"  [{ticker}] Insufficient data ({len(df)} bars)")
        return last_signal_bar

    price = float(df["Close"].iloc[-1])
    atr   = _current_atr(df)
    print(f"  [{now.strftime('%H:%M')}] {ticker} ${price:,.3f}  ATR={atr:.3f}  Bars={len(df)}")

    # ── Manage open position (3-phase trailing) ───────────────────────────────
    if state["position"]:
        pos       = state["position"]
        init_risk = pos["init_risk"]
        entry     = pos["entry"]
        phase     = pos.get("phase", 1)

        if pos["dir"] == "LONG":
            profit_r = (price - entry) / init_risk if init_risk > 0 else 0

            if phase == 1 and profit_r >= params["be_after_r"]:
                new_stop = entry
                if new_stop > pos["stop"]:
                    print(f"      [{ticker}] Phase 2 (BE): stop ${pos['stop']:.3f} -> ${new_stop:.3f}")
                    pos["stop"] = new_stop; pos["phase"] = 2
                    save_state(ticker, state)

            if phase <= 2 and profit_r >= params["trail_after_r"]:
                new_stop = price - atr * params["trail_atr"]
                if new_stop > pos["stop"]:
                    print(f"      [{ticker}] Phase 3 (TRAIL): stop -> ${new_stop:.3f}")
                    pos["stop"] = new_stop; pos["phase"] = 3
                    save_state(ticker, state)

            if phase == 3:
                new_stop = price - atr * params["trail_atr"]
                if new_stop > pos["stop"]:
                    print(f"      [{ticker}] Trail ratchet: ${pos['stop']:.3f} -> ${new_stop:.3f}")
                    pos["stop"] = new_stop
                    save_state(ticker, state)

            if price <= pos["stop"]:
                reason = {1: "STOP", 2: "BE_STOP", 3: "TRAIL_STOP"}.get(phase, "STOP")
                _close_position(ticker, state, pos["stop"], reason, params)

        else:  # SHORT
            profit_r = (entry - price) / init_risk if init_risk > 0 else 0

            if phase == 1 and profit_r >= params["be_after_r"]:
                new_stop = entry
                if new_stop < pos["stop"]:
                    print(f"      [{ticker}] Phase 2 (BE): stop ${pos['stop']:.3f} -> ${new_stop:.3f}")
                    pos["stop"] = new_stop; pos["phase"] = 2
                    save_state(ticker, state)

            if phase <= 2 and profit_r >= params["trail_after_r"]:
                new_stop = price + atr * params["trail_atr"]
                if new_stop < pos["stop"]:
                    print(f"      [{ticker}] Phase 3 (TRAIL): stop -> ${new_stop:.3f}")
                    pos["stop"] = new_stop; pos["phase"] = 3
                    save_state(ticker, state)

            if phase == 3:
                new_stop = price + atr * params["trail_atr"]
                if new_stop < pos["stop"]:
                    print(f"      [{ticker}] Trail ratchet: ${pos['stop']:.3f} -> ${new_stop:.3f}")
                    pos["stop"] = new_stop
                    save_state(ticker, state)

            if price >= pos["stop"]:
                reason = {1: "STOP", 2: "BE_STOP", 3: "TRAIL_STOP"}.get(phase, "STOP")
                _close_position(ticker, state, pos["stop"], reason, params)

        if state["position"]:
            pos = state["position"]
            unreal = ((price - pos["entry"]) * pos["shares"]
                      if pos["dir"] == "LONG"
                      else (pos["entry"] - price) * pos["shares"])
            phase_name = {1: "HARD", 2: "BE", 3: "TRAIL"}.get(pos.get("phase", 1), "?")
            print(f"      [{ticker}] {pos['dir']} {pos['shares']}sh @ ${pos['entry']:.3f}  "
                  f"Stop:${pos['stop']:.3f}[{phase_name}]  Unreal:${unreal:+.2f}")

        return last_signal_bar   # don't scan for new signals while in a position

    # ── Signal scan ───────────────────────────────────────────────────────────
    sig_cfg = {"ticker": ticker, **params}
    sig = detect_signal(df, sig_cfg)

    if sig is None:
        print(f"      [{ticker}] No signal")
        return last_signal_bar

    bar_key = str(sig["bar_time"])
    if last_signal_bar == bar_key:
        print(f"      [{ticker}] Signal already acted on for bar {bar_key}")
        return last_signal_bar

    # ── Enter ─────────────────────────────────────────────────────────────────
    entry     = sig["entry"]
    stop      = sig["stop"]
    stop_dist = abs(entry - stop)
    shares    = _qty(state["balance"], entry, stop_dist, params)

    if shares <= 0:
        print(f"      [{ticker}] Signal skipped -- 0 shares")
        return bar_key

    direction = sig["direction"]
    action    = "BUY" if direction == "LONG" else "SELL"

    state["position"] = {
        "dir":       direction,
        "shares":    shares,
        "entry":     entry,
        "stop":      stop,
        "init_risk": stop_dist,
        "phase":     1,
        "entry_time": now.strftime("%Y-%m-%d %H:%M"),
        "swept_lvl": sig.get("swept_lvl"),
        "poc":       sig.get("poc"),
        "avwap":     sig.get("avwap"),
    }
    save_state(ticker, state)

    proj_rr = sig.get("proj_rr", 0)
    print(f"\n  [{ticker}] >>> ENTER {direction} {shares}sh @ ${entry:,.3f}  "
          f"Stop:${stop:,.3f}  ProjRR:{proj_rr:.1f}x  "
          f"Swept:{sig.get('swept_lvl',0):,.3f}")

    log_trade(ticker, {
        "date":    now.strftime("%Y-%m-%d"),
        "time":    now.strftime("%H:%M"),
        "action":  action,
        "dir":     direction,
        "shares":  shares,
        "price":   round(entry, 3),
        "stop":    round(stop, 3),
        "reason":  f"LFV sweep @ {sig.get('swept_lvl',0):.3f}",
        "pnl":     "",
        "balance": round(state["balance"], 2),
        "signal_details": (
            f"swept={sig.get('swept_lvl',0):.3f} "
            f"avwap={sig.get('avwap',0):.3f} "
            f"poc={sig.get('poc',0):.3f} "
            f"proj_rr={proj_rr:.1f}"
        ),
    })

    return bar_key


# ── Main loop ─────────────────────────────────────────────────────────────────

def run(capital=10_000.0):
    tickers = list(TICKER_CFG.keys())

    print(f"\n{'='*70}")
    print(f"  LFV Paper Trader  |  {', '.join(tickers)}  |  5-min bars")
    print(f"  Capital per asset: ${capital:,.0f}")
    print(f"{'='*70}\n")

    # Init states
    states = {}
    last_signal_bars = {}
    for ticker in tickers:
        s = load_state(ticker)
        if s and s.get("ticker") == ticker:
            print(f"  [{ticker}] Resuming -- Balance: ${s['balance']:,.2f}, "
                  f"Trades: {s['total_trades']}, P&L: ${s['total_pnl']:+,.2f}")
        else:
            s = {
                "ticker":        ticker,
                "capital":       capital,
                "balance":       capital,
                "position":      None,
                "total_trades":  0,
                "total_pnl":     0.0,
                "wins":          0,
                "losses":        0,
            }
            save_state(ticker, s)
            print(f"  [{ticker}] Starting fresh -- ${capital:,.0f}")
        states[ticker] = s
        last_signal_bars[ticker] = None

    while True:
        for ticker in tickers:
            try:
                last_signal_bars[ticker] = process_ticker(
                    ticker,
                    states[ticker],
                    last_signal_bars[ticker],
                    TICKER_CFG[ticker],
                )
            except Exception as e:
                print(f"  [{ticker}] ERROR: {e}")
                import traceback; traceback.print_exc()

        # Sleep until ~10s after next 5m bar boundary
        now_ts  = time.time()
        next_5m = (now_ts // 300 + 1) * 300 + 10
        time.sleep(next_5m - now_ts)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", default=10_000.0, type=float,
                    help="Starting capital per asset")
    args = ap.parse_args()
    run(capital=args.capital)


if __name__ == "__main__":
    main()
