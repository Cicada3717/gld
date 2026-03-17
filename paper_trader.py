"""
paper_trader.py — ClaudeAPEX v12 Live Paper Trader
===================================================
Watches GLD 5m bars in real-time during market hours.
Logs every signal check and trade to console + CSV.

Usage:
  python paper_trader.py              # default $500 capital
  python paper_trader.py --capital 1000
  python paper_trader.py --ticker GLD --capital 500

Runs Mon-Fri 9:30 AM - 4:00 PM ET.
Press Ctrl+C to stop.
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import yfinance as yf

ET = ZoneInfo("America/New_York")

# ── Strategy Parameters (ClaudeAPEX v12 IB-optimized) ──────────────────
PARAMS = {
    "atr_short": 10,
    "atr_long": 50,
    "vei_max": 1.08,
    "ema_fast": 9,
    "ema_slow": 21,
    "atr_period": 14,
    "gap_min": 0.0010,       # 0.10%
    "entry_start": 2,        # bar 2 (~9:40 AM)
    "entry_end": 25,         # bar 25 (~11:35 AM)
    "eod_bar": 72,           # ~3:30 PM force close
    "stop_mult": 3.0,
    "risk_pct": 0.02,
    "leverage": 5.0,
}

# Railway volume path (falls back to local for dev)
DATA_DIR = Path(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "D:/trdng"))
TRADE_LOG = DATA_DIR / "paper_trades.csv"
STATE_FILE = DATA_DIR / "paper_state.json"


def ema(values, period):
    """Compute EMA from a list of floats."""
    if len(values) < period:
        return values[-1] if values else 0
    k = 2 / (period + 1)
    e = np.mean(values[:period])
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def atr(highs, lows, closes, period):
    """Compute ATR from lists."""
    if len(closes) < 2 or len(highs) < period:
        return 0
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i - 1]),
                 abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    if len(trs) < period:
        return np.mean(trs) if trs else 0
    # Simple EMA-based ATR
    a = np.mean(trs[:period])
    for v in trs[period:]:
        a = (a * (period - 1) + v) / period
    return a


def vwap_today(bars_today):
    """Compute VWAP from today's bars (list of dicts with h, l, c, v)."""
    cpv = 0
    cv = 0
    for b in bars_today:
        tp = (b["h"] + b["l"] + b["c"]) / 3
        vol = max(b["v"], 1)
        cpv += tp * vol
        cv += vol
    return cpv / cv if cv > 0 else bars_today[-1]["c"]


def load_state():
    """Load persistent state (portfolio, open position)."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return None


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def log_trade(row):
    """Append trade to CSV log."""
    exists = TRADE_LOG.exists()
    with open(TRADE_LOG, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "date", "time", "action", "dir", "shares", "price",
            "stop", "reason", "pnl", "balance", "signal_details"
        ])
        if not exists:
            w.writeheader()
        w.writerow(row)


def fetch_bars(ticker, days=5):
    """Fetch recent 5m bars for indicator warmup + today."""
    df = yf.download(ticker, period=f"{days}d", interval="5m", progress=False)
    if hasattr(df.columns, "droplevel") and isinstance(df.columns, type(df.columns)):
        try:
            df.columns = df.columns.droplevel(1)
        except (ValueError, IndexError):
            pass
    df.dropna(inplace=True)
    return df


def print_status(state, msg=""):
    now = datetime.now(ET).strftime("%H:%M:%S")
    pos = state.get("position")
    bal = state["balance"]
    if pos:
        d = pos["dir"]
        entry = pos["entry"]
        shares = pos["shares"]
        print(f"  [{now}]  Balance: ${bal:,.2f}  |  {d} {shares}sh @ ${entry:.2f}  |  {msg}")
    else:
        print(f"  [{now}]  Balance: ${bal:,.2f}  |  FLAT  |  {msg}")


def run(ticker="GLD", capital=500.0):
    print(f"\n{'='*70}")
    print(f"  ClaudeAPEX v12 Paper Trader")
    print(f"  Ticker: {ticker}  |  Capital: ${capital:,.0f}  |  Leverage: {PARAMS['leverage']}x")
    print(f"  Commission: 0.01% (IB)  |  Gap min: {PARAMS['gap_min']*100:.2f}%")
    print(f"  Entry window: bar {PARAMS['entry_start']}-{PARAMS['entry_end']}")
    print(f"  Log: {TRADE_LOG}")
    print(f"{'='*70}\n")

    # Load or init state
    state = load_state()
    if state and state.get("ticker") == ticker:
        print(f"  Resuming — Balance: ${state['balance']:,.2f}, "
              f"Trades: {state['total_trades']}, P&L: ${state['total_pnl']:+,.2f}")
    else:
        state = {
            "ticker": ticker,
            "capital": capital,
            "balance": capital,
            "position": None,       # {dir, shares, entry, stop, trail, bar_count}
            "today": None,
            "bar_count": 0,
            "prior_close": 0,
            "traded_today": False,
            "total_trades": 0,
            "total_pnl": 0.0,
            "wins": 0,
            "losses": 0,
        }
        save_state(state)
        print(f"  Starting fresh — ${capital:,.0f}")

    print(f"\n  Waiting for market hours (9:30 AM - 4:00 PM ET)...")
    print(f"  Press Ctrl+C to stop.\n")

    last_bar_time = None

    while True:
        try:
            now = datetime.now(ET)

            # Only run Mon-Fri
            if now.weekday() >= 5:
                time.sleep(60)
                continue

            market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
            market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)

            # Before market
            if now < market_open:
                wait = (market_open - now).total_seconds()
                if wait > 300:
                    print(f"  Market opens in {wait/60:.0f}m — sleeping...")
                    time.sleep(min(wait - 60, 300))
                else:
                    time.sleep(30)
                continue

            # After market
            if now > market_close:
                # Force close if position open
                if state["position"]:
                    _force_close(state, ticker, "EOD")
                # Reset for tomorrow
                if state["today"] == now.strftime("%Y-%m-%d"):
                    state["traded_today"] = False
                    state["today"] = None
                    save_state(state)
                next_open = market_open + timedelta(days=1)
                while next_open.weekday() >= 5:
                    next_open += timedelta(days=1)
                wait = (next_open - now).total_seconds()
                print(f"  Market closed. Next open: {next_open.strftime('%Y-%m-%d %H:%M ET')}")
                time.sleep(min(wait, 3600))
                continue

            # ── Fetch latest bars ─────────────────────────────────────
            df = fetch_bars(ticker, days=10)
            if df.empty:
                time.sleep(30)
                continue

            # Check if new bar
            latest_time = df.index[-1]
            if last_bar_time and latest_time <= last_bar_time:
                time.sleep(15)
                continue
            last_bar_time = latest_time

            # ── Compute indicators ────────────────────────────────────
            closes = df["Close"].tolist()
            highs = df["High"].tolist()
            lows = df["Low"].tolist()
            volumes = df["Volume"].tolist()

            atr_val = atr(highs, lows, closes, PARAMS["atr_period"])
            atr_s = atr(highs, lows, closes, PARAMS["atr_short"])
            atr_l = atr(highs, lows, closes, PARAMS["atr_long"])
            vei = atr_s / atr_l if atr_l > 0 else 1.0
            ema_f = ema(closes, PARAMS["ema_fast"])
            ema_s = ema(closes, PARAMS["ema_slow"])

            # Today's bars for VWAP
            today_str = now.strftime("%Y-%m-%d")
            today_mask = df.index.strftime("%Y-%m-%d") == today_str
            df_today = df[today_mask]

            if len(df_today) == 0:
                time.sleep(15)
                continue

            bars_today = [{"h": r["High"], "l": r["Low"], "c": r["Close"], "v": r["Volume"]}
                          for _, r in df_today.iterrows()]
            vwap_val = vwap_today(bars_today)

            bar_num = len(df_today)
            price = closes[-1]

            # New day detection
            if state["today"] != today_str:
                # Close any position from yesterday
                if state["position"]:
                    _force_close(state, ticker, "NEW_DAY")

                # Find prior close (last bar of previous day)
                prev_mask = ~today_mask
                if prev_mask.any():
                    state["prior_close"] = df[prev_mask]["Close"].iloc[-1]

                state["today"] = today_str
                state["bar_count"] = 0
                state["traded_today"] = False
                save_state(state)
                print(f"\n  ── New Day: {today_str} ──")
                print(f"  Prior close: ${state['prior_close']:.2f}")

            state["bar_count"] = bar_num

            # ── Manage open position ──────────────────────────────────
            if state["position"]:
                pos = state["position"]

                # EOD force close
                if bar_num >= PARAMS["eod_bar"]:
                    _close_position(state, price, "EOD")
                    continue

                # Trailing stop
                if pos["dir"] == "LONG":
                    new_trail = price - atr_val * PARAMS["stop_mult"]
                    if new_trail > pos["trail"]:
                        pos["trail"] = new_trail
                    if price <= pos["trail"]:
                        _close_position(state, price, "STOP")
                elif pos["dir"] == "SHORT":
                    new_trail = price + atr_val * PARAMS["stop_mult"]
                    if new_trail < pos["trail"]:
                        pos["trail"] = new_trail
                    if price >= pos["trail"]:
                        _close_position(state, price, "STOP")

                save_state(state)
                if bar_num % 5 == 0:
                    unrealized = _unrealized_pnl(state, price)
                    print_status(state, f"Bar {bar_num} | ${price:.2f} | Trail ${pos['trail']:.2f} | Unreal: ${unrealized:+.2f}")
                continue

            # ── Entry scan ────────────────────────────────────────────
            if state["traded_today"]:
                if bar_num % 10 == 0:
                    print_status(state, f"Bar {bar_num} | Already traded today")
                time.sleep(15)
                continue

            if bar_num < PARAMS["entry_start"] or bar_num > PARAMS["entry_end"]:
                if bar_num % 10 == 0:
                    window = "too early" if bar_num < PARAMS["entry_start"] else "window closed"
                    print_status(state, f"Bar {bar_num} | {window}")
                time.sleep(15)
                continue

            # VEI gate
            if vei >= PARAMS["vei_max"]:
                print_status(state, f"Bar {bar_num} | VEI {vei:.3f} >= {PARAMS['vei_max']} — BLOCKED")
                time.sleep(15)
                continue

            # Gap calculation
            if state["prior_close"] <= 0:
                time.sleep(15)
                continue

            gap = (price - state["prior_close"]) / state["prior_close"]
            ema_bull = ema_f > ema_s

            # Position size
            if atr_val <= 0:
                time.sleep(15)
                continue
            risk_shares = int(state["balance"] * PARAMS["risk_pct"] /
                              (atr_val * PARAMS["stop_mult"]))
            lev_shares = int(state["balance"] * PARAMS["leverage"] / price)
            qty = min(risk_shares, lev_shares)
            if qty <= 0:
                print_status(state, f"Bar {bar_num} | Qty=0 (balance too low)")
                time.sleep(15)
                continue

            # ── LONG signal ───────────────────────────────────────────
            if (gap >= PARAMS["gap_min"] and price > vwap_val and ema_bull):
                trail = price - atr_val * PARAMS["stop_mult"]
                state["position"] = {
                    "dir": "LONG",
                    "shares": qty,
                    "entry": price,
                    "trail": trail,
                    "stop_init": trail,
                    "entry_time": now.strftime("%H:%M"),
                    "entry_bar": bar_num,
                }
                state["traded_today"] = True
                save_state(state)

                print(f"\n  *** LONG {qty} shares @ ${price:.2f} ***")
                print(f"      Stop: ${trail:.2f}  |  Gap: {gap*100:+.2f}%  |  VWAP: ${vwap_val:.2f}  |  VEI: {vei:.3f}")

                log_trade({
                    "date": today_str, "time": now.strftime("%H:%M"),
                    "action": "BUY", "dir": "LONG", "shares": qty,
                    "price": round(price, 2), "stop": round(trail, 2),
                    "reason": "SIGNAL", "pnl": "",
                    "balance": round(state["balance"], 2),
                    "signal_details": f"gap={gap*100:+.2f}% vwap={vwap_val:.2f} vei={vei:.3f} atr={atr_val:.3f}"
                })

            # ── SHORT signal ──────────────────────────────────────────
            elif (gap <= -PARAMS["gap_min"] and price < vwap_val and not ema_bull):
                trail = price + atr_val * PARAMS["stop_mult"]
                state["position"] = {
                    "dir": "SHORT",
                    "shares": qty,
                    "entry": price,
                    "trail": trail,
                    "stop_init": trail,
                    "entry_time": now.strftime("%H:%M"),
                    "entry_bar": bar_num,
                }
                state["traded_today"] = True
                save_state(state)

                print(f"\n  *** SHORT {qty} shares @ ${price:.2f} ***")
                print(f"      Stop: ${trail:.2f}  |  Gap: {gap*100:+.2f}%  |  VWAP: ${vwap_val:.2f}  |  VEI: {vei:.3f}")

                log_trade({
                    "date": today_str, "time": now.strftime("%H:%M"),
                    "action": "SELL", "dir": "SHORT", "shares": qty,
                    "price": round(price, 2), "stop": round(trail, 2),
                    "reason": "SIGNAL", "pnl": "",
                    "balance": round(state["balance"], 2),
                    "signal_details": f"gap={gap*100:+.2f}% vwap={vwap_val:.2f} vei={vei:.3f} atr={atr_val:.3f}"
                })

            else:
                # No signal — show why
                if bar_num % 5 == 0:
                    reasons = []
                    if abs(gap) < PARAMS["gap_min"]:
                        reasons.append(f"gap {gap*100:+.3f}% < {PARAMS['gap_min']*100:.2f}%")
                    if gap > 0 and price <= vwap_val:
                        reasons.append(f"price ${price:.2f} <= VWAP ${vwap_val:.2f}")
                    if gap > 0 and not ema_bull:
                        reasons.append("EMA bearish")
                    if gap < 0 and price >= vwap_val:
                        reasons.append(f"price ${price:.2f} >= VWAP ${vwap_val:.2f}")
                    if gap < 0 and ema_bull:
                        reasons.append("EMA bullish")
                    print_status(state, f"Bar {bar_num} | No signal: {', '.join(reasons)}")

            time.sleep(15)

        except KeyboardInterrupt:
            print(f"\n\n  Stopping paper trader...")
            if state["position"]:
                print(f"  WARNING: Open position — {state['position']['dir']} "
                      f"{state['position']['shares']}sh @ ${state['position']['entry']:.2f}")
            _print_summary(state)
            save_state(state)
            break
        except Exception as e:
            print(f"  ERROR: {e}")
            time.sleep(30)


def _unrealized_pnl(state, price):
    pos = state["position"]
    if not pos:
        return 0
    if pos["dir"] == "LONG":
        return (price - pos["entry"]) * pos["shares"]
    else:
        return (pos["entry"] - price) * pos["shares"]


def _close_position(state, price, reason):
    pos = state["position"]
    if not pos:
        return

    if pos["dir"] == "LONG":
        pnl = (price - pos["entry"]) * pos["shares"]
    else:
        pnl = (pos["entry"] - price) * pos["shares"]

    # Commission (0.01% each way)
    comm = pos["entry"] * pos["shares"] * 0.0001 + price * pos["shares"] * 0.0001
    net_pnl = pnl - comm

    state["balance"] += net_pnl
    state["total_pnl"] += net_pnl
    state["total_trades"] += 1
    if net_pnl > 0:
        state["wins"] += 1
    else:
        state["losses"] += 1
    state["position"] = None

    now = datetime.now(ET)
    tag = "WIN" if net_pnl > 0 else "LOSS"

    print(f"\n  *** CLOSE {pos['dir']} {pos['shares']}sh @ ${price:.2f} ({reason}) ***")
    print(f"      Entry: ${pos['entry']:.2f} → Exit: ${price:.2f}  |  Net: ${net_pnl:+.2f}  [{tag}]")
    print(f"      Balance: ${state['balance']:,.2f}  |  Total P&L: ${state['total_pnl']:+,.2f}")

    log_trade({
        "date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M"),
        "action": "CLOSE", "dir": pos["dir"], "shares": pos["shares"],
        "price": round(price, 2), "stop": round(pos["trail"], 2),
        "reason": reason, "pnl": round(net_pnl, 2),
        "balance": round(state["balance"], 2),
        "signal_details": f"entry={pos['entry']:.2f} comm={comm:.2f}"
    })
    save_state(state)


def _force_close(state, ticker, reason):
    """Force close using latest market price."""
    try:
        df = yf.download(ticker, period="1d", interval="5m", progress=False)
        if hasattr(df.columns, "droplevel"):
            try:
                df.columns = df.columns.droplevel(1)
            except (ValueError, IndexError):
                pass
        price = df["Close"].iloc[-1]
        _close_position(state, price, reason)
    except Exception as e:
        print(f"  ERROR force-closing: {e}")


def _print_summary(state):
    n = state["total_trades"]
    w = state["wins"]
    l = state["losses"]
    wr = w / n * 100 if n else 0
    roi = (state["balance"] - state["capital"]) / state["capital"] * 100
    print(f"\n  {'='*50}")
    print(f"  PAPER TRADING SUMMARY")
    print(f"  {'─'*50}")
    print(f"  Starting Capital : ${state['capital']:,.2f}")
    print(f"  Current Balance  : ${state['balance']:,.2f}")
    print(f"  Total P&L        : ${state['total_pnl']:+,.2f}")
    print(f"  ROI              : {roi:+.2f}%")
    print(f"  Trades           : {n}")
    print(f"  Wins / Losses    : {w} / {l}  ({wr:.1f}%)")
    print(f"  {'='*50}\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", default="GLD")
    ap.add_argument("--capital", type=float, default=500.0)
    args = ap.parse_args()
    run(ticker=args.ticker, capital=args.capital)
