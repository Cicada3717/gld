"""
replay.py — Simulate ClaudeAPEX v12 (5m) and Zone Refinement (1H) on real
GC=F data from March 18 2026 to today.  Writes:
  paper_trades.csv / paper_state.json
  zone_trades.csv  / zone_state.json

Run once locally (or at Railway deploy) to populate dashboard with
historical replay results.  Always overwrites existing files.
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

# ── Config ────────────────────────────────────────────────────────────────────
TICKER      = "GC=F"
CAPITAL     = 10000.0
START_DATE  = date(2026, 3, 18)
DATA_DIR    = Path(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", Path(__file__).parent))

APEX_P = dict(
    atr_short=10, atr_long=50, vei_max=1.25,
    ema_fast=9, ema_slow=21, atr_period=14,
    gap_min=0.0010, entry_start=2, entry_end=25,
    eod_bar=72, stop_mult=3.0, risk_pct=0.02, leverage=5.0,
)
ZONE_P = dict(
    strength_bars=3, strength_mult=1.5,
    bos_ema=21, bos_slope_bars=3,
    stop_buffer=0.001, target_lookback=60, target_skip=5,
    min_rr=3.0, risk_pct=0.02, leverage=5.0, commission=0.0001,
)

TRADE_FIELDS = [
    "date", "time", "action", "dir", "shares", "price",
    "stop", "reason", "pnl", "balance", "signal_details",
]


# ── Indicator helpers ─────────────────────────────────────────────────────────

def _ema(values, period):
    if len(values) < period:
        return values[-1] if values else 0.0
    k = 2 / (period + 1)
    e = float(np.mean(values[:period]))
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


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


def _atr(highs, lows, closes, period):
    if len(closes) < 2 or len(highs) < period:
        return 0.0
    trs = [max(highs[i] - lows[i],
               abs(highs[i] - closes[i - 1]),
               abs(lows[i] - closes[i - 1]))
           for i in range(1, len(closes))]
    if len(trs) < period:
        return float(np.mean(trs)) if trs else 0.0
    a = float(np.mean(trs[:period]))
    for v in trs[period:]:
        a = (a * (period - 1) + v) / period
    return a


def _vwap(bars):
    cpv = cv = 0.0
    for b in bars:
        tp = (b["h"] + b["l"] + b["c"]) / 3
        v  = max(b["v"], 1)
        cpv += tp * v
        cv  += v
    return cpv / cv if cv > 0 else bars[-1]["c"]


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


# ── I/O ───────────────────────────────────────────────────────────────────────

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


# ── ClaudeAPEX v12 replay (5m) ────────────────────────────────────────────────

def replay_apex(df5m):
    p        = APEX_P
    balance  = CAPITAL
    position = None
    trades   = []
    wins = losses = 0
    total_pnl = 0.0

    df5m = df5m.copy()
    df5m["_date"] = df5m.index.date
    replay_dates  = sorted(d for d in df5m["_date"].unique() if d >= START_DATE)

    for today in replay_dates:
        today_str     = today.strftime("%Y-%m-%d")
        session_start = pd.Timestamp(f"{today_str} 09:30:00")
        session_end   = pd.Timestamp(f"{today_str} 16:00:00")

        day_mask = (df5m.index >= session_start) & (df5m.index < session_end)
        df_today = df5m[day_mask]
        if df_today.empty:
            continue

        # Prior close — last bar before today (our new fix: date < today)
        prev_mask = df5m["_date"] < today
        if not prev_mask.any():
            continue
        prior_close = float(df5m[prev_mask]["Close"].iloc[-1])

        # Force-close any carry-over position at prior_close
        if position:
            px = prior_close
            pnl  = (px - position["entry"]) * position["shares"] if position["dir"] == "LONG" \
                   else (position["entry"] - px) * position["shares"]
            comm = (position["entry"] + px) * position["shares"] * 0.0001
            net  = pnl - comm
            balance   += net
            total_pnl += net
            if net > 0: wins  += 1
            else:       losses += 1
            trades.append({
                "date": today_str, "time": "09:30",
                "action": "CLOSE", "dir": position["dir"],
                "shares": position["shares"], "price": round(px, 2),
                "stop": round(position["trail"], 2), "reason": "NEW_DAY",
                "pnl": round(net, 2), "balance": round(balance, 2),
                "signal_details": f"entry={position['entry']:.2f} comm={comm:.2f}",
            })
            position = None

        bar_num      = 0
        traded_today = False

        for ts, row in df_today.iterrows():
            bar_num += 1
            price   = float(row["Close"])

            # Indicators on all history up to this bar
            hist    = df5m[df5m.index <= ts]
            closes  = hist["Close"].tolist()
            highs   = hist["High"].tolist()
            lows    = hist["Low"].tolist()

            atr_val = _atr(highs, lows, closes, p["atr_period"])
            atr_s   = _atr(highs, lows, closes, p["atr_short"])
            atr_l   = _atr(highs, lows, closes, p["atr_long"])
            vei     = atr_s / atr_l if atr_l > 0 else 1.0
            ema_f   = _ema(closes, p["ema_fast"])
            ema_s_  = _ema(closes, p["ema_slow"])

            # Session VWAP
            sf = df_today[df_today.index <= ts]
            vwap_val = _vwap([{"h": r["High"], "l": r["Low"], "c": r["Close"],
                               "v": r["Volume"]} for _, r in sf.iterrows()])

            # ── Manage open position ──────────────────────────────────
            if position:
                eod = bar_num >= p["eod_bar"] or ts >= session_end - pd.Timedelta(minutes=5)
                if eod:
                    pnl  = (price - position["entry"]) * position["shares"] if position["dir"] == "LONG" \
                           else (position["entry"] - price) * position["shares"]
                    comm = (position["entry"] + price) * position["shares"] * 0.0001
                    net  = pnl - comm
                    balance += net; total_pnl += net
                    if net > 0: wins  += 1
                    else:       losses += 1
                    trades.append({
                        "date": today_str, "time": ts.strftime("%H:%M"),
                        "action": "CLOSE", "dir": position["dir"],
                        "shares": position["shares"], "price": round(price, 2),
                        "stop": round(position["trail"], 2), "reason": "EOD",
                        "pnl": round(net, 2), "balance": round(balance, 2),
                        "signal_details": f"entry={position['entry']:.2f} comm={comm:.2f}",
                    })
                    position = None
                    break

                if position["dir"] == "LONG":
                    new_trail = price - atr_val * p["stop_mult"]
                    if new_trail > position["trail"]:
                        position["trail"] = new_trail
                    if price <= position["trail"]:
                        px   = position["trail"]
                        pnl  = (px - position["entry"]) * position["shares"]
                        comm = (position["entry"] + px) * position["shares"] * 0.0001
                        net  = pnl - comm
                        balance += net; total_pnl += net
                        if net > 0: wins  += 1
                        else:       losses += 1
                        trades.append({
                            "date": today_str, "time": ts.strftime("%H:%M"),
                            "action": "CLOSE", "dir": "LONG",
                            "shares": position["shares"], "price": round(px, 2),
                            "stop": round(px, 2), "reason": "STOP",
                            "pnl": round(net, 2), "balance": round(balance, 2),
                            "signal_details": f"entry={position['entry']:.2f} comm={comm:.2f}",
                        })
                        position = None
                else:
                    new_trail = price + atr_val * p["stop_mult"]
                    if new_trail < position["trail"]:
                        position["trail"] = new_trail
                    if price >= position["trail"]:
                        px   = position["trail"]
                        pnl  = (position["entry"] - px) * position["shares"]
                        comm = (position["entry"] + px) * position["shares"] * 0.0001
                        net  = pnl - comm
                        balance += net; total_pnl += net
                        if net > 0: wins  += 1
                        else:       losses += 1
                        trades.append({
                            "date": today_str, "time": ts.strftime("%H:%M"),
                            "action": "CLOSE", "dir": "SHORT",
                            "shares": position["shares"], "price": round(px, 2),
                            "stop": round(px, 2), "reason": "STOP",
                            "pnl": round(net, 2), "balance": round(balance, 2),
                            "signal_details": f"entry={position['entry']:.2f} comm={comm:.2f}",
                        })
                        position = None
                continue

            # ── Entry scan ────────────────────────────────────────────
            if traded_today:
                continue
            if bar_num < p["entry_start"] or bar_num > p["entry_end"]:
                continue
            if vei >= p["vei_max"] or prior_close <= 0 or atr_val <= 0:
                continue

            gap      = (price - prior_close) / prior_close
            ema_bull = ema_f > ema_s_

            risk_sh = int(balance * p["risk_pct"] / (atr_val * p["stop_mult"]))
            lev_sh  = int(balance * p["leverage"] / price)
            qty     = min(risk_sh, lev_sh)
            if qty <= 0:
                continue

            if gap >= p["gap_min"] and price > vwap_val and ema_bull:
                trail = price - atr_val * p["stop_mult"]
                position     = {"dir": "LONG",  "shares": qty, "entry": price, "trail": trail}
                traded_today = True
                trades.append({
                    "date": today_str, "time": ts.strftime("%H:%M"),
                    "action": "BUY", "dir": "LONG", "shares": qty,
                    "price": round(price, 2), "stop": round(trail, 2),
                    "reason": "SIGNAL", "pnl": "",
                    "balance": round(balance, 2),
                    "signal_details": f"gap={gap*100:+.2f}% vwap={vwap_val:.2f} vei={vei:.3f} atr={atr_val:.2f}",
                })
            elif gap <= -p["gap_min"] and price < vwap_val and not ema_bull:
                trail = price + atr_val * p["stop_mult"]
                position     = {"dir": "SHORT", "shares": qty, "entry": price, "trail": trail}
                traded_today = True
                trades.append({
                    "date": today_str, "time": ts.strftime("%H:%M"),
                    "action": "SELL", "dir": "SHORT", "shares": qty,
                    "price": round(price, 2), "stop": round(trail, 2),
                    "reason": "SIGNAL", "pnl": "",
                    "balance": round(balance, 2),
                    "signal_details": f"gap={gap*100:+.2f}% vwap={vwap_val:.2f} vei={vei:.3f} atr={atr_val:.2f}",
                })

    # EOD close any remaining open position
    if position:
        px   = float(df5m["Close"].iloc[-1])
        pnl  = (px - position["entry"]) * position["shares"] if position["dir"] == "LONG" \
               else (position["entry"] - px) * position["shares"]
        comm = (position["entry"] + px) * position["shares"] * 0.0001
        net  = pnl - comm
        balance += net; total_pnl += net
        if net > 0: wins  += 1
        else:       losses += 1
        last_ts = df5m.index[-1]
        trades.append({
            "date": last_ts.strftime("%Y-%m-%d"), "time": last_ts.strftime("%H:%M"),
            "action": "CLOSE", "dir": position["dir"],
            "shares": position["shares"], "price": round(px, 2),
            "stop": round(position["trail"], 2), "reason": "EOD",
            "pnl": round(net, 2), "balance": round(balance, 2),
            "signal_details": f"entry={position['entry']:.2f} comm={comm:.2f}",
        })

    closed = [t for t in trades if t["action"] == "CLOSE"]
    n = len(closed)
    print(f"  ClaudeAPEX:  {n} closed trades | W:{wins} L:{losses} | "
          f"P&L: ${total_pnl:+,.2f} | Balance: ${balance:,.2f}")

    state = {
        "ticker": TICKER, "capital": CAPITAL, "balance": round(balance, 2),
        "position": None, "today": None, "bar_count": 0,
        "prior_close": 0, "traded_today": False,
        "total_trades": n, "total_pnl": round(total_pnl, 2),
        "wins": wins, "losses": losses,
    }
    return trades, state


# ── Zone Refinement replay (1H) ───────────────────────────────────────────────

def replay_zone(df1h, zones):
    p         = ZONE_P
    balance   = CAPITAL
    position  = None
    trades    = []
    wins = losses = 0
    total_pnl = 0.0

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

        # ── Manage open position ──────────────────────────────────────
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
            position = None
            continue

        # ── Zone scan ─────────────────────────────────────────────────
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


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\nReplaying {TICKER} strategies from {START_DATE} …\n")

    # 1. Fetch 5m data (30d for ClaudeAPEX warmup + replay)
    print("[1/4] Fetching 5m GC=F data (30d) …")
    df5m = _clean(yf.download(TICKER, period="30d", interval="5m", progress=False))
    print(f"      {len(df5m)} 5m bars")

    # 2. Fetch 1H data + build zones (6 months for zone warmup)
    print("[2/4] Fetching 1H GC=F data (6 months) …")
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
    zones = detect_zones(df4h, df1h, strength_bars=3, strength_mult=1.5)
    d_c   = sum(1 for z in zones if z["type"] == "demand")
    s_c   = sum(1 for z in zones if z["type"] == "supply")
    print(f"      {len(df1h)} 1H bars | {len(zones)} zones ({d_c}D / {s_c}S)")

    # 3. Simulate ClaudeAPEX
    print("\n[3/4] Simulating ClaudeAPEX v12 (5m) …")
    apex_trades, apex_state = replay_apex(df5m)

    # 4. Simulate Zone Refinement
    print("\n[4/4] Simulating Zone Refinement (1H) …")
    zone_trades, zone_state = replay_zone(df1h, zones)

    # 5. Write files
    print("\nWriting output files …")
    write_csv(DATA_DIR / "paper_trades.csv", apex_trades)
    write_json(DATA_DIR / "paper_state.json", apex_state)
    write_csv(DATA_DIR / "zone_trades.csv",  zone_trades)
    write_json(DATA_DIR / "zone_state.json", zone_state)

    print("\nDone.\n")
