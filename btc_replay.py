"""
btc_replay.py — Replay BTC-USD LFV strategy from March 18 2026 to today.
Writes lfv_trades_BTCUSD.csv + lfv_state_BTCUSD.json so the dashboard
shows correct history from the start date.

All bugs fixed:
  - Stop checks use bar HIGH/LOW (not close)
  - Slippage ($25) included in position sizing
  - Slippage applied to exit price
  - Best-price tracking uses bar HIGH (LONG) / LOW (SHORT)

Optimized params (from 1296-combo grid search):
  sweep_min_atr=0.25, min_rr=3.0, be_after_r=1.5,
  trail_after_r=2.5, trail_atr=0.50
"""

import csv
import json
import os
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent))
from signal_scanner import detect_signal, _atr as _atr_arr

# -- Config ------------------------------------------------------------------
TICKER      = "BTC-USD"
CAPITAL     = 10_000.0
SLIPPAGE    = 25.0
MIN_SIZE    = 0.0001
START_DATE  = date(2026, 3, 18)
DATA_DIR    = Path(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", Path(__file__).parent))
YF_CACHE_DIR = DATA_DIR / ".yf_cache"
YF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
yf.set_tz_cache_location(str(YF_CACHE_DIR))

PARAMS = {
    "ticker":          TICKER,
    "swing_n":         8,
    "sweep_min_atr":   0.25,   # OPTIMIZED (was 0.40)
    "avwap_tolerance": 0.007,
    "vp_lookback":     80,
    "vp_buckets":      40,
    "vah_val_pct":     0.75,
    "lvn_ratio":       0.20,
    "stop_atr_buffer": 1.0,
    "min_rr":          3.0,    # OPTIMIZED (was 3.5)
    "be_after_r":      1.5,    # OPTIMIZED (was 2.0)
    "trail_after_r":   2.5,    # OPTIMIZED (was 3.0)
    "trail_atr":       0.50,   # OPTIMIZED (was 0.75)
    "risk_pct":        0.02,
}

TRADE_FIELDS = [
    "date", "time", "action", "dir", "shares", "price",
    "stop", "reason", "pnl", "balance", "signal_details",
]


# -- I/O ---------------------------------------------------------------------

def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"  Wrote {len(rows)} rows  ->  {path}")


def write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"  Wrote state   ->  {path}")


# -- Replay ------------------------------------------------------------------

def replay_btc(df):
    h_arr = df["High"].values
    l_arr = df["Low"].values
    c_arr = df["Close"].values
    atr_full = _atr_arr(h_arr, l_arr, c_arr, 14)

    balance   = CAPITAL
    position  = None
    trades    = []
    wins      = 0
    losses    = 0
    total_pnl = 0.0
    peak_bal  = CAPITAL
    max_dd    = 0.0

    replay_start = pd.Timestamp(START_DATE.strftime("%Y-%m-%d"), tz="UTC")
    # Warmup: scan signals from bar 100 onward, but only record trades from START_DATE
    n = len(df)
    last_signal_i = -999
    MIN_GAP = 3

    for i in range(100, n):
        ts    = df.index[i]
        bar_h = h_arr[i]
        bar_l = l_arr[i]
        atr   = atr_full[i] if not np.isnan(atr_full[i]) else (atr_full[i-1] if i > 0 else 1.0)
        date_str = pd.Timestamp(ts).strftime("%Y-%m-%d")
        time_str = pd.Timestamp(ts).strftime("%H:%M")

        # -- Manage open position ----------------------------------------
        if position is not None:
            entry     = position["entry"]
            stop      = position["stop"]
            target    = position["target"]
            init_risk = position["init_risk"]
            phase     = position["phase"]
            direction = position["dir"]

            if direction == "LONG":
                # FIX: track best using bar HIGH
                best_px = position.get("best_px", entry)
                if bar_h > best_px:
                    best_px = bar_h
                    position["best_px"] = best_px
                profit_r = (best_px - entry) / init_risk if init_risk > 0 else 0
                if phase == 1 and profit_r >= PARAMS["be_after_r"]:
                    new_stop = entry
                    if new_stop > stop:
                        position["stop"] = new_stop; stop = new_stop
                        position["phase"] = 2; phase = 2
                if phase <= 2 and profit_r >= PARAMS["trail_after_r"]:
                    new_stop = best_px - atr * PARAMS["trail_atr"]
                    if new_stop > stop:
                        position["stop"] = new_stop; stop = new_stop
                        position["phase"] = 3; phase = 3
                if phase == 3:
                    new_stop = best_px - atr * PARAMS["trail_atr"]
                    if new_stop > stop:
                        position["stop"] = new_stop; stop = new_stop
                # FIX: use bar LOW for stop check
                hit_stop   = bar_l <= stop
                hit_target = bar_h >= target
            else:  # SHORT
                # FIX: track best using bar LOW
                best_px = position.get("best_px", entry)
                if bar_l < best_px:
                    best_px = bar_l
                    position["best_px"] = best_px
                profit_r = (entry - best_px) / init_risk if init_risk > 0 else 0
                if phase == 1 and profit_r >= PARAMS["be_after_r"]:
                    new_stop = entry
                    if new_stop < stop:
                        position["stop"] = new_stop; stop = new_stop
                        position["phase"] = 2; phase = 2
                if phase <= 2 and profit_r >= PARAMS["trail_after_r"]:
                    new_stop = best_px + atr * PARAMS["trail_atr"]
                    if new_stop < stop:
                        position["stop"] = new_stop; stop = new_stop
                        position["phase"] = 3; phase = 3
                if phase == 3:
                    new_stop = best_px + atr * PARAMS["trail_atr"]
                    if new_stop < stop:
                        position["stop"] = new_stop; stop = new_stop
                # FIX: use bar HIGH for stop check
                hit_stop   = bar_h >= stop
                hit_target = bar_l <= target

            if hit_stop or hit_target:
                ep_raw = stop if hit_stop else target
                # FIX: apply slippage to exit
                ep = ep_raw - SLIPPAGE if direction == "LONG" else ep_raw + SLIPPAGE
                pnl = (ep - entry) * position["oz"] if direction == "LONG" \
                      else (entry - ep) * position["oz"]
                reason = {1:"STOP",2:"BE_STOP",3:"TRAIL_STOP"}[phase] if hit_stop else "TARGET"
                balance += pnl; total_pnl += pnl
                peak_bal = max(peak_bal, balance)
                dd = (peak_bal - balance) / peak_bal; max_dd = max(max_dd, dd)
                net_pnl = pnl

                if position.get("record"):
                    if net_pnl > 0: wins   += 1
                    else:           losses += 1
                    trades.append({
                        "date": date_str, "time": time_str,
                        "action": "CLOSE", "dir": direction,
                        "shares": round(position["oz"], 6),
                        "price": round(ep, 2),
                        "stop": round(stop, 2), "reason": reason,
                        "pnl": round(net_pnl, 2), "balance": round(balance, 2),
                        "signal_details": (
                            f"entry={entry:.2f} trigger={ep_raw:.2f} phase={phase}"
                        ),
                    })
                position = None
            continue

        # -- Check for signal (only from START_DATE) ----------------------
        if ts < replay_start:
            continue  # warmup only — no trading before start date

        if i - last_signal_i < MIN_GAP:
            continue

        sub = df.iloc[:i+1]
        sig = detect_signal(sub, PARAMS)
        if sig is None:
            continue

        last_signal_i = i
        rr = sig.get("proj_rr", 0)
        if rr < PARAMS["min_rr"]:
            continue

        entry_px   = sig["entry"]
        stop_raw   = sig["stop"]
        stop_dist  = abs(entry_px - stop_raw)
        actual_risk = stop_dist + 2 * SLIPPAGE   # FIX: include slippage
        if actual_risk <= 0:
            continue
        oz = (balance * PARAMS["risk_pct"]) / actual_risk
        if oz < MIN_SIZE:
            continue

        direction = sig["direction"]
        target_px = sig.get("proj_target", entry_px + stop_dist * PARAMS["min_rr"])

        position = {
            "dir": direction, "oz": oz,
            "entry": entry_px, "stop": stop_raw,
            "target": target_px, "init_risk": stop_dist,
            "phase": 1, "best_px": entry_px,
            "record": True,
            "entry_ts": str(ts),
        }

        action = "BUY" if direction == "LONG" else "SELL"
        trades.append({
            "date": date_str, "time": time_str,
            "action": action, "dir": direction,
            "shares": round(oz, 6),
            "price": round(entry_px, 2),
            "stop": round(stop_raw, 2),
            "reason": f"LFV sweep @ {sig.get('swept_lvl',0):.2f}",
            "pnl": "",
            "balance": round(balance, 2),
            "signal_details": (
                f"swept={sig.get('swept_lvl',0):.2f} "
                f"avwap={sig.get('avwap',0):.2f} "
                f"poc={sig.get('poc',0):.2f} "
                f"proj_rr={rr:.1f}"
            ),
        })

    closed = [t for t in trades if t["action"] == "CLOSE"]
    n_closed = len(closed)
    roi = (balance - CAPITAL) / CAPITAL * 100
    wr  = wins / n_closed * 100 if n_closed else 0
    print(f"  BTC LFV Replay: {n_closed} trades | W:{wins} L:{losses} | "
          f"WR:{wr:.1f}% | ROI:{roi:+.2f}% | MaxDD:{-max_dd*100:.1f}% | Balance:${balance:,.2f}")

    live_pos = None
    if position and position.get("record"):
        live_pos = {
            "dir":       position["dir"],
            "shares":    round(position["oz"], 6),
            "entry":     position["entry"],
            "stop":      position["stop"],
            "init_risk": position["init_risk"],
            "phase":     position["phase"],
            "entry_time": pd.Timestamp(position["entry_ts"]).strftime("%Y-%m-%d %H:%M"),
        }
        print(f"  Open position: {live_pos['dir']} {live_pos['shares']} BTC @ ${live_pos['entry']:.2f}")

    state = {
        "ticker": TICKER, "capital": CAPITAL, "balance": round(balance, 2),
        "position": live_pos, "total_trades": n_closed,
        "total_pnl": round(total_pnl, 2), "wins": wins, "losses": losses,
        "last_signal_bar": None, "last_processed_bar": None,
    }
    return trades, state


# -- Entry point -------------------------------------------------------------

if __name__ == "__main__":
    print(f"\n{'='*60}")
    print(f"  BTC LFV Replay  |  {START_DATE} to today")
    print(f"  Capital: ${CAPITAL:,.0f}  |  SLIPPAGE: ${SLIPPAGE}")
    print(f"{'='*60}\n")

    print("[1/2] Fetching BTC-USD 5-min data (60d)...")
    df = yf.download(TICKER, period="60d", interval="5m",
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df.dropna(subset=["Open","High","Low","Close","Volume"])
    if df.empty:
        raise RuntimeError("No BTC data returned.")
    print(f"  {len(df)} bars  ({df.index[0]} -> {df.index[-1]})\n")

    print("[2/2] Replaying trades from March 18...")
    btc_trades, btc_state = replay_btc(df)

    print("\nWriting output files...")
    write_csv(DATA_DIR / "lfv_trades_BTCUSD.csv", btc_trades)
    write_json(DATA_DIR / "lfv_state_BTCUSD.json", btc_state)
    print("\nDone.\n")
