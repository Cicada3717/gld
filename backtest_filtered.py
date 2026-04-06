"""
backtest_filtered.py — GC=F 1-year backtest WITH pattern-recognition filters.

Filters applied based on analyze_losses.py findings:
  1. RSI filter       : skip when RSI < 35 or RSI > 68  (40-60 sweet spot is 54-61% WR)
  2. ATR regime       : skip when entry_atr < 0.8x or > 1.2x avg_atr_20
                        (low-vol 0% WR, elevated only 16.7% WR)
  3. Body filter      : skip when body_pct in 0.3-0.7 ("small confirm" = 27.8% WR, -$162 avg)
  4. Hour filter      : skip hours 10,11,12,15,19,22  (all <25% WR)
"""
from datetime import datetime, date
import numpy as np
import pandas as pd
import yfinance as yf
from zone_refinement_backtest import detect_zones, _clean

TICKER   = "GC=F"
CAPITAL  = 10_000.0
SLIPPAGE = 0.50
START    = date(2025, 4, 1)

PARAMS = dict(
    strength_bars=3, strength_mult=1.5, bos_ema=21,
    bos_slope_bars=8, stop_buffer=0.001,
    target_lookback=60, target_skip=5, min_rr=2.5,
    trail_activation_r=2.5, trail_distance_r=0.2,
    max_trades_day=2, risk_pct=0.02, leverage=5.0, commission=0.0001,
)

# ── FILTERS ─────────────────────────────────────────────────────────────────
# RSI filter REMOVED — all RSI buckets have positive expected value (2.5 R:R saves them)
ATR_LOW   = 0.80     # skip when entry_atr < ATR_LOW  * avg_atr_20  (low-vol = 0% WR)
ATR_HIGH  = 1.20     # skip when entry_atr > ATR_HIGH * avg_atr_20  (elevated = 16% WR)
BODY_SKIP_LOW  = 0.30  # skip "small confirm" body range  [0.30 , 0.70)  (27% WR, -$162 avg)
BODY_SKIP_HIGH = 0.70
BAD_HOURS = {10, 11, 12, 15, 19}  # clearly negative avg P&L; removed 22 (only -$18, borderline)

# ── indicators ──────────────────────────────────────────────────────────────

def ema_s(v, p):
    out = [float("nan")] * len(v)
    if len(v) < p: return out
    k = 2/(p+1); e = float(np.mean(v[:p])); out[p-1] = e
    for i in range(p, len(v)): e = v[i]*k+e*(1-k); out[i] = e
    return out

def rsi14(closes, period=14):
    if len(closes) < period+1: return 50.0
    deltas = np.diff(closes[-period-10:])
    gains  = np.where(deltas>0, deltas, 0.0)
    loss_  = np.where(deltas<0, -deltas, 0.0)
    ag = np.mean(gains[-period:]); al = np.mean(loss_[-period:])
    if al == 0: return 100.0
    return 100 - 100/(1 + ag/al)

def atr_val(highs, lows, closes, period=14):
    h = np.array(highs[-period-2:]); l = np.array(lows[-period-2:])
    c = np.array(closes[-period-2:])
    tr = np.maximum(h[1:]-l[1:], np.maximum(abs(h[1:]-c[:-1]), abs(l[1:]-c[:-1])))
    return float(np.mean(tr[-period:])) if len(tr)>=period else float(np.mean(tr)) if len(tr) else 1.0

def bos_bull(c, p, s):
    ev = ema_s(c, p); vv = [x for x in ev if x==x]
    return len(vv)>s and vv[-1]>vv[-1-s]

def bos_bear(c, p, s):
    ev = ema_s(c, p); vv = [x for x in ev if x==x]
    return len(vv)>s and vv[-1]<vv[-1-s]

def prior_high(h, sk, lb):
    n=min(lb,len(h)); s=max(0,len(h)-n); e=max(0,len(h)-sk)
    return max(h[s:e]) if s<e and h[s:e] else (max(h[s:]) if h[s:] else 0.0)

def prior_low(l, sk, lb):
    n=min(lb,len(l)); s=max(0,len(l)-n); e=max(0,len(l)-sk)
    return min(l[s:e]) if s<e and l[s:e] else (min(l[s:]) if l[s:] else 9e9)

def efill(px, d): return px+SLIPPAGE if d=="LONG" else px-SLIPPAGE

# ── main ────────────────────────────────────────────────────────────────────

print(f"\n{'='*80}")
print(f"  GC=F 1-YEAR FILTERED BACKTEST  |  {START} to today")
print(f"  Filters: ATR regime {ATR_LOW}-{ATR_HIGH}x | no small-confirm body | skip hours {sorted(BAD_HOURS)}")
print(f"{'='*80}\n")

print("Fetching GC=F 1H data (15 months for zone warmup)...")
end      = pd.Timestamp.now()
start_dl = end - pd.DateOffset(months=15)
df1h     = _clean(yf.download(TICKER, start=start_dl.strftime("%Y-%m-%d"),
                               end=end.strftime("%Y-%m-%d"),
                               interval="1h", progress=False))
df4h     = (df1h.resample("4h")
             .agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"})
             .dropna())
zones    = detect_zones(df4h, df1h, strength_bars=3, strength_mult=1.5)
print(f"  {len(df1h)} 1H bars | {len(zones)} zones detected\n")

replay_start = pd.Timestamp(START.strftime("%Y-%m-%d"))
zone_list    = [dict(z) for z in zones]
balance = CAPITAL; position = None
wins = losses = skipped = 0
total_pnl = 0.0; trades = []
peak = CAPITAL; max_dd = 0.0; monthly = {}
trades_today_date = None; trades_today_count = 0
skip_reasons = {"atr":0, "body":0, "hour":0}

for ts, row in df1h[df1h.index >= replay_start].iterrows():
    dt = ts.to_pydatetime()
    if dt.weekday() == 5: continue
    if dt.weekday() == 6 and dt.hour < 18: continue
    if dt.hour == 17: continue

    ds = ts.strftime("%Y-%m-%d"); tm = ts.strftime("%H:%M")
    ym = ts.strftime("%Y-%m")
    if trades_today_date != ds: trades_today_date = ds; trades_today_count = 0

    hist   = df1h[df1h.index <= ts]
    closes = hist["Close"].tolist(); highs = hist["High"].tolist()
    lows   = hist["Low"].tolist(); vols = hist["Volume"].tolist()
    price  = float(row["Close"]); high = float(row["High"]); low = float(row["Low"])

    # ── manage position ───────────────────────────────────────────────────
    if position:
        pos = position
        ir  = pos.get("initial_risk", abs(pos["entry"]-pos["stop"]))
        pos["initial_risk"] = ir
        ta  = ir*PARAMS["trail_activation_r"]; td = ir*PARAMS["trail_distance_r"]

        if pos["dir"] == "LONG":
            best = pos.get("best_price", pos["entry"])
            if high > best: pos["best_price"] = high; best = high
            if best >= pos["entry"]+ta:
                ts2 = best-td
                if ts2 > pos["stop"]: pos["stop"] = ts2
            hs = low  <= pos["stop"]; ht = high >= pos["target"]
        else:
            best = pos.get("best_price", pos["entry"])
            if low < best: pos["best_price"] = low; best = low
            if best <= pos["entry"]-ta:
                ts2 = best+td
                if ts2 < pos["stop"]: pos["stop"] = ts2
            hs = high >= pos["stop"]; ht = low  <= pos["target"]

        if hs or ht:
            er = pos["stop"] if hs else pos["target"]
            ep = er-SLIPPAGE if pos["dir"]=="LONG" else er+SLIPPAGE
            trail_active = pos.get("best_price") is not None and (
                (pos["dir"]=="LONG"  and pos.get("best_price",pos["entry"])>=pos["entry"]+ta) or
                (pos["dir"]=="SHORT" and pos.get("best_price",pos["entry"])<=pos["entry"]-ta)
            )
            reason = "TRAIL_STOP" if (hs and trail_active) else ("STOP" if hs else "TARGET")
            pnl    = (ep-pos["entry"])*pos["shares"] if pos["dir"]=="LONG" \
                     else (pos["entry"]-ep)*pos["shares"]
            net    = pnl - (pos["entry"]+ep)*pos["shares"]*PARAMS["commission"]
            balance += net; total_pnl += net
            peak    = max(peak, balance); dd = (peak-balance)/peak; max_dd = max(max_dd, dd)
            if net > 0: wins   += 1
            else:       losses += 1
            monthly[ym] = monthly.get(ym,0) + net
            trades.append({"ds":ds,"tm":tm,"dir":pos["dir"],"shares":pos["shares"],
                            "entry":pos["entry"],"exit":ep,"reason":reason,
                            "pnl":net,"balance":balance})
            position = None
        continue

    if trades_today_count >= PARAMS["max_trades_day"]: continue

    bull = bos_bull(closes, PARAMS["bos_ema"], PARAMS["bos_slope_bars"])
    bear = bos_bear(closes, PARAMS["bos_ema"], PARAMS["bos_slope_bars"])
    t20  = closes[-1]-closes[-20] if len(closes)>=20 else 0

    # ── pre-compute filter values ─────────────────────────────────────────
    entry_atr  = atr_val(highs, lows, closes)
    avg_atr_20 = atr_val(highs[-30:], lows[-30:], closes[-30:], 20) if len(closes)>=22 else entry_atr
    atr_ratio  = entry_atr / avg_atr_20 if avg_atr_20 > 0 else 1.0
    body_raw   = float(row["Close"]) - float(row["Open"])
    body_pct   = abs(body_raw) / entry_atr if entry_atr > 0 else 0
    body_dir   = 1 if body_raw >= 0 else -1  # +1 = bullish candle

    for zone in zone_list:
        if zone.get("consumed"): continue
        formed = zone["formed_at"]
        if not isinstance(formed, datetime): formed = datetime.fromisoformat(str(formed))
        if pd.Timestamp(formed) >= ts: continue

        ztop=zone["htf_top"]; zbot=zone["htf_bottom"]
        rtop=zone["refined_top"]; rbot=zone["refined_bottom"]

        if zone["type"] == "demand":
            if not(zbot<=price<=ztop) or not bull or low>rtop or price<rbot or t20<0: continue
            stop=rbot*(1-0.001); risk=price-stop
            if risk<=0: continue
            target=prior_high(highs,5,60)
            if target<=price: target=price+risk*PARAMS["min_rr"]
            if (target-price)/risk<PARAMS["min_rr"]: continue
            ar=risk+2*SLIPPAGE
            qty=min(int(balance*PARAMS["risk_pct"]/ar), int(balance*PARAMS["leverage"]/price))
            if qty<=0: continue

            # ── FILTER CHECKS ────────────────────────────────────────────
            # For demand (LONG), body_pct confirmation = bullish candle body ratio
            signed_body = body_pct if body_dir >= 0 else -body_pct  # positive = confirming for LONG
            if dt.hour in BAD_HOURS:
                skip_reasons["hour"] += 1; zone["consumed"]=True; zone["consumed_date"]=ds; break
            if not (ATR_LOW <= atr_ratio <= ATR_HIGH):
                skip_reasons["atr"] += 1; zone["consumed"]=True; zone["consumed_date"]=ds; break
            if BODY_SKIP_LOW <= signed_body < BODY_SKIP_HIGH:
                skip_reasons["body"] += 1; zone["consumed"]=True; zone["consumed_date"]=ds; break
            # ─────────────────────────────────────────────────────────────

            ef = efill(price,"LONG")
            position = {"dir":"LONG","shares":qty,"entry":ef,"stop":stop,"target":target,
                        "initial_risk":abs(ef-stop)}
            zone["consumed"]=True; zone["consumed_date"]=ds; trades_today_count+=1; break

        elif zone["type"] == "supply":
            if not(zbot<=price<=ztop) or not bear or high<rbot or price>rtop or t20>0: continue
            stop=rtop*(1+0.001); risk=stop-price
            if risk<=0: continue
            target=prior_low(lows,5,60)
            if target>=price: target=price-risk*PARAMS["min_rr"]
            if (price-target)/risk<PARAMS["min_rr"]: continue
            ar=risk+2*SLIPPAGE
            qty=min(int(balance*PARAMS["risk_pct"]/ar), int(balance*PARAMS["leverage"]/price))
            if qty<=0: continue

            # ── FILTER CHECKS ────────────────────────────────────────────
            # For supply (SHORT), confirming body = bearish candle (body_dir < 0)
            signed_body = body_pct if body_dir <= 0 else -body_pct  # positive = confirming for SHORT
            if dt.hour in BAD_HOURS:
                skip_reasons["hour"] += 1; zone["consumed"]=True; zone["consumed_date"]=ds; break
            if not (ATR_LOW <= atr_ratio <= ATR_HIGH):
                skip_reasons["atr"] += 1; zone["consumed"]=True; zone["consumed_date"]=ds; break
            if BODY_SKIP_LOW <= signed_body < BODY_SKIP_HIGH:
                skip_reasons["body"] += 1; zone["consumed"]=True; zone["consumed_date"]=ds; break
            # ─────────────────────────────────────────────────────────────

            ef = efill(price,"SHORT")
            position = {"dir":"SHORT","shares":qty,"entry":ef,"stop":stop,"target":target,
                        "initial_risk":abs(ef-stop)}
            zone["consumed"]=True; zone["consumed_date"]=ds; trades_today_count+=1; break

# ── results ──────────────────────────────────────────────────────────────────
n   = wins+losses
wr  = wins/n*100 if n else 0
roi = (balance-CAPITAL)/CAPITAL*100

print(f"{'='*80}")
print(f"  FILTERED RESULTS")
print(f"{'='*80}")
print(f"  Trades     : {n}  ({wins}W / {losses}L)  [skipped: {sum(skip_reasons.values())} zones]")
print(f"  Skip breakdown: ATR={skip_reasons['atr']}  Body={skip_reasons['body']}  Hour={skip_reasons['hour']}")
print(f"  Win Rate   : {wr:.1f}%")
print(f"  ROI        : {roi:+.2f}%")
print(f"  Net P&L    : ${total_pnl:+,.2f}")
print(f"  End Balance: ${balance:,.2f}")
print(f"  Max Drawdown: -{max_dd*100:.1f}%")
if trades:
    pnls = [t["pnl"] for t in trades]
    loss_list = [p for p in pnls if p<0]
    print(f"  Largest loss: ${min(loss_list):+,.2f}" if loss_list else "  No losses!")
    print(f"  Avg loss    : ${sum(loss_list)/len(loss_list):+,.2f}" if loss_list else "")
print()

print(f"  {'Month':<10} {'P&L':>12}  {'Cumul':>12}")
print(f"  {'-'*38}")
cumul=0; losing=0
for ym in sorted(monthly):
    cumul += monthly[ym]
    tag = " <<" if monthly[ym]<0 else ""
    if monthly[ym]<0: losing+=1
    print(f"  {ym:<10} ${monthly[ym]:>+11,.2f}  ${cumul:>+11,.2f}{tag}")
print(f"  {'-'*38}")
print(f"  Losing months: {losing}/{len(monthly)}")
print()

print(f"  {'#':<4} {'Date':<12} {'Time':<6} {'Dir':<6} {'Oz':>7} {'Entry':>8} {'Exit':>8} {'Reason':<12} {'P&L':>10} {'Balance':>12}")
print(f"  {'-'*90}")
for i, t in enumerate(trades, 1):
    print(f"  {i:<4} {t['ds']:<12} {t['tm']:<6} {t['dir']:<6} {t['shares']:>7} "
          f"${t['entry']:>7.2f} ${t['exit']:>7.2f} {t['reason']:<12} "
          f"${t['pnl']:>+9.2f} ${t['balance']:>11,.2f}")
