"""
replay.py — Simulate Zone Refinement (1H) on real GC=F data from March 18 2026
to today.  Writes:
  zone_trades.csv  / zone_state.json

Run once locally (or at Railway deploy) to populate dashboard with
historical replay results.  Always overwrites existing files.
"""

import csv
import json
import os
from datetime import datetime, date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from zone_refinement_backtest import detect_zones, _clean

# -- Config ------------------------------------------------------------------
TICKER      = "GC=F"
CAPITAL     = 10000.0
START_DATE  = date(2026, 3, 18)
DATA_DIR    = Path(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", Path(__file__).parent))

ZONE_P = dict(
    strength_bars=3, strength_mult=2.0,
    bos_ema=21, bos_slope_bars=5,
    stop_buffer=0.003, target_lookback=120, target_skip=5,
    min_rr=3.0, risk_pct=0.02, leverage=5.0, commission=0.0001,
)

TRADE_FIELDS = [
    "date", "time", "action", "dir", "shares", "price",
    "stop", "reason", "pnl", "balance", "signal_details",
]


# -- Indicator helpers -------------------------------------------------------

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
    n     = min(lookback, len(highs))
    start = max(0, len(highs) - n)
    end   = max(0, len(highs) - skip)
    if start >= end:
        return max(highs[start:]) if highs[start:] else 0.0
    return max(highs[start:end])


def _prior_low(lows, skip, lookback):
    n     = min(lookback, len(lows))
    start = max(0, len(lows) - n)
    end   = max(0, len(lows) - skip)
    if start >= end:
        return min(lows[start:]) if lows[start:] else 9e9
    return min(lows[start:end])


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


# -- Zone Refinement replay (1H) --------------------------------------------

def replay_zone(df1h, zones):
    p         = ZONE_P
    balance   = CAPITAL
    position  = None
    trades    = []
    wins = losses = 0
    total_pnl = 0.0
    last_stop_time = None  # 6-hour cooldown tracker

    replay_start = pd.Timestamp(START_DATE.strftime("%Y-%m-%d"))
    df_replay    = df1h[df1h.index >= replay_start].copy()
    zone_list    = [dict(z) for z in zones]  # mutable copy

    for ts, row in df_replay.iterrows():
        # Skip Sat, Sun pre-18:00, and 17:00 maintenance hour
        dt = ts.to_pydatetime()
        if dt.weekday() == 5:
            continue
        if dt.weekday() == 6 and dt.hour < 18:
            continue
        if dt.hour == 17:
            continue

        date_str = ts.strftime("%Y-%m-%d")
        time_str = ts.strftime("%H:%M")

        hist   = df1h[df1h.index <= ts]
        closes = hist["Close"].tolist()
        highs  = hist["High"].tolist()
        lows   = hist["Low"].tolist()
        price  = float(row["Close"])
        high   = float(row["High"])
        low    = float(row["Low"])

        # -- Manage open position ----------------------------------------
        if position:
            hit_stop   = (position["dir"] == "LONG"  and price <= position["stop"]) or \
                         (position["dir"] == "SHORT" and price >= position["stop"])
            hit_target = (position["dir"] == "LONG"  and price >= position["target"]) or \
                         (position["dir"] == "SHORT" and price <= position["target"])
            if not hit_stop and not hit_target:
                continue

            exit_px = position["stop"] if hit_stop else position["target"]
            reason  = "STOP" if hit_stop else "TARGET"
            pnl     = (exit_px - position["entry"]) * position["shares"] if position["dir"] == "LONG" \
                      else (position["entry"] - exit_px) * position["shares"]
            comm    = (position["entry"] + exit_px) * position["shares"] * p["commission"]
            net     = pnl - comm
            balance += net; total_pnl += net
            if net > 0: wins  += 1
            else:       losses += 1
            trades.append({
                "date": date_str, "time": time_str,
                "action": "CLOSE", "dir": position["dir"],
                "shares": position["shares"], "price": round(exit_px, 3),
                "stop": round(position["stop"], 3), "reason": reason,
                "pnl": round(net, 2), "balance": round(balance, 2),
                "signal_details": f"entry={position['entry']:.3f} comm={comm:.2f} zone={position.get('zone_type','?')}",
            })
            if reason == "STOP":
                last_stop_time = dt
            position = None
            continue

        # -- 6-hour cooldown after stop-out ------------------------------
        if last_stop_time:
            if (dt - last_stop_time) < timedelta(hours=6):
                continue

        # -- Zone scan ---------------------------------------------------
        bull = _bos_bullish(closes, p["bos_ema"], p["bos_slope_bars"])
        bear = _bos_bearish(closes, p["bos_ema"], p["bos_slope_bars"])

        for zone in zone_list:
            if zone.get("consumed"):
                continue

            formed = zone["formed_at"]
            if not isinstance(formed, datetime):
                formed = datetime.fromisoformat(str(formed))
            if pd.Timestamp(formed) >= ts:
                continue
            # Skip stale zones older than 3 days
            formed_dt = formed if isinstance(formed, datetime) else datetime.fromisoformat(str(formed))
            if (dt - formed_dt).total_seconds() > 3 * 86400:
                continue

            ztop = zone["htf_top"]
            zbot = zone["htf_bottom"]
            rtop = zone["refined_top"]
            rbot = zone["refined_bottom"]
            buf  = p["stop_buffer"]

            if zone["type"] == "demand":
                if not (zbot <= price <= ztop): continue
                if not bull:                    continue
                if low > rtop:                  continue
                if price < rbot:                continue
                stop   = rbot * (1 - buf)
                risk   = price - stop
                if risk <= 0:                   continue
                target = _prior_high(highs, p["target_skip"], p["target_lookback"])
                if target <= price:
                    target = price + risk * p["min_rr"]
                rr = (target - price) / risk
                if rr < p["min_rr"]:            continue
                qty = min(int(balance * p["risk_pct"] / risk),
                          int(balance * p["leverage"] / price))
                if qty <= 0:                    continue

                position = {"dir": "LONG", "shares": qty, "entry": price,
                            "stop": stop, "target": target, "zone_type": "demand"}
                zone["consumed"]      = True
                zone["consumed_date"] = date_str
                trades.append({
                    "date": date_str, "time": time_str,
                    "action": "BUY", "dir": "LONG", "shares": qty,
                    "price": round(price, 3), "stop": round(stop, 3),
                    "reason": "ZONE", "pnl": "",
                    "balance": round(balance, 2),
                    "signal_details": (f"zone=demand htf=[{zbot:.0f},{ztop:.0f}] "
                                       f"refined=[{rbot:.3f},{rtop:.3f}] rr={rr:.1f}"),
                })
                break

            elif zone["type"] == "supply":
                if not (zbot <= price <= ztop): continue
                if not bear:                    continue
                if high < rbot:                 continue
                if price > rtop:                continue
                stop   = rtop * (1 + buf)
                risk   = stop - price
                if risk <= 0:                   continue
                target = _prior_low(lows, p["target_skip"], p["target_lookback"])
                if target >= price:
                    target = price - risk * p["min_rr"]
                rr = (price - target) / risk
                if rr < p["min_rr"]:            continue
                qty = min(int(balance * p["risk_pct"] / risk),
                          int(balance * p["leverage"] / price))
                if qty <= 0:                    continue

                position = {"dir": "SHORT", "shares": qty, "entry": price,
                            "stop": stop, "target": target, "zone_type": "supply"}
                zone["consumed"]      = True
                zone["consumed_date"] = date_str
                trades.append({
                    "date": date_str, "time": time_str,
                    "action": "SELL", "dir": "SHORT", "shares": qty,
                    "price": round(price, 3), "stop": round(stop, 3),
                    "reason": "ZONE", "pnl": "",
                    "balance": round(balance, 2),
                    "signal_details": (f"zone=supply htf=[{zbot:.0f},{ztop:.0f}] "
                                       f"refined=[{rbot:.3f},{rtop:.3f}] rr={rr:.1f}"),
                })
                break

    closed = [t for t in trades if t["action"] == "CLOSE"]
    n = len(closed)
    print(f"  Zone Refine: {n} closed trades | W:{wins} L:{losses} | "
          f"P&L: ${total_pnl:+,.2f} | Balance: ${balance:,.2f}")

    state = {
        "ticker": TICKER, "capital": CAPITAL, "balance": round(balance, 2),
        "position": None, "zones": [], "zones_date": None,
        "total_trades": n, "total_pnl": round(total_pnl, 2),
        "wins": wins, "losses": losses,
    }
    return trades, state


# -- Entry point -------------------------------------------------------------

if __name__ == "__main__":
    print(f"\nReplaying {TICKER} Zone Refinement from {START_DATE} ...\n")

    # 1. Fetch 1H data + build zones (6 months for zone warmup)
    print("[1/2] Fetching 1H GC=F data (6 months) ...")
    end   = pd.Timestamp.now()
    start = end - pd.DateOffset(months=6)
    df1h  = _clean(yf.download(TICKER,
                               start=start.strftime("%Y-%m-%d"),
                               end=end.strftime("%Y-%m-%d"),
                               interval="1h", progress=False))
    df4h  = (df1h.resample("4h")
             .agg({"Open": "first", "High": "max", "Low": "min",
                   "Close": "last", "Volume": "sum"})
             .dropna())
    zones = detect_zones(df4h, df1h,
                         strength_bars=ZONE_P["strength_bars"],
                         strength_mult=ZONE_P["strength_mult"])
    d_c   = sum(1 for z in zones if z["type"] == "demand")
    s_c   = sum(1 for z in zones if z["type"] == "supply")
    print(f"      {len(df1h)} 1H bars | {len(zones)} zones ({d_c}D / {s_c}S)")

    # 2. Simulate Zone Refinement
    print("\n[2/2] Simulating Zone Refinement (1H) ...")
    zone_trades, zone_state = replay_zone(df1h, zones)

    # 3. Write files
    print("\nWriting output files ...")
    write_csv(DATA_DIR / "zone_trades.csv",  zone_trades)
    write_json(DATA_DIR / "zone_state.json", zone_state)

    print("\nDone.\n")
