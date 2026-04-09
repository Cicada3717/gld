"""
replay.py — Replay GC=F Zone Refinement from March 18 2026 to today.
Writes zone_trades.csv + zone_state.json so the dashboard shows
correct gold futures history from the start date.

All bugs fixed:
  - Stop checks use bar HIGH/LOW (not close)
  - Slippage included in position sizing (2x $0.50)
  - Slippage applied to exit price
  - Best-price tracking uses bar HIGH (LONG) / LOW (SHORT)

Optimized params:
  bos_slope_bars=8, min_rr=2.5, trail_activation=2.5R, trail_dist=0.15R
  max_trades_day=2
"""

import csv
import json
import os
from datetime import datetime, date
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from zone_refinement_backtest import detect_zones, _clean

# -- Config ------------------------------------------------------------------
TICKER      = "GC=F"
CAPITAL     = 10_000.0
START_DATE  = date(2026, 3, 18)
SLIPPAGE    = 0.50
DATA_DIR    = Path(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", Path(__file__).parent))
YF_CACHE_DIR = DATA_DIR / ".yf_cache"
YF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
yf.set_tz_cache_location(str(YF_CACHE_DIR))

PARAMS = dict(
    strength_bars=3, strength_mult=1.5,
    bos_ema=21,
    bos_slope_bars=8,        # OPTIMIZED
    stop_buffer=0.001,
    target_lookback=60, target_skip=5,
    min_rr=2.5,
    trail_activation_r=2.5,  # OPTIMIZED
    trail_distance_r=0.15,   # OPTIMIZED
    max_trades_day=2,        # OPTIMIZED
    risk_pct=0.02,
    leverage=5.0,
    commission=0.0001,
)

TRADE_FIELDS = [
    "date", "time", "action", "dir", "shares", "price",
    "stop", "reason", "pnl", "balance", "signal_details",
]

# -- Pattern-recognition entry filters (from analyze_losses.py) --------------
# RSI filter removed: all RSI buckets positive EV at 2.5 R:R
FILTER_ATR_LOW   = 0.85
FILTER_ATR_HIGH  = 1.20
FILTER_BODY_LOW  = 0.30
FILTER_BODY_HIGH = 0.70
FILTER_BAD_HOURS  = {7, 10, 11, 12, 15, 19}
FILTER_TREND_BARS = 72      # LONGs only: 72H crash filter
FILTER_TREND_PCT  = -0.015  # block LONG when 72H drop > 1.5% of price


def _entry_fill(raw_price, direction):
    return raw_price + SLIPPAGE if direction == "LONG" else raw_price - SLIPPAGE


# -- Indicators --------------------------------------------------------------

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


def _atr14(highs, lows, closes, period=14):
    h = np.array(highs[-period - 2:])
    l = np.array(lows[-period - 2:])
    c = np.array(closes[-period - 2:])
    if len(h) < 2:
        return 1.0
    tr = np.maximum(h[1:] - l[1:],
                    np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    return float(np.mean(tr[-period:])) if len(tr) >= period else float(np.mean(tr))


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

def replay_zone(df1h, zones):
    p            = PARAMS
    balance      = CAPITAL
    position     = None
    trades       = []
    wins = losses = 0
    total_pnl    = 0.0
    replay_start = pd.Timestamp(START_DATE.strftime("%Y-%m-%d"))
    zone_list    = [dict(z) for z in zones]
    last_processed_bar = None
    trades_today_date = None
    trades_today_count = 0

    for ts, row in df1h[df1h.index >= replay_start].iterrows():
        dt = ts.to_pydatetime()
        # Skip Saturday and Sunday pre-market
        if dt.weekday() == 5:
            continue
        if dt.weekday() == 6 and dt.hour < 18:
            continue
        if dt.hour == 17:
            continue

        last_processed_bar = ts

        date_str = ts.strftime("%Y-%m-%d")
        time_str = ts.strftime("%H:%M")
        if trades_today_date != date_str:
            trades_today_date = date_str
            trades_today_count = 0

        hist   = df1h[df1h.index <= ts]
        closes = hist["Close"].tolist()
        highs  = hist["High"].tolist()
        lows   = hist["Low"].tolist()
        price  = float(row["Close"])
        high   = float(row["High"])
        low    = float(row["Low"])

        # -- Manage open position ----------------------------------------
        if position:
            initial_risk   = position.get("initial_risk", abs(position["entry"] - position["stop"]))
            position["initial_risk"] = initial_risk
            trail_activate = initial_risk * p["trail_activation_r"]
            trail_dist     = initial_risk * p["trail_distance_r"]

            if position["dir"] == "LONG":
                # FIX: track best using bar HIGH
                best = position.get("best_price", position["entry"])
                if high > best:
                    position["best_price"] = high
                    best = high
                if best >= position["entry"] + trail_activate:
                    trail_stop = best - trail_dist
                    if trail_stop > position["stop"]:
                        position["stop"] = trail_stop
            else:
                # FIX: track best using bar LOW
                best = position.get("best_price", position["entry"])
                if low < best:
                    position["best_price"] = low
                    best = low
                if best <= position["entry"] - trail_activate:
                    trail_stop = best + trail_dist
                    if trail_stop < position["stop"]:
                        position["stop"] = trail_stop

            # FIX: use bar HIGH/LOW for stop/target checks
            hit_stop   = (position["dir"] == "LONG"  and low  <= position["stop"]) or \
                         (position["dir"] == "SHORT" and high >= position["stop"])
            hit_target = (position["dir"] == "LONG"  and high >= position["target"]) or \
                         (position["dir"] == "SHORT" and low  <= position["target"])

            if not hit_stop and not hit_target:
                continue

            exit_raw  = position["stop"] if hit_stop else position["target"]
            # FIX: apply slippage to exit
            exit_px   = exit_raw - SLIPPAGE if position["dir"] == "LONG" else exit_raw + SLIPPAGE
            trail_active = position.get("best_price") is not None and (
                (position["dir"] == "LONG"  and position["best_price"] >= position["entry"] + trail_activate) or
                (position["dir"] == "SHORT" and position["best_price"] <= position["entry"] - trail_activate)
            )
            reason = "TRAIL_STOP" if (hit_stop and trail_active) else ("STOP" if hit_stop else "TARGET")

            pnl  = (exit_px - position["entry"]) * position["shares"] if position["dir"] == "LONG" \
                   else (position["entry"] - exit_px) * position["shares"]
            comm = (position["entry"] + exit_px) * position["shares"] * p["commission"]
            net  = pnl - comm
            balance += net; total_pnl += net
            if net > 0: wins   += 1
            else:       losses += 1

            trades.append({
                "date": date_str, "time": time_str,
                "action": "CLOSE", "dir": position["dir"],
                "shares": position["shares"], "price": round(exit_px, 3),
                "stop": round(position["stop"], 3), "reason": reason,
                "pnl": round(net, 2), "balance": round(balance, 2),
                "signal_details": (
                    f"entry={position['entry']:.3f} trigger={exit_raw:.3f} "
                    f"comm={comm:.4f} zone={position.get('zone_type','?')}"
                ),
            })
            position = None
            continue

        # -- Zone scan ---------------------------------------------------
        bull     = _bos_bullish(closes, p["bos_ema"], p["bos_slope_bars"])
        bear     = _bos_bearish(closes, p["bos_ema"], p["bos_slope_bars"])
        trend_20 = closes[-1] - closes[-20] if len(closes) >= 20 else 0

        if trades_today_count >= p["max_trades_day"]:
            continue

        # Pre-compute filter values
        n_bars        = len(closes)
        trend_72h     = closes[-1] - closes[-FILTER_TREND_BARS] \
                        if n_bars >= FILTER_TREND_BARS else closes[-1] - closes[0]
        trend_72h_pct = trend_72h / closes[-1] if closes[-1] > 0 else 0
        f_atr       = _atr14(highs, lows, closes)
        f_atr_avg   = _atr14(highs[-30:], lows[-30:], closes[-30:], 20) \
                      if len(closes) >= 22 else f_atr
        f_atr_ratio = f_atr / f_atr_avg if f_atr_avg > 0 else 1.0
        f_body_raw  = float(row["Close"]) - float(row["Open"])
        f_body_pct  = abs(f_body_raw) / f_atr if f_atr > 0 else 0.0
        f_body_bull = f_body_raw >= 0

        for zone in zone_list:
            if zone.get("consumed"):
                continue
            formed = zone["formed_at"]
            if not isinstance(formed, datetime):
                formed = datetime.fromisoformat(str(formed))
            if pd.Timestamp(formed) >= ts:
                continue

            ztop = zone["htf_top"]; zbot = zone["htf_bottom"]
            rtop = zone["refined_top"]; rbot = zone["refined_bottom"]
            buf  = p["stop_buffer"]

            if zone["type"] == "demand":
                if not (zbot <= price <= ztop): continue
                if not bull:                    continue
                if low > rtop:                  continue
                if price < rbot:                continue
                if trend_20 < 0:               continue
                stop = rbot * (1 - buf)
                risk = price - stop
                if risk <= 0:                   continue
                target = _prior_high(highs, p["target_skip"], p["target_lookback"])
                if target <= price:
                    target = price + risk * p["min_rr"]
                if (target - price) / risk < p["min_rr"]: continue
                # FIX: include slippage in position sizing
                actual_risk = risk + 2 * SLIPPAGE
                qty = min(int(balance * p["risk_pct"] / actual_risk),
                          int(balance * p["leverage"] / price))
                if qty <= 0: continue

                # Entry filters
                signed_body = f_body_pct if f_body_bull else -f_body_pct
                if dt.hour in FILTER_BAD_HOURS:
                    break
                if not (FILTER_ATR_LOW <= f_atr_ratio <= FILTER_ATR_HIGH):
                    break
                if FILTER_BODY_LOW <= signed_body < FILTER_BODY_HIGH:
                    break
                if trend_72h_pct < FILTER_TREND_PCT:
                    break

                entry_fill = _entry_fill(price, "LONG")
                position = {
                    "dir": "LONG",
                    "shares": qty,
                    "entry": entry_fill,
                    "entry_trigger": price,
                    "stop": stop,
                    "target": target,
                    "zone_type": "demand",
                    "initial_risk": abs(entry_fill - stop),
                }
                zone["consumed"] = True; zone["consumed_date"] = date_str
                trades_today_count += 1
                trades.append({
                    "date": date_str, "time": time_str,
                    "action": "BUY", "dir": "LONG", "shares": qty,
                    "price": round(entry_fill, 3), "stop": round(stop, 3),
                    "reason": "ZONE", "pnl": "",
                    "balance": round(balance, 2),
                    "signal_details": (
                        f"trigger={price:.3f} zone=demand htf=[{zbot:.2f},{ztop:.2f}] "
                        f"refined=[{rbot:.3f},{rtop:.3f}] rr={(target-price)/risk:.1f}"
                    ),
                })
                break

            elif zone["type"] == "supply":
                if not (zbot <= price <= ztop): continue
                if not bear:                    continue
                if high < rbot:                 continue
                if price > rtop:                continue
                if trend_20 > 0:               continue
                stop = rtop * (1 + buf)
                risk = stop - price
                if risk <= 0:                   continue
                target = _prior_low(lows, p["target_skip"], p["target_lookback"])
                if target >= price:
                    target = price - risk * p["min_rr"]
                if (price - target) / risk < p["min_rr"]: continue
                # FIX: include slippage in position sizing
                actual_risk = risk + 2 * SLIPPAGE
                qty = min(int(balance * p["risk_pct"] / actual_risk),
                          int(balance * p["leverage"] / price))
                if qty <= 0: continue

                # Entry filters
                signed_body = f_body_pct if not f_body_bull else -f_body_pct
                if dt.hour in FILTER_BAD_HOURS:
                    break
                if not (FILTER_ATR_LOW <= f_atr_ratio <= FILTER_ATR_HIGH):
                    break
                if FILTER_BODY_LOW <= signed_body < FILTER_BODY_HIGH:
                    break

                entry_fill = _entry_fill(price, "SHORT")
                position = {
                    "dir": "SHORT",
                    "shares": qty,
                    "entry": entry_fill,
                    "entry_trigger": price,
                    "stop": stop,
                    "target": target,
                    "zone_type": "supply",
                    "initial_risk": abs(entry_fill - stop),
                }
                zone["consumed"] = True; zone["consumed_date"] = date_str
                trades_today_count += 1
                trades.append({
                    "date": date_str, "time": time_str,
                    "action": "SELL", "dir": "SHORT", "shares": qty,
                    "price": round(entry_fill, 3), "stop": round(stop, 3),
                    "reason": "ZONE", "pnl": "",
                    "balance": round(balance, 2),
                    "signal_details": (
                        f"trigger={price:.3f} zone=supply htf=[{zbot:.2f},{ztop:.2f}] "
                        f"refined=[{rbot:.3f},{rtop:.3f}] rr={(price-target)/risk:.1f}"
                    ),
                })
                break

    closed = [t for t in trades if t["action"] == "CLOSE"]
    n = len(closed)
    roi = (balance - CAPITAL) / CAPITAL * 100
    wr  = wins / n * 100 if n else 0
    print(f"  GC=F Zone Replay: {n} trades | W:{wins} L:{losses} | "
          f"WR:{wr:.1f}% | ROI:{roi:+.2f}% | Balance:${balance:,.2f}")

    live_pos = None
    if position:
        live_pos = {
            "dir":          position["dir"],
            "shares":       position["shares"],
            "entry":        position["entry"],
            "entry_trigger": position.get("entry_trigger"),
            "stop":         position["stop"],
            "target":       position["target"],
            "zone_type":    position.get("zone_type", "?"),
            "initial_risk": position.get("initial_risk", abs(position["entry"] - position["stop"])),
            "entry_time":   f"{trades[-1]['date']} {trades[-1]['time']}" if trades else "1970-01-01 00:00",
        }
        print(f"  Open position carried forward: {live_pos['dir']} "
              f"{live_pos['shares']}sh @ ${live_pos['entry']:.3f}")

    state = {
        "ticker": TICKER, "capital": CAPITAL, "balance": round(balance, 2),
        "position": live_pos, "zones": [], "zones_date": None,
        "last_processed_bar": str(last_processed_bar) if last_processed_bar is not None else None,
        "trades_today_date": trades_today_date,
        "trades_today_count": trades_today_count,
        "total_trades": n, "total_pnl": round(total_pnl, 2),
        "wins": wins, "losses": losses,
    }
    return trades, state


# -- Entry point -------------------------------------------------------------

if __name__ == "__main__":
    print(f"\n{'='*60}")
    print(f"  GC=F Zone Replay  |  {START_DATE} to today")
    print(f"  Capital: ${CAPITAL:,.0f}  |  Params: optimized")
    print(f"{'='*60}\n")

    print("[1/2] Fetching GC=F 1H data (6 months for zone warmup)...")
    end   = pd.Timestamp.now()
    start = end - pd.DateOffset(months=6)
    df1h  = _clean(yf.download(TICKER,
                               start=start.strftime("%Y-%m-%d"),
                               end=end.strftime("%Y-%m-%d"),
                               interval="1h", progress=False))
    if df1h.empty:
        raise RuntimeError(f"No 1H data for {TICKER}. Check ticker and yfinance.")

    df4h  = (df1h.resample("4h")
             .agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"})
             .dropna())
    zones = detect_zones(df4h, df1h,
                         strength_bars=PARAMS["strength_bars"],
                         strength_mult=PARAMS["strength_mult"])
    print(f"  {len(df1h)} bars | {len(zones)} zones detected\n")

    print("[2/2] Replaying trades from March 18...")
    zone_trades, zone_state = replay_zone(df1h, zones)

    print("\nWriting output files...")
    write_csv(DATA_DIR / "zone_trades.csv",  zone_trades)
    write_json(DATA_DIR / "zone_state.json", zone_state)
    print("\nDone.\n")
