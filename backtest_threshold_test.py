"""
backtest_threshold_test.py
Test different 72H trend thresholds to find the sweet spot:
  Binary (<=0): blocks ALL LONGs when 72H is even slightly negative  [v3 — too strict]
  ATR-based   : block only when 72H drop > N x ATR  (normalised to volatility)
  Pct-based   : block only when 72H drop > X% of price

Goal: keep the crash-blockers (Apr 2025, Mar 2026) while allowing
      normal uptrend pullbacks (Jul 2025, Sep 2025, Feb 2026).
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
ATR_LOW=0.80; ATR_HIGH=1.20; BODY_LOW=0.30; BODY_HIGH=0.70; BAD_HOURS={10,11,12,15,19}
TREND_BARS = 72

def ema_s(v,p):
    out=[float("nan")]*len(v)
    if len(v)<p: return out
    k=2/(p+1); e=float(np.mean(v[:p])); out[p-1]=e
    for i in range(p,len(v)): e=v[i]*k+e*(1-k); out[i]=e
    return out
def atr_v(h,l,c,p=14):
    ha=np.array(h[-p-2:]); la=np.array(l[-p-2:]); ca=np.array(c[-p-2:])
    if len(ha)<2: return 1.0
    tr=np.maximum(ha[1:]-la[1:],np.maximum(abs(ha[1:]-ca[:-1]),abs(la[1:]-ca[:-1])))
    return float(np.mean(tr[-p:])) if len(tr)>=p else float(np.mean(tr))
def bos_bull(c,p,s):
    ev=ema_s(c,p); vv=[x for x in ev if x==x]; return len(vv)>s and vv[-1]>vv[-1-s]
def bos_bear(c,p,s):
    ev=ema_s(c,p); vv=[x for x in ev if x==x]; return len(vv)>s and vv[-1]<vv[-1-s]
def ph(h,sk,lb):
    n=min(lb,len(h)); s=max(0,len(h)-n); e=max(0,len(h)-sk)
    return max(h[s:e]) if s<e and h[s:e] else (max(h[s:]) if h[s:] else 0.0)
def pl(l,sk,lb):
    n=min(lb,len(l)); s=max(0,len(l)-n); e=max(0,len(l)-sk)
    return min(l[s:e]) if s<e and l[s:e] else (min(l[s:]) if l[s:] else 9e9)
def ef(px,d): return px+SLIPPAGE if d=="LONG" else px-SLIPPAGE

print("Fetching...", flush=True)
end=pd.Timestamp.now(); sdl=end-pd.DateOffset(months=15)
df1h=_clean(yf.download(TICKER,start=sdl.strftime("%Y-%m-%d"),end=end.strftime("%Y-%m-%d"),interval="1h",progress=False))
df4h=df1h.resample("4h").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna()
base_zones=detect_zones(df4h,df1h,strength_bars=3,strength_mult=1.5)
print(f"  {len(df1h)} bars | {len(base_zones)} zones\n")

def run_backtest(threshold_label, long_block_fn):
    """
    long_block_fn(trend_72h, f_atr, price) -> True means BLOCK the LONG
    """
    zone_list=[dict(z) for z in base_zones]
    balance=CAPITAL; position=None; wins=losses=0
    long_w=long_l=short_w=short_l=0
    total_pnl=0.0; trades=[]; peak=CAPITAL; max_dd=0.0; monthly={}
    tdd=None; tdc=0; filtered=0
    replay_start=pd.Timestamp(START.strftime("%Y-%m-%d"))

    for ts,row in df1h[df1h.index>=replay_start].iterrows():
        dt=ts.to_pydatetime()
        if dt.weekday()==5: continue
        if dt.weekday()==6 and dt.hour<18: continue
        if dt.hour==17: continue
        ds=ts.strftime("%Y-%m-%d"); ym=ts.strftime("%Y-%m")
        if tdd!=ds: tdd=ds; tdc=0
        hist=df1h[df1h.index<=ts]
        closes=hist["Close"].tolist(); highs=hist["High"].tolist(); lows=hist["Low"].tolist()
        price=float(row["Close"]); high=float(row["High"]); low=float(row["Low"])

        if position:
            pos=position; ir=pos.get("initial_risk",abs(pos["entry"]-pos["stop"]))
            pos["initial_risk"]=ir; ta=ir*PARAMS["trail_activation_r"]; td2=ir*PARAMS["trail_distance_r"]
            if pos["dir"]=="LONG":
                best=pos.get("best_price",pos["entry"])
                if high>best: pos["best_price"]=high; best=high
                if best>=pos["entry"]+ta:
                    ts2=best-td2
                    if ts2>pos["stop"]: pos["stop"]=ts2
                hs=low<=pos["stop"]; ht=high>=pos["target"]
            else:
                best=pos.get("best_price",pos["entry"])
                if low<best: pos["best_price"]=low; best=low
                if best<=pos["entry"]-ta:
                    ts2=best+td2
                    if ts2<pos["stop"]: pos["stop"]=ts2
                hs=high>=pos["stop"]; ht=low<=pos["target"]
            if hs or ht:
                er=pos["stop"] if hs else pos["target"]
                ep=er-SLIPPAGE if pos["dir"]=="LONG" else er+SLIPPAGE
                ta2=ir*PARAMS["trail_activation_r"]
                trail_active=pos.get("best_price") is not None and (
                    (pos["dir"]=="LONG" and pos.get("best_price",pos["entry"])>=pos["entry"]+ta2) or
                    (pos["dir"]=="SHORT" and pos.get("best_price",pos["entry"])<=pos["entry"]-ta2))
                reason="TRAIL_STOP" if (hs and trail_active) else ("STOP" if hs else "TARGET")
                pnl=(ep-pos["entry"])*pos["shares"] if pos["dir"]=="LONG" else (pos["entry"]-ep)*pos["shares"]
                net=pnl-(pos["entry"]+ep)*pos["shares"]*PARAMS["commission"]
                balance+=net; total_pnl+=net; peak=max(peak,balance)
                dd=(peak-balance)/peak; max_dd=max(max_dd,dd)
                if net>0:
                    wins+=1
                    if pos["dir"]=="LONG": long_w+=1
                    else: short_w+=1
                else:
                    losses+=1
                    if pos["dir"]=="LONG": long_l+=1
                    else: short_l+=1
                monthly[ym]=monthly.get(ym,0)+net
                trades.append({"ds":ds,"dir":pos["dir"],"pnl":net})
                position=None
            continue

        if tdc>=PARAMS["max_trades_day"]: continue
        bull=bos_bull(closes,PARAMS["bos_ema"],PARAMS["bos_slope_bars"])
        bear=bos_bear(closes,PARAMS["bos_ema"],PARAMS["bos_slope_bars"])
        t20=closes[-1]-closes[-20] if len(closes)>=20 else 0
        t72=closes[-1]-closes[-TREND_BARS] if len(closes)>=TREND_BARS else closes[-1]-closes[0]
        f_atr=atr_v(highs,lows,closes)
        f_avg=atr_v(highs[-30:],lows[-30:],closes[-30:],20) if len(closes)>=22 else f_atr
        f_ratio=f_atr/f_avg if f_avg>0 else 1.0
        f_body_raw=float(row["Close"])-float(row["Open"])
        f_body_pct=abs(f_body_raw)/f_atr if f_atr>0 else 0.0
        f_body_bull=f_body_raw>=0

        for zone in zone_list:
            if zone.get("consumed"): continue
            formed=zone["formed_at"]
            if not isinstance(formed,datetime): formed=datetime.fromisoformat(str(formed))
            if pd.Timestamp(formed)>=ts: continue
            ztop=zone["htf_top"]; zbot=zone["htf_bottom"]
            rtop=zone["refined_top"]; rbot=zone["refined_bottom"]

            if zone["type"]=="demand":
                if not(zbot<=price<=ztop) or not bull or low>rtop or price<rbot or t20<0: continue
                stop=rbot*(1-0.001); risk=price-stop
                if risk<=0: continue
                target=ph(highs,5,60)
                if target<=price: target=price+risk*PARAMS["min_rr"]
                if (target-price)/risk<PARAMS["min_rr"]: continue
                ar=risk+2*SLIPPAGE
                qty=min(int(balance*PARAMS["risk_pct"]/ar),int(balance*PARAMS["leverage"]/price))
                if qty<=0: continue
                signed_body=f_body_pct if f_body_bull else -f_body_pct
                if dt.hour in BAD_HOURS: zone["consumed"]=True; zone["consumed_date"]=ds; break
                if not(ATR_LOW<=f_ratio<=ATR_HIGH): zone["consumed"]=True; zone["consumed_date"]=ds; break
                if BODY_LOW<=signed_body<BODY_HIGH: zone["consumed"]=True; zone["consumed_date"]=ds; break
                if long_block_fn(t72, f_atr, price):
                    filtered+=1; zone["consumed"]=True; zone["consumed_date"]=ds; break
                position={"dir":"LONG","shares":qty,"entry":ef(price,"LONG"),
                          "stop":stop,"target":target,"initial_risk":abs(ef(price,"LONG")-stop)}
                zone["consumed"]=True; zone["consumed_date"]=ds; tdc+=1; break

            elif zone["type"]=="supply":
                if not(zbot<=price<=ztop) or not bear or high<rbot or price>rtop or t20>0: continue
                stop=rtop*(1+0.001); risk=stop-price
                if risk<=0: continue
                target=pl(lows,5,60)
                if target>=price: target=price-risk*PARAMS["min_rr"]
                if (price-target)/risk<PARAMS["min_rr"]: continue
                ar=risk+2*SLIPPAGE
                qty=min(int(balance*PARAMS["risk_pct"]/ar),int(balance*PARAMS["leverage"]/price))
                if qty<=0: continue
                signed_body=f_body_pct if not f_body_bull else -f_body_pct
                if dt.hour in BAD_HOURS: zone["consumed"]=True; zone["consumed_date"]=ds; break
                if not(ATR_LOW<=f_ratio<=ATR_HIGH): zone["consumed"]=True; zone["consumed_date"]=ds; break
                if BODY_LOW<=signed_body<BODY_HIGH: zone["consumed"]=True; zone["consumed_date"]=ds; break
                position={"dir":"SHORT","shares":qty,"entry":ef(price,"SHORT"),
                          "stop":stop,"target":target,"initial_risk":abs(ef(price,"SHORT")-stop)}
                zone["consumed"]=True; zone["consumed_date"]=ds; tdc+=1; break

    n=wins+losses; wr=wins/n*100 if n else 0
    roi=(balance-CAPITAL)/CAPITAL*100
    llist=[t["pnl"] for t in trades if t["pnl"]<0]
    lw=long_w+long_l; sw=short_w+short_l
    lwr=long_w/lw*100 if lw else 0; swr=short_w/sw*100 if sw else 0
    losing_months=sum(1 for v in monthly.values() if v<0)
    return dict(label=threshold_label, trades=n, wins=wins, losses=losses,
                wr=wr, roi=roi, balance=balance, max_dd=max_dd*100,
                largest_loss=min(llist) if llist else 0,
                long_wr=lwr, short_wr=swr, filtered=filtered,
                losing_months=losing_months, monthly=monthly)

# ── Run all variants ─────────────────────────────────────────────────────────
configs = [
    ("No filter",      lambda t,a,p: False),
    ("Binary <=0",     lambda t,a,p: t <= 0),
    ("ATR x2",         lambda t,a,p: t < -2 * a),
    ("ATR x3",         lambda t,a,p: t < -3 * a),
    ("ATR x4",         lambda t,a,p: t < -4 * a),
    ("ATR x5",         lambda t,a,p: t < -5 * a),
    ("Pct -1.5%",      lambda t,a,p: t/p < -0.015),
    ("Pct -2.0%",      lambda t,a,p: t/p < -0.020),
    ("Pct -2.5%",      lambda t,a,p: t/p < -0.025),
    ("Pct -3.0%",      lambda t,a,p: t/p < -0.030),
]

results = []
for label, fn in configs:
    print(f"  Running: {label} ...", flush=True)
    r = run_backtest(label, fn)
    results.append(r)

print()
print(f"{'='*100}")
print(f"  {'Filter':<14} {'Trades':>7} {'WR%':>6} {'ROI%':>8} {'Balance':>11} {'MaxDD':>7} "
      f"{'LgLoss':>9} {'LongWR':>8} {'ShrtWR':>8} {'Fltrd':>6} {'LossMo':>7}")
print(f"  {'-'*98}")
for r in results:
    print(f"  {r['label']:<14} {r['trades']:>7} {r['wr']:>6.1f} {r['roi']:>+8.1f} "
          f"${r['balance']:>10,.0f} {r['max_dd']:>6.1f}% ${r['largest_loss']:>8,.0f} "
          f"{r['long_wr']:>7.1f}% {r['short_wr']:>7.1f}% {r['filtered']:>6} {r['losing_months']:>7}")

print()
print("  Key: want HIGH ROI + HIGH LongWR + LOW MaxDD + LOW LossMo")
