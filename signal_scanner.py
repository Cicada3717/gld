"""
LFV Live Signal Scanner
=======================
Runs 24/7, polls yfinance every 5 minutes, detects LFV setups on real data,
and sends alerts via Telegram.

Setup
-----
1. Create a Telegram bot: message @BotFather -> /newbot -> copy token
2. Get your chat ID: message @userinfobot -> copy id
3. Set env vars:
     export TELEGRAM_TOKEN="123456:ABC-DEF..."
     export TELEGRAM_CHAT_ID="987654321"
4. python signal_scanner.py
   python signal_scanner.py --tickers BTC-USD GLD SPY
   python signal_scanner.py --interval 15m --tickers BTC-USD ETH-USD

Oracle Cloud Free Tier deployment:
   nohup python signal_scanner.py > scanner.log 2>&1 &
"""

import os
import time
import argparse
import logging
from datetime import datetime, timezone
from collections import deque

import numpy as np
import pandas as pd
import yfinance as yf
import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)s  %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Telegram
# ─────────────────────────────────────────────────────────────────────────────

def send_telegram(msg: str, token: str, chat_id: str):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(url, json={'chat_id': chat_id, 'text': msg,
                                     'parse_mode': 'HTML'}, timeout=10)
        if not r.ok:
            log.warning(f"Telegram error: {r.text}")
    except Exception as e:
        log.warning(f"Telegram send failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Signal logic (stateless — recomputed from scratch each poll)
# ─────────────────────────────────────────────────────────────────────────────

def _atr(high, low, close, period=14):
    tr = np.maximum(high[1:] - low[1:],
         np.maximum(np.abs(high[1:] - close[:-1]),
                    np.abs(low[1:]  - close[:-1])))
    atr = np.full(len(high), np.nan)
    atr[period] = tr[:period].mean()
    for i in range(period + 1, len(tr) + 1):
        atr[i] = (atr[i-1] * (period - 1) + tr[i-1]) / period
    return atr


def _swing_pivots(high, low, n=8):
    """Return arrays of confirmed swing high/low indices and prices."""
    sh_idx, sh_px = [], []
    sl_idx, sl_px = [], []
    for i in range(n, len(high) - n):
        if high[i] == max(high[i-n:i+n+1]):
            sh_idx.append(i); sh_px.append(high[i])
        if low[i]  == min(low[i-n:i+n+1]):
            sl_idx.append(i); sl_px.append(low[i])
    return sh_idx, sh_px, sl_idx, sl_px


def _avwap_from(idx_anchor, tp, volume):
    """AVWAP from bar index idx_anchor to end."""
    cpv = cv = 0.0
    for i in range(idx_anchor, len(tp)):
        cpv += tp[i] * volume[i]
        cv  += volume[i]
    return cpv / cv if cv > 0 else tp[-1]


def _volume_profile(high, low, tp, volume, buckets=50, vah_val_pct=0.75, lvn_ratio=0.20):
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


def detect_signal(df: pd.DataFrame, cfg: dict) -> dict | None:
    """
    Run LFV signal detection on a completed OHLCV dataframe.
    Uses bar[-1] (last CLOSED bar) as the signal bar — never the forming bar.
    Returns a signal dict or None.
    """
    swing_n        = cfg['swing_n']
    sweep_min_atr  = cfg['sweep_min_atr']
    avwap_tol      = cfg['avwap_tolerance']
    vp_lookback    = cfg['vp_lookback']
    min_rr         = cfg['min_rr']
    stop_buf       = cfg['stop_atr_buffer']

    if len(df) < vp_lookback + swing_n * 2 + 5:
        return None

    high   = df['High'].values
    low    = df['Low'].values
    close  = df['Close'].values
    volume = df['Volume'].values
    tp     = (high + low + close) / 3.0
    atr_arr = _atr(high, low, close)

    # Signal bar = last closed bar (index -1; bar[-2] in bt terms would be index -2)
    sig   = len(df) - 2        # second-to-last (last CLOSED, not the forming bar)
    atr   = atr_arr[sig]
    if np.isnan(atr) or atr == 0:
        return None

    c  = close[sig]
    h  = high[sig]
    l  = low[sig]

    # VP window
    vp_start = max(0, sig - vp_lookback)
    vp = _volume_profile(
        high[vp_start:sig+1], low[vp_start:sig+1],
        tp[vp_start:sig+1], volume[vp_start:sig+1],
        vah_val_pct=cfg.get('vah_val_pct', 0.75),
        lvn_ratio=cfg.get('lvn_ratio', 0.20),
    )

    # Swing pivots (only up to sig - confirmed pivots)
    sh_idx, sh_px, sl_idx, sl_px = _swing_pivots(
        high[:sig+1], low[:sig+1], n=swing_n
    )

    min_sweep = atr * sweep_min_atr

    # ── LONG sweep ────────────────────────────────────────────────────────────
    for i in range(len(sl_idx) - 1, max(len(sl_idx) - 4, -1), -1):
        level = sl_px[i]
        age   = sig - sl_idx[i]
        if age < swing_n + 2:
            continue
        if l < level and c > level and (level - l) >= min_sweep:
            # AVWAP check — use last swing HIGH as anchor
            avwap = None
            if sh_idx:
                anchor = sh_idx[-1]
                avwap  = _avwap_from(anchor, tp, volume)
                if c > avwap * (1 + avwap_tol):
                    continue   # price above fair value from last high

            # VP check
            if vp:
                at_lvn    = any(abs(level - lvn) <= vp['bsz'] for lvn in vp['lvn_px'])
                below_val = c <= vp['val'] + vp['bsz']
                if not at_lvn and not below_val:
                    continue

            stop      = l - atr * stop_buf
            stop_dist = c - stop
            if stop_dist <= 0:
                continue

            proj_target = vp['poc'] if (vp and vp['poc'] > c) else c + stop_dist * min_rr
            rr = (proj_target - c) / stop_dist
            if rr < min_rr:
                continue

            return {
                'direction':  'LONG',
                'ticker':     cfg['ticker'],
                'bar_time':   df.index[sig],
                'entry':      round(c, 4),
                'stop':       round(stop, 4),
                'proj_target': round(proj_target, 4),
                'proj_rr':    round(rr, 2),
                'swept_lvl':  round(level, 4),
                'avwap':      round(avwap, 4) if avwap else None,
                'poc':        round(vp['poc'], 4) if vp else None,
                'atr':        round(atr, 4),
            }

    # ── SHORT sweep ───────────────────────────────────────────────────────────
    for i in range(len(sh_idx) - 1, max(len(sh_idx) - 4, -1), -1):
        level = sh_px[i]
        age   = sig - sh_idx[i]
        if age < swing_n + 2:
            continue
        if h > level and c < level and (h - level) >= min_sweep:
            avwap = None
            if sl_idx:
                anchor = sl_idx[-1]
                avwap  = _avwap_from(anchor, tp, volume)
                if c < avwap * (1 - avwap_tol):
                    continue

            if vp:
                at_lvn    = any(abs(level - lvn) <= vp['bsz'] for lvn in vp['lvn_px'])
                above_vah = c >= vp['vah'] - vp['bsz']
                if not at_lvn and not above_vah:
                    continue

            stop      = h + atr * stop_buf
            stop_dist = stop - c
            if stop_dist <= 0:
                continue

            proj_target = vp['poc'] if (vp and vp['poc'] < c) else c - stop_dist * min_rr
            rr = (c - proj_target) / stop_dist
            if rr < min_rr:
                continue

            return {
                'direction':  'SHORT',
                'ticker':     cfg['ticker'],
                'bar_time':   df.index[sig],
                'entry':      round(c, 4),
                'stop':       round(stop, 4),
                'proj_target': round(proj_target, 4),
                'proj_rr':    round(rr, 2),
                'swept_lvl':  round(level, 4),
                'avwap':      round(avwap, 4) if avwap else None,
                'poc':        round(vp['poc'], 4) if vp else None,
                'atr':        round(atr, 4),
            }

    return None


def format_alert(sig: dict) -> str:
    emoji = "🟢" if sig['direction'] == 'LONG' else "🔴"
    return (
        f"{emoji} <b>LFV {sig['direction']} — {sig['ticker']}</b>\n"
        f"Time     : {sig['bar_time']}\n"
        f"Entry    : {sig['entry']:,.2f}\n"
        f"Stop     : {sig['stop']:,.2f}\n"
        f"Target   : {sig['proj_target']:,.2f}\n"
        f"Proj R:R : {sig['proj_rr']:.1f}x\n"
        f"Swept    : {sig['swept_lvl']:,.2f}\n"
        f"AVWAP    : {sig['avwap']:,.2f}\n"
        f"POC      : {sig['poc']:,.2f}\n"
        f"ATR      : {sig['atr']:,.2f}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main scanner loop
# ─────────────────────────────────────────────────────────────────────────────

INTERVAL_PERIOD = {'1m': '7d', '5m': '60d', '15m': '60d', '30m': '60d', '1h': '730d'}
INTERVAL_SECS   = {'1m': 60,   '5m': 300,   '15m': 900,   '30m': 1800,  '1h': 3600}


def run_scanner(tickers, interval, cfg_overrides, telegram_token, telegram_chat_id):
    period   = INTERVAL_PERIOD.get(interval, '60d')
    poll_sec = INTERVAL_SECS.get(interval, 300)

    # Track last signal bar per ticker to avoid duplicate alerts
    last_signal_bar = {t: None for t in tickers}

    log.info(f"Scanner started | tickers={tickers} interval={interval} poll={poll_sec}s")
    if telegram_token:
        send_telegram(
            f"LFV Scanner started\nTickers: {', '.join(tickers)}\nInterval: {interval}",
            telegram_token, telegram_chat_id
        )

    while True:
        for ticker in tickers:
            try:
                df = yf.download(ticker, period=period, interval=interval,
                                 auto_adjust=True, progress=False)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(1)
                df.dropna(inplace=True)

                if len(df) < 50:
                    log.warning(f"{ticker}: only {len(df)} bars, skipping")
                    continue

                cfg = {
                    'ticker':         ticker,
                    'swing_n':        8,
                    'sweep_min_atr':  0.4,
                    'avwap_tolerance': 0.007,
                    'vp_lookback':    80,
                    'vah_val_pct':    0.75,
                    'lvn_ratio':      0.20,
                    'stop_atr_buffer': 1.0,
                    'min_rr':         3.5,
                    **cfg_overrides.get(ticker, {}),
                }

                sig = detect_signal(df, cfg)

                if sig is None:
                    log.info(f"{ticker}: no signal")
                    continue

                # Deduplicate — don't re-alert same bar
                bar_key = str(sig['bar_time'])
                if last_signal_bar[ticker] == bar_key:
                    log.info(f"{ticker}: signal already sent for bar {bar_key}")
                    continue

                last_signal_bar[ticker] = bar_key
                msg = format_alert(sig)
                log.info(f"\n{msg}")

                if telegram_token:
                    send_telegram(msg, telegram_token, telegram_chat_id)

            except Exception as e:
                log.error(f"{ticker}: error — {e}", exc_info=True)

        # Sleep until next bar close (aligned to interval boundaries)
        now     = time.time()
        next_t  = (now // poll_sec + 1) * poll_sec + 10  # +10s for bar to close
        sleep_s = next_t - now
        log.info(f"Next poll in {sleep_s:.0f}s")
        time.sleep(sleep_s)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description='LFV Live Signal Scanner')
    ap.add_argument('--tickers',  nargs='+', default=['BTC-USD'],
                    help='Tickers to scan (e.g. BTC-USD GLD SPY)')
    ap.add_argument('--interval', default='5m',
                    help='Bar interval: 1m 5m 15m 30m 1h')
    ap.add_argument('--token',    default=os.getenv('TELEGRAM_TOKEN', ''),
                    help='Telegram bot token (or set TELEGRAM_TOKEN env var)')
    ap.add_argument('--chat-id',  default=os.getenv('TELEGRAM_CHAT_ID', ''),
                    help='Telegram chat ID (or set TELEGRAM_CHAT_ID env var)')
    args = ap.parse_args()

    if not args.token:
        log.warning("No Telegram token — alerts will print to console only")

    # Per-ticker param overrides (GLD uses equity params, BTC uses crypto params)
    cfg_overrides = {
        'GLD': {
            'swing_n': 3, 'sweep_min_atr': 0.3, 'avwap_tolerance': 0.01,
            'vp_lookback': 100, 'vah_val_pct': 0.8, 'lvn_ratio': 0.25,
            'stop_atr_buffer': 1.25, 'min_rr': 3.0,
        },
    }

    run_scanner(
        tickers          = args.tickers,
        interval         = args.interval,
        cfg_overrides    = cfg_overrides,
        telegram_token   = args.token,
        telegram_chat_id = args.chat_id,
    )


if __name__ == '__main__':
    main()
