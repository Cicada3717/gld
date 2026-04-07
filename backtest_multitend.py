"""
backtest_multitrend.py  — adds 72H trend alignment filter for LONG/SHORT entries.

Pattern identified: most LONG losses cluster when gold was in a multi-day downtrend.
The existing 20H trend check (~1 day) is too short to catch major corrections.
Fix: require 72H (3-day) momentum to agree with trade direction before entry.
"""
from datetime import datetime, date
import numpy as np
import pandas as pd
import yfinance as yf
from zone_refinement_backtest import detect_zones, _clean

TICKER  = "GC=F"; CAPITAL = 10_000.0; SLIPPAGE = 0.50; START = date(2025, 4, 1)
PARAMS  = dict(strength_bars=3, strength_mult=1.5, bos_ema=21, bos_slope_bars=8,
               stop_buffer=0.001, target_lookback=60, target_skip=5, min_rr=2.5,
               trail_activation_r=2.5, trail_distance_r=0.2, max_trades_day=2,
               risk_pct=0.02, leverage=5.0, commission=0.0001)

ATR_LOW  = 0.80; ATR_HIGH  = 1.20
BODY_LOW = 0.30; BODY_HIGH = 0.70
BAD_HOURS = {10, 11, 12, 15, 19}
TREND_MULTI = 72   # 72 one-hour bars ≈ 3 trading days

# ── helpers ─────────────────────────────────────────────────────────────────
def ema_s(v, p):
    out = [float("nan")] * len(v)
    if len(v) < p: return out
    k = 2/(p+1); e = float(np.mean(v[:p])); out[p-1] = e
    for i in range(p, len(v)): e = v[i]*k+e*(1-k); out[i] = e
    return out

def atr_v(h, l, c, p=14):
    ha = np.array(h[-p-2:]); la = np.array(l[-p-2:]); ca = np.array(c[-p-2:])
    if len(ha) < 2: return 1.0
    tr = np.maximum(ha[1:]-la[1:], np.maximum(abs(ha[1:]-ca[:-1]), abs(la[1:]-ca[:-1])))
    return float(np.mean(tr[-p:])) if len(tr) >= p else float(np.mean(tr))

def bos_bull(c, p, s):
    ev = ema_s(c, p); vv = [x for x in ev if x == x]
    return len(vv) > s and vv[-1] > vv[-1-s]

def bos_bear(c, p, s):
    ev = ema_s(c, p); vv = [x for x in ev if x == x]
    return len(vv) > s and vv[-1] < vv[-1-s]

def ph(h, sk, lb):
    n = min(lb, len(h)); s = max(0, len(h)-n); e = max(0, len(h)-sk)
    return max(h[s:e]) if s < e and h[s:e] else (max(h[s:]) if h[s:] else 0.0)

def pl(l, sk, lb):
    n = min(lb, len(l)); s = max(0, len(l)-n); e = max(0, len(l)-sk)
    return min(l[s:e]) if s < e and l[s:e] else (min(l[s:]) if l[s:] else 9e9)

def ef(px, d): return px + SLIPPAGE if d == "LONG" else px - SLIPPAGE

# ── fetch ────────────────────────────────────────────────────────────────────
print("Fetching GC=F data...", flush=True)
end = pd.Timestamp.now(); sdl = end - pd.DateOffset(months=15)
df1h = _clean(yf.download(TICKER, start=sdl.strftime("%Y-%m-%d"),
                           end=end.strftime("%Y-%m-%d"), interval="1h", progress=False))
df4h = df1h.resample("4h").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna()
zones = detect_zones(df4h, df1h, strength_bars=3, strength_mult=1.5)
print(f"  {len(df1h)} bars | {len(zones)} zones\n")

# ── replay ───────────────────────────────────────────────────────────────────
replay_start = pd.Timestamp(START.strftime("%Y-%m-%d"))
zone_list = [dict(z) for z in zones]
balance = CAPITAL; position = None
wins = losses = 0; long_w = long_l = short_w = short_l = 0
total_pnl = 0.0; trades = []; peak = CAPITAL; max_dd = 0.0; monthly = {}
tdd = None; tdc = 0; skip_multi = 0

for ts, row in df1h[df1h.index >= replay_start].iterrows():
    dt = ts.to_pydatetime()
    if dt.weekday() == 5: continue
    if dt.weekday() == 6 and dt.hour < 18: continue
    if dt.hour == 17: continue
    ds = ts.strftime("%Y-%m-%d"); ym = ts.strftime("%Y-%m")
    if tdd != ds: tdd = ds; tdc = 0

    hist   = df1h[df1h.index <= ts]
    closes = hist["Close"].tolist(); highs = hist["High"].tolist(); lows = hist["Low"].tolist()
    price  = float(row["Close"]); high = float(row["High"]); low = float(row["Low"])

    if position:
        pos = position
        ir  = pos.get("initial_risk", abs(pos["entry"] - pos["stop"]))
        pos["initial_risk"] = ir
        ta  = ir * PARAMS["trail_activation_r"]; td2 = ir * PARAMS["trail_distance_r"]
        if pos["dir"] == "LONG":
            best = pos.get("best_price", pos["entry"])
            if high > best: pos["best_price"] = high; best = high
            if best >= pos["entry"] + ta:
                ts2 = best - td2
                if ts2 > pos["stop"]: pos["stop"] = ts2
            hs = low <= pos["stop"]; ht = high >= pos["target"]
        else:
            best = pos.get("best_price", pos["entry"])
            if low < best: pos["best_price"] = low; best = low
            if best <= pos["entry"] - ta:
                ts2 = best + td2
                if ts2 < pos["stop"]: pos["stop"] = ts2
            hs = high >= pos["stop"]; ht = low <= pos["target"]
        if hs or ht:
            er  = pos["stop"] if hs else pos["target"]
            ep  = er - SLIPPAGE if pos["dir"] == "LONG" else er + SLIPPAGE
            ta2 = ir * PARAMS["trail_activation_r"]
            trail_active = pos.get("best_price") is not None and (
                (pos["dir"] == "LONG"  and pos.get("best_price", pos["entry"]) >= pos["entry"] + ta2) or
                (pos["dir"] == "SHORT" and pos.get("best_price", pos["entry"]) <= pos["entry"] - ta2))
            reason = "TRAIL_STOP" if (hs and trail_active) else ("STOP" if hs else "TARGET")
            pnl = (ep - pos["entry"]) * pos["shares"] if pos["dir"] == "LONG" \
                  else (pos["entry"] - ep) * pos["shares"]
            net = pnl - (pos["entry"] + ep) * pos["shares"] * PARAMS["commission"]
            balance += net; total_pnl += net
            peak = max(peak, balance); dd = (peak - balance) / peak; max_dd = max(max_dd, dd)
            if net > 0:
                wins += 1
                if pos["dir"] == "LONG": long_w += 1
                else: short_w += 1
            else:
                losses += 1
                if pos["dir"] == "LONG": long_l += 1
                else: short_l += 1
            monthly[ym] = monthly.get(ym, 0) + net
            trades.append({"ds": ds, "tm": ts.strftime("%H:%M"), "dir": pos["dir"],
                           "shares": pos["shares"], "entry": pos["entry"], "exit": ep,
                           "pnl": net, "balance": balance, "reason": reason})
            position = None
        continue

    if tdc >= PARAMS["max_trades_day"]: continue

    bull    = bos_bull(closes, PARAMS["bos_ema"], PARAMS["bos_slope_bars"])
    bear    = bos_bear(closes, PARAMS["bos_ema"], PARAMS["bos_slope_bars"])
    t20     = closes[-1] - closes[-20]   if len(closes) >= 20 else 0
    t_multi = closes[-1] - closes[-TREND_MULTI] if len(closes) >= TREND_MULTI else t20

    f_atr      = atr_v(highs, lows, closes)
    f_avg      = atr_v(highs[-30:], lows[-30:], closes[-30:], 20) if len(closes) >= 22 else f_atr
    f_ratio    = f_atr / f_avg if f_avg > 0 else 1.0
    f_body_raw = float(row["Close"]) - float(row["Open"])
    f_body_pct = abs(f_body_raw) / f_atr if f_atr > 0 else 0.0
    f_body_bull= f_body_raw >= 0

    for zone in zone_list:
        if zone.get("consumed"): continue
        formed = zone["formed_at"]
        if not isinstance(formed, datetime): formed = datetime.fromisoformat(str(formed))
        if pd.Timestamp(formed) >= ts: continue

        ztop = zone["htf_top"]; zbot = zone["htf_bottom"]
        rtop = zone["refined_top"]; rbot = zone["refined_bottom"]

        if zone["type"] == "demand":
            if not (zbot <= price <= ztop) or not bull or low > rtop or price < rbot or t20 < 0: continue
            stop = rbot * (1 - 0.001); risk = price - stop
            if risk <= 0: continue
            target = ph(highs, 5, 60)
            if target <= price: target = price + risk * PARAMS["min_rr"]
            if (target - price) / risk < PARAMS["min_rr"]: continue
            ar  = risk + 2 * SLIPPAGE
            qty = min(int(balance * PARAMS["risk_pct"] / ar), int(balance * PARAMS["leverage"] / price))
            if qty <= 0: continue
            signed_body = f_body_pct if f_body_bull else -f_body_pct
            if dt.hour in BAD_HOURS:
                zone["consumed"] = True; zone["consumed_date"] = ds; break
            if not (ATR_LOW <= f_ratio <= ATR_HIGH):
                zone["consumed"] = True; zone["consumed_date"] = ds; break
            if BODY_LOW <= signed_body < BODY_HIGH:
                zone["consumed"] = True; zone["consumed_date"] = ds; break
            # NEW: 72H trend must be bullish for LONG entry
            if t_multi <= 0:
                skip_multi += 1; zone["consumed"] = True; zone["consumed_date"] = ds; break
            position = {"dir": "LONG", "shares": qty, "entry": ef(price, "LONG"),
                        "stop": stop, "target": target, "initial_risk": abs(ef(price, "LONG") - stop)}
            zone["consumed"] = True; zone["consumed_date"] = ds; tdc += 1; break

        elif zone["type"] == "supply":
            if not (zbot <= price <= ztop) or not bear or high < rbot or price > rtop or t20 > 0: continue
            stop = rtop * (1 + 0.001); risk = stop - price
            if risk <= 0: continue
            target = pl(lows, 5, 60)
            if target >= price: target = price - risk * PARAMS["min_rr"]
            if (price - target) / risk < PARAMS["min_rr"]: continue
            ar  = risk + 2 * SLIPPAGE
            qty = min(int(balance * PARAMS["risk_pct"] / ar), int(balance * PARAMS["leverage"] / price))
            if qty <= 0: continue
            signed_body = f_body_pct if not f_body_bull else -f_body_pct
            if dt.hour in BAD_HOURS:
                zone["consumed"] = True; zone["consumed_date"] = ds; break
            if not (ATR_LOW <= f_ratio <= ATR_HIGH):
                zone["consumed"] = True; zone["consumed_date"] = ds; break
            if BODY_LOW <= signed_body < BODY_HIGH:
                zone["consumed"] = True; zone["consumed_date"] = ds; break
            # SHORTs: no 72H filter — supply zone rejections work in any macro environment
            position = {"dir": "SHORT", "shares": qty, "entry": ef(price, "SHORT"),
                        "stop": stop, "target": target, "initial_risk": abs(ef(price, "SHORT") - stop)}
            zone["consumed"] = True; zone["consumed_date"] = ds; tdc += 1; break

# ── results ──────────────────────────────────────────────────────────────────
n   = wins + losses
wr  = wins / n * 100 if n else 0
roi = (balance - CAPITAL) / CAPITAL * 100
pnls  = [t["pnl"] for t in trades]
llist = [p for p in pnls if p < 0]

print(f"{'='*80}")
print(f"  MULTI-TREND FILTER (72H on LONGs only)  |  {START} to today")
print(f"{'='*80}")
print(f"  Trades       : {n}  ({wins}W / {losses}L)  [72H filtered: {skip_multi}]")
print(f"  LONG         : {long_w}W / {long_l}L  WR={long_w/(long_w+long_l)*100:.1f}%  "
      f"P&L=${sum(t['pnl'] for t in trades if t['dir']=='LONG'):+,.0f}")
print(f"  SHORT        : {short_w}W / {short_l}L  WR={short_w/(short_w+short_l)*100:.1f}%  "
      f"P&L=${sum(t['pnl'] for t in trades if t['dir']=='SHORT'):+,.0f}")
print(f"  Win Rate     : {wr:.1f}%")
print(f"  ROI          : {roi:+.2f}%")
print(f"  End Balance  : ${balance:,.2f}")
print(f"  Max Drawdown : -{max_dd*100:.1f}%")
if llist:
    print(f"  Largest loss : ${min(llist):+,.2f}")
    print(f"  Avg loss     : ${sum(llist)/len(llist):+,.2f}")
print()
print(f"  {'Month':<10} {'P&L':>12}  {'Cumul':>12}")
print(f"  {'-'*38}")
cumul = 0; losing = 0
for ym in sorted(monthly):
    cumul += monthly[ym]; tag = " <<" if monthly[ym] < 0 else ""
    if monthly[ym] < 0: losing += 1
    print(f"  {ym:<10} ${monthly[ym]:>+11,.2f}  ${cumul:>+11,.2f}{tag}")
print(f"  {'-'*38}")
print(f"  Losing months: {losing}/{len(monthly)}")
print()
print(f"  {'#':<4} {'Date':<12} {'T':<6} {'D':<6} {'Oz':>5} {'Entry':>8} {'Exit':>8} {'Reason':<12} {'P&L':>10} {'Balance':>12}")
print(f"  {'-'*85}")
for i, t in enumerate(trades, 1):
    print(f"  {i:<4} {t['ds']:<12} {t['tm']:<6} {t['dir']:<6} {t['shares']:>5} "
          f"${t['entry']:>7.2f} ${t['exit']:>7.2f} {t['reason']:<12} "
          f"${t['pnl']:>+9.2f} ${t['balance']:>11,.2f}")
