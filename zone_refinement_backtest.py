"""
Zone Refinement Backtest
========================
Pre-computes 4H supply/demand zones (with 1H refinement) then runs the
ZoneRefinement strategy on 1H bars.

Two Steps Down: HTF=4H → LTF=1H (one step). Pass --two-step to refine
further to 30M (second step) — in that case the strategy runs on 30M bars
with zones refined to the 30M initiating candle inside the 1H sub-zone.

Usage:
  python zone_refinement_backtest.py --ticker GLD
  python zone_refinement_backtest.py --ticker GLD --start 2025-01-01 --end 2026-01-01
  python zone_refinement_backtest.py --ticker GLD --plot
  python zone_refinement_backtest.py --ticker GLD --two-step
"""

import argparse
import datetime

import matplotlib
matplotlib.use('Agg')

import backtrader as bt
import yfinance as yf
import pandas as pd
import numpy as np

from strategies.zone_refinement import ZoneRefinement


# ── ATR helper (pandas-based, for pre-processing) ─────────────────────────────

def _atr(df, period=14):
    high  = df['High']
    low   = df['Low']
    close = df['Close']
    prev  = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev).abs(),
        (low  - prev).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


# ── Zone detection ─────────────────────────────────────────────────────────────

def detect_zones(df_htf, df_ltf,
                 strength_bars=3,
                 strength_mult=2.0,
                 atr_period=14):
    """
    Detect supply and demand zones on the HTF data and refine each zone
    to the initiating candle found on the LTF data.

    Parameters
    ----------
    df_htf        : OHLCV DataFrame at the higher time frame (e.g. 4H)
    df_ltf        : OHLCV DataFrame at the lower time frame  (e.g. 1H)
    strength_bars : Number of subsequent bars that must confirm the strong move
    strength_mult : Move must exceed strength_mult × ATR to qualify
    atr_period    : ATR lookback for strength threshold

    Returns
    -------
    List of zone dicts (see ZoneRefinement docstring for schema).
    """
    atr  = _atr(df_htf, atr_period)
    zones = []

    # Ensure index is tz-naive for comparison
    ltf_idx = df_ltf.index
    if hasattr(ltf_idx, 'tz') and ltf_idx.tz is not None:
        ltf_idx = ltf_idx.tz_localize(None)
        df_ltf  = df_ltf.copy()
        df_ltf.index = ltf_idx

    htf_idx = df_htf.index
    if hasattr(htf_idx, 'tz') and htf_idx.tz is not None:
        htf_idx = htf_idx.tz_localize(None)
        df_htf  = df_htf.copy()
        df_htf.index = htf_idx

    # Detect the HTF bar interval (to define the LTF window per bar)
    if len(df_htf) >= 2:
        htf_interval = htf_idx[1] - htf_idx[0]
    else:
        htf_interval = pd.Timedelta(hours=4)

    for i in range(len(df_htf) - strength_bars):
        bar       = df_htf.iloc[i]
        ts        = htf_idx[i]
        atr_val   = atr.iloc[i]
        if pd.isna(atr_val) or atr_val <= 0:
            continue

        future    = df_htf.iloc[i + 1 : i + 1 + strength_bars]
        htf_top   = bar['High']
        htf_bot   = bar['Low']

        # ── Demand zone: strong up move follows ──────────────────────────────
        up_move = future['Close'].max() - htf_top
        if up_move >= strength_mult * atr_val:
            # Find the 1H initiating candle: the most bearish (lowest close)
            # bar inside this HTF candle's time window — the "absorption" bar
            mask = (df_ltf.index >= ts) & (df_ltf.index < ts + htf_interval)
            h1   = df_ltf[mask]
            if not h1.empty:
                idx_init  = h1['Close'].idxmin()
                init_bar  = h1.loc[idx_init]
                refined_top = float(init_bar['High'])
                refined_bot = float(init_bar['Low'])
            else:
                refined_top = htf_top
                refined_bot = htf_bot

            zones.append({
                'type':           'demand',
                'formed_at':      ts.to_pydatetime() if hasattr(ts, 'to_pydatetime') else ts,
                'htf_top':        float(htf_top),
                'htf_bottom':     float(htf_bot),
                'refined_top':    refined_top,
                'refined_bottom': refined_bot,
                'consumed':       False,
            })

        # ── Supply zone: strong down move follows ─────────────────────────────
        down_move = htf_bot - future['Close'].min()
        if down_move >= strength_mult * atr_val:
            # Find the 1H initiating candle: the most bullish (highest close) bar
            mask = (df_ltf.index >= ts) & (df_ltf.index < ts + htf_interval)
            h1   = df_ltf[mask]
            if not h1.empty:
                idx_init  = h1['Close'].idxmax()
                init_bar  = h1.loc[idx_init]
                refined_top = float(init_bar['High'])
                refined_bot = float(init_bar['Low'])
            else:
                refined_top = htf_top
                refined_bot = htf_bot

            zones.append({
                'type':           'supply',
                'formed_at':      ts.to_pydatetime() if hasattr(ts, 'to_pydatetime') else ts,
                'htf_top':        float(htf_top),
                'htf_bottom':     float(htf_bot),
                'refined_top':    refined_top,
                'refined_bottom': refined_bot,
                'consumed':       False,
            })

    return zones


# ── Optional second refinement (two-step-down: 4H → 1H → 30M) ────────────────

def refine_zones_second_step(zones, df_30m):
    """
    Further refine each zone's LTF sub-zone from 1H to 30M.
    Replaces refined_top / refined_bottom with the 30M initiating candle.
    """
    idx_30m = df_30m.index
    if hasattr(idx_30m, 'tz') and idx_30m.tz is not None:
        df_30m = df_30m.copy()
        df_30m.index = idx_30m.tz_localize(None)

    step = pd.Timedelta(hours=1)
    for zone in zones:
        ts  = pd.Timestamp(zone['formed_at'])
        top = zone['refined_top']
        bot = zone['refined_bottom']
        # 30M bars within the 1H refined window (±1H around formation)
        mask = (df_30m.index >= ts) & (df_30m.index < ts + step)
        df_w = df_30m[mask]
        # Keep only bars inside refined zone price range
        inside = df_w[(df_w['Low'] >= bot * 0.999) & (df_w['High'] <= top * 1.001)]
        if inside.empty:
            inside = df_w
        if inside.empty:
            continue
        if zone['type'] == 'demand':
            idx_init = inside['Close'].idxmin()
        else:
            idx_init = inside['Close'].idxmax()
        bar = inside.loc[idx_init]
        zone['refined_top']    = float(bar['High'])
        zone['refined_bottom'] = float(bar['Low'])
    return zones


# ── Normalise yfinance MultiIndex columns ─────────────────────────────────────

def _clean(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    if hasattr(df.index, 'tz') and df.index.tz is not None:
        df.index = df.index.tz_convert('America/New_York').tz_localize(None)
    return df


# ── Main backtest ──────────────────────────────────────────────────────────────

def run_backtest(ticker, start_date, end_date, cash, min_rr=3.0, two_step=False, args_plot=False):
    WARMUP_MONTHS = 6

    warmup_start = (
        pd.Timestamp(start_date) - pd.DateOffset(months=WARMUP_MONTHS)
    ).strftime('%Y-%m-%d')
    trade_start = datetime.date.fromisoformat(start_date)

    print(f"[ZoneRefinement] {ticker}  {start_date} to {end_date}"
          f"  two_step={two_step}")
    print(f"  Downloading data (warmup from {warmup_start})...")

    # Download HTF (4H) for zone detection
    df_4h = _clean(yf.download(ticker, start=warmup_start, end=end_date,
                                interval='1h', progress=False))   # yfinance max 4H = 1H grouping
    # yfinance doesn't provide true 4H; resample 1H → 4H
    df_1h_raw = df_4h.copy()
    df_4h = (df_1h_raw
             .resample('4h')
             .agg({'Open': 'first', 'High': 'max', 'Low': 'min',
                   'Close': 'last', 'Volume': 'sum'})
             .dropna())

    print(f"  4H bars: {len(df_4h)},  1H bars: {len(df_1h_raw)}")

    # Detect zones
    print("  Detecting zones...")
    zones = detect_zones(df_4h, df_1h_raw, strength_bars=3, strength_mult=1.5)
    demand = sum(1 for z in zones if z['type'] == 'demand')
    supply = sum(1 for z in zones if z['type'] == 'supply')
    print(f"  Found {len(zones)} zones ({demand} demand, {supply} supply)")

    # Optional: two-step refinement to 30M
    # Note: yfinance limits 30M data to the last 60 days; two-step mode auto-restricts window.
    exec_interval = '1h'
    if two_step:
        print("  Applying second refinement (4H > 1H > 30M)...")
        # yfinance 30m: max 60-day rolling window only
        df_30m = _clean(yf.download(ticker, period='59d', interval='30m', progress=False))
        if df_30m.empty:
            print("  WARNING: 30M data unavailable; falling back to 1H execution.")
        else:
            zones = refine_zones_second_step(zones, df_30m)
            exec_interval = '30m'
            df_exec = df_30m
            print(f"  30M bars: {len(df_30m)}")

    if exec_interval == '1h':
        df_exec = df_1h_raw

    if df_exec.empty:
        print("No execution-timeframe data found.")
        return

    # Backtrader setup
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(cash * 10.0)   # Padding for leverage
    cerebro.broker.set_shortcash(False)
    cerebro.broker.set_coc(True)
    cerebro.broker.setcommission(commission=0.001)

    tf = bt.TimeFrame.Minutes
    comp = 30 if exec_interval == '30m' else 60
    data = bt.feeds.PandasData(dataname=df_exec,
                                timeframe=tf, compression=comp)
    cerebro.adddata(data)

    cerebro.addstrategy(
        ZoneRefinement,
        zones=zones,
        risk_pct=0.02,
        leverage=5.0,
        real_cash=cash,
        min_rr=min_rr,
        trade_start=trade_start,
    )

    cerebro.addanalyzer(bt.analyzers.SharpeRatio,  _name='sharpe', riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.DrawDown,      _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.Returns,       _name='returns')

    print(f"  Starting value: ${cash:,.0f}")
    results = cerebro.run()

    final_raw = cerebro.broker.getvalue()
    final     = final_raw - (cash * 9.0)   # Remove leverage padding
    roi       = (final - cash) / cash * 100

    if not results:
        print("  No results.")
        return

    s = results[0]

    # ── Summary stats ─────────────────────────────────────────────────────────
    sharpe   = s.analyzers.sharpe.get_analysis().get('sharperatio', None)
    dd       = s.analyzers.drawdown.get_analysis().max.drawdown
    trades_a = s.analyzers.trades.get_analysis()
    n_closed = trades_a.get('total', {}).get('closed', 0) if isinstance(trades_a, dict) else 0
    won      = trades_a.get('won',   {}).get('total', 0) if isinstance(trades_a, dict) else 0
    lost     = trades_a.get('lost',  {}).get('total', 0) if isinstance(trades_a, dict) else 0
    win_pct  = won / n_closed * 100 if n_closed else 0

    print()
    print("=" * 70)
    print(f"  RESULTS — {ticker}  ({start_date} to {end_date})")
    print("=" * 70)
    print(f"  Final Value:    ${final:>12,.2f}  ({roi:+.2f}%)")
    print(f"  Sharpe Ratio:   {sharpe:.3f}" if sharpe else "  Sharpe Ratio:   N/A")
    print(f"  Max Drawdown:   {dd:.2f}%")
    print(f"  Total Trades:   {n_closed}  (W: {won}  L: {lost}  |  {win_pct:.0f}% win rate)")

    # ── Trade detail table ────────────────────────────────────────────────────
    log = s.trade_log
    if log:
        total_pnl   = sum(t['pnl_$'] for t in log)
        avg_rr_win  = (sum(t['rr'] for t in log if t['result'] == 'WIN') / won) if won else 0
        avg_rr_loss = (sum(t['rr'] for t in log if t['result'] == 'LOSS') / lost) if lost else 0
        avg_rr      = sum(t['rr'] for t in log) / len(log)

        print(f"  Avg R:R (all):  {avg_rr:.2f}x  "
              f"(wins {avg_rr_win:.2f}x  |  losses {avg_rr_loss:.2f}x)")
        print(f"  Total P&L:      ${total_pnl:>10,.2f}")
        print()
        print("-" * 120)
        hdr = (f"{'#':>3}  {'Entry Date':<19}  {'Exit Date':<19}  "
               f"{'Dir':<5}  {'Zone':<6}  {'Qty':>5}  "
               f"{'Entry':>7}  {'Stop':>7}  {'Target':>7}  {'Exit':>7}  "
               f"{'Pts':>7}  {'R:R':>5}  {'P&L ($)':>10}  {'Result':<6}")
        print(hdr)
        print("-" * 120)
        running_pnl = 0.
        for i, t in enumerate(log, 1):
            running_pnl += t['pnl_$']
            entry_dt = t['entry_date'].strftime('%Y-%m-%d %H:%M') if t['entry_date'] else '?'
            exit_dt  = t['exit_date'].strftime('%Y-%m-%d %H:%M')  if t['exit_date'] else '?'
            row = (f"{i:>3}  {entry_dt:<19}  {exit_dt:<19}  "
                   f"{t['direction']:<5}  {t['zone_type']:<6}  {t['size']:>5}  "
                   f"{t['entry_px']:>7.3f}  {t['stop']:>7.3f}  {t['target']:>7.3f}  "
                   f"{t['exit_px']:>7.3f}  "
                   f"{t['pnl_pts']:>+7.3f}  {t['rr']:>5.2f}  "
                   f"{t['pnl_$']:>+10.2f}  {t['result']:<6}  "
                   f"[cum ${running_pnl:+,.0f}]")
            print(row)
        print("-" * 120)
        print(f"  Net P&L: ${total_pnl:+,.2f}")
    else:
        print("  No completed trades in log.")

    if args_plot:
        try:
            fig = cerebro.plot(style='candlestick', barup='green', bardown='red')[0][0]
            out = f'{ticker}_zone_refinement.png'
            fig.savefig(out, dpi=150)
            print(f"\n  Chart saved: {out}")
        except Exception as e:
            print(f"\n  Plot error (non-fatal): {e}")
    else:
        print("\n  (use --plot to save a chart PNG)")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Zone Refinement Supply & Demand Backtest')
    parser.add_argument('--ticker',    default='GLD',        help='Ticker symbol')
    parser.add_argument('--start',     default='2025-01-01', help='Trade start YYYY-MM-DD')
    parser.add_argument('--end',       default='2026-03-01', help='End date   YYYY-MM-DD')
    parser.add_argument('--cash',      type=float, default=100_000.0)
    parser.add_argument('--min-rr',    type=float, default=3.0,    help='Minimum R:R ratio')
    parser.add_argument('--two-step',  action='store_true',
                        help='Apply second refinement step (4H→1H→30M)')
    parser.add_argument('--plot',      action='store_true',  help='Save chart PNG')
    args = parser.parse_args()

    run_backtest(
        ticker     = args.ticker,
        start_date = args.start,
        end_date   = args.end,
        cash       = args.cash,
        min_rr     = args.min_rr,
        two_step   = args.two_step,
        args_plot  = args.plot,
    )
