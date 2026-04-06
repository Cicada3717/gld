"""
replay.py — Simulate Zone Refinement + LFV confluence (1H) on real GC=F data
from March 18 2026 to today.  Writes:
  zone_trades.csv  / zone_state.json

Zone entries are filtered by LFV confluence (liquidity sweep, AVWAP, volume
profile).  At least 1 of 3 must confirm before a zone trade fires.
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
YF_CACHE_DIR = DATA_DIR / ".yf_cache"
YF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
yf.set_tz_cache_location(str(YF_CACHE_DIR))

ZONE_P = dict(
    strength_bars=3, strength_mult=1.5,
    bos_ema=21, bos_slope_bars=3,
    stop_buffer=0.001, target_lookback=60, target_skip=5,
    min_rr=3.0, risk_pct=0.02, leverage=5.0, commission=0.0001,
)

# LFV confluence params (tuned for 1H gold futures)
LFV_P = dict(
    swing_n=3,              # pivot lookback (bars each side)
    sweep_min_atr=0.3,      # min sweep distance in ATR units
    avwap_tolerance=0.01,   # 1% fair value tolerance
    vp_lookback=80,         # volume profile window (bars)
    vp_buckets=50,          # histogram buckets
    vah_val_pct=0.75,       # value area percentage
    lvn_ratio=0.25,         # low volume node threshold
    min_confluence=0,       # 0 = disabled (trend filter is the primary gate)
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


# -- LFV confluence helpers --------------------------------------------------

def _atr_series(high, low, close, period=14):
    """Wilder ATR as a full-length array (NaN-padded)."""
    tr = np.maximum(high[1:] - low[1:],
         np.maximum(np.abs(high[1:] - close[:-1]),
                    np.abs(low[1:]  - close[:-1])))
    atr = np.full(len(high), np.nan)
    if len(tr) < period:
        return atr
    atr[period] = tr[:period].mean()
    for i in range(period + 1, len(tr) + 1):
        atr[i] = (atr[i-1] * (period - 1) + tr[i-1]) / period
    return atr


def _swing_pivots(high, low, n):
    """Return confirmed swing high/low indices and prices."""
    sh_idx, sh_px, sl_idx, sl_px = [], [], [], []
    for i in range(n, len(high) - n):
        if high[i] == max(high[i-n:i+n+1]):
            sh_idx.append(i); sh_px.append(high[i])
        if low[i]  == min(low[i-n:i+n+1]):
            sl_idx.append(i); sl_px.append(low[i])
    return sh_idx, sh_px, sl_idx, sl_px


def _avwap_from(idx_anchor, tp, volume):
    """Anchored VWAP from bar index to end."""
    cpv = cv = 0.0
    for i in range(idx_anchor, len(tp)):
        cpv += tp[i] * volume[i]
        cv  += volume[i]
    return cpv / cv if cv > 0 else tp[-1]


def _volume_profile(high, low, tp, volume, buckets=50, vah_val_pct=0.75, lvn_ratio=0.25):
    """Compute POC, VAH, VAL, and LVN list from price/volume arrays."""
    p_min, p_max = low.min(), high.max()
    if p_max <= p_min:
        return None
    bsz  = (p_max - p_min) / buckets
    hist = np.zeros(buckets)
    bpx  = np.array([p_min + (i + 0.5) * bsz for i in range(buckets)])
    for t, v in zip(tp, volume):
        idx = int((t - p_min) / bsz)
        idx = max(0, min(buckets - 1, idx))
        hist[idx] += v
    poc_i  = int(np.argmax(hist))
    poc_px = bpx[poc_i]
    total  = hist.sum()
    tgt    = total * vah_val_pct
    lo_i = hi_i = poc_i
    va_vol = hist[poc_i]
    while va_vol < tgt:
        can_up = hi_i + 1 < buckets
        can_dn = lo_i - 1 >= 0
        if not can_up and not can_dn:
            break
        go_up = (hist[hi_i+1] >= hist[lo_i-1]) if (can_up and can_dn) else can_up
        if go_up:
            hi_i += 1; va_vol += hist[hi_i]
        else:
            lo_i -= 1; va_vol += hist[lo_i]
    vah = bpx[hi_i]
    val = bpx[lo_i]
    nonzero = hist[hist > 0]
    mean_v  = nonzero.mean() if len(nonzero) else 1.0
    lvn_px  = [bpx[i] for i in range(buckets)
               if hist[i] > 0 and hist[i] < lvn_ratio * mean_v]
    return dict(poc=poc_px, vah=vah, val=val, lvn_px=lvn_px, bsz=bsz)


def _check_lfv_confluence(direction, price, high, low, hist_high, hist_low,
                           hist_close, hist_volume, bar_idx):
    """
    Check LFV confluence for a zone entry.
    Returns (score, details) where score is 0-3.
    """
    lp = LFV_P
    n  = lp["swing_n"]

    h_arr = np.array(hist_high)
    l_arr = np.array(hist_low)
    c_arr = np.array(hist_close)
    v_arr = np.array(hist_volume)
    tp    = (h_arr + l_arr + c_arr) / 3.0

    atr_arr = _atr_series(h_arr, l_arr, c_arr)
    atr = atr_arr[bar_idx] if bar_idx < len(atr_arr) and not np.isnan(atr_arr[bar_idx]) else None
    if atr is None or atr == 0:
        return 0, "no_atr"

    sh_idx, sh_px, sl_idx, sl_px = _swing_pivots(h_arr[:bar_idx+1], l_arr[:bar_idx+1], n)

    swept = False
    avwap_ok = False
    vp_ok = False
    details = []
    min_sweep = atr * lp["sweep_min_atr"]

    # 1. Liquidity sweep check
    if direction == "LONG":
        for i in range(len(sl_idx) - 1, max(len(sl_idx) - 4, -1), -1):
            level = sl_px[i]
            if low < level and price > level and (level - low) >= min_sweep:
                swept = True
                details.append(f"sweep={level:.1f}")
                break
    else:  # SHORT
        for i in range(len(sh_idx) - 1, max(len(sh_idx) - 4, -1), -1):
            level = sh_px[i]
            if high > level and price < level and (high - level) >= min_sweep:
                swept = True
                details.append(f"sweep={level:.1f}")
                break

    # 2. AVWAP proximity check
    if direction == "LONG" and sh_idx:
        avwap = _avwap_from(sh_idx[-1], tp, v_arr)
        if price <= avwap * (1 + lp["avwap_tolerance"]):
            avwap_ok = True
            details.append(f"avwap={avwap:.1f}")
    elif direction == "SHORT" and sl_idx:
        avwap = _avwap_from(sl_idx[-1], tp, v_arr)
        if price >= avwap * (1 - lp["avwap_tolerance"]):
            avwap_ok = True
            details.append(f"avwap={avwap:.1f}")

    # 3. Volume profile check
    vp_start = max(0, bar_idx - lp["vp_lookback"])
    vp = _volume_profile(
        h_arr[vp_start:bar_idx+1], l_arr[vp_start:bar_idx+1],
        tp[vp_start:bar_idx+1], v_arr[vp_start:bar_idx+1],
        buckets=lp["vp_buckets"], vah_val_pct=lp["vah_val_pct"],
        lvn_ratio=lp["lvn_ratio"],
    )
    if vp:
        at_lvn = any(abs(price - lvn) <= vp["bsz"] for lvn in vp["lvn_px"])
        if direction == "LONG":
            at_boundary = price <= vp["val"] + vp["bsz"]
        else:
            at_boundary = price >= vp["vah"] - vp["bsz"]
        if at_lvn or at_boundary:
            vp_ok = True
            tag = "LVN" if at_lvn else ("VAL" if direction == "LONG" else "VAH")
            details.append(f"vp={tag} poc={vp['poc']:.1f}")

    score = sum([swept, avwap_ok, vp_ok])
    return score, " ".join(details) if details else "none"


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
            # Trailing stop: activates at 1R profit, trails 0.5R behind best
            initial_risk = position.get("initial_risk", abs(position["entry"] - position["stop"]))
            position["initial_risk"] = initial_risk
            trail_dist = initial_risk * 0.5

            if position["dir"] == "LONG":
                best = position.get("best_price", position["entry"])
                if price > best:
                    position["best_price"] = price
                    best = price
                if best >= position["entry"] + initial_risk:
                    trail_stop = best - trail_dist
                    if trail_stop > position["stop"]:
                        position["stop"] = trail_stop
            else:  # SHORT
                best = position.get("best_price", position["entry"])
                if price < best:
                    position["best_price"] = price
                    best = price
                if best <= position["entry"] - initial_risk:
                    trail_stop = best + trail_dist
                    if trail_stop < position["stop"]:
                        position["stop"] = trail_stop

            hit_stop   = (position["dir"] == "LONG"  and price <= position["stop"]) or \
                         (position["dir"] == "SHORT" and price >= position["stop"])
            hit_target = (position["dir"] == "LONG"  and price >= position["target"]) or \
                         (position["dir"] == "SHORT" and price <= position["target"])
            if not hit_stop and not hit_target:
                continue

            exit_px = position["stop"] if hit_stop else position["target"]
            is_trail = hit_stop and position.get("best_price") is not None and (
                (position["dir"] == "LONG"  and position["best_price"] >= position["entry"] + initial_risk) or
                (position["dir"] == "SHORT" and position["best_price"] <= position["entry"] - initial_risk)
            )
            reason  = "TRAIL_STOP" if is_trail else ("STOP" if hit_stop else "TARGET")
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
            # Note: no zone age filter in replay — zones are pre-computed once
            # (live trader refreshes zones daily so age filter applies there)

            ztop = zone["htf_top"]
            zbot = zone["htf_bottom"]
            rtop = zone["refined_top"]
            rbot = zone["refined_bottom"]
            buf  = p["stop_buffer"]

            # Bar index in the full df for LFV lookups
            bar_idx = len(hist) - 1
            volumes = hist["Volume"].tolist()

            # 20-bar trend filter: only trade WITH trend direction
            trend_20 = closes[-1] - closes[-20] if len(closes) >= 20 else 0

            if zone["type"] == "demand":
                if not (zbot <= price <= ztop): continue
                if not bull:                    continue
                if low > rtop:                  continue
                if price < rbot:                continue
                if trend_20 < 0:               continue   # trend filter: skip LONG in downtrend
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

                # LFV confluence gate
                score, lfv_detail = _check_lfv_confluence(
                    "LONG", price, high, low, highs, lows, closes, volumes, bar_idx)
                if score < LFV_P["min_confluence"]:
                    continue

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
                                       f"refined=[{rbot:.3f},{rtop:.3f}] rr={rr:.1f} "
                                       f"lfv={score}/3 {lfv_detail}"),
                })
                break

            elif zone["type"] == "supply":
                if not (zbot <= price <= ztop): continue
                if not bear:                    continue
                if high < rbot:                 continue
                if price > rtop:                continue
                if trend_20 > 0:               continue   # trend filter: skip SHORT in uptrend
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

                # LFV confluence gate
                score, lfv_detail = _check_lfv_confluence(
                    "SHORT", price, high, low, highs, lows, closes, volumes, bar_idx)
                if score < LFV_P["min_confluence"]:
                    continue

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
                                       f"refined=[{rbot:.3f},{rtop:.3f}] rr={rr:.1f} "
                                       f"lfv={score}/3 {lfv_detail}"),
                })
                break

    closed = [t for t in trades if t["action"] == "CLOSE"]
    n = len(closed)
    print(f"  Zone Refine: {n} closed trades | W:{wins} L:{losses} | "
          f"P&L: ${total_pnl:+,.2f} | Balance: ${balance:,.2f}")

    # Carry forward any open position so the live trader picks it up
    live_pos = None
    if position:
        live_pos = {
            "dir":        position["dir"],
            "shares":     position["shares"],
            "entry":      position["entry"],
            "stop":       position["stop"],
            "target":     position["target"],
            "zone_type":  position.get("zone_type", "?"),
            "initial_risk": abs(position["entry"] - position["stop"]),
            "entry_time": trades[-1]["time"] if trades else "00:00",
        }
        print(f"  Open position carried forward: {live_pos['dir']} "
              f"{live_pos['shares']}sh @ ${live_pos['entry']:.3f}")

    state = {
        "ticker": TICKER, "capital": CAPITAL, "balance": round(balance, 2),
        "position": live_pos, "zones": [], "zones_date": None,
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
    if df1h.empty:
        raise RuntimeError(
            f"No 1H data returned for {TICKER}. "
            "Check the ticker, date range, and yfinance cache/database permissions."
        )
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
