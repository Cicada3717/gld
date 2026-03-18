"""
momentum_backtest.py — Runner for Claude's Momentum Rotation Strategy.

Usage:
    python momentum_backtest.py

Competition settings (mirrors Antigravity's baseline):
    Capital  : $100,000
    Period   : 2026-01-14 -> 2026-03-14
    Engine   : backtrader  |  Data: yfinance daily
"""

import matplotlib
matplotlib.use('Agg')

import backtrader as bt
import yfinance as yf
import pandas as pd
import numpy as np
import datetime

from strategies.momentum_rotation import MomentumRotationStrategy

# ── Universe: diversified ETFs across equities, sectors & commodities ──────
UNIVERSE = ['SPY', 'QQQ', 'XLE', 'XLK', 'XLV', 'XLU', 'GLD']

COMPETITION_START = '2026-01-14'
COMPETITION_END   = '2026-03-14'
WARMUP_MONTHS     = 8          # Extra history so indicators are hot by start date
STARTING_CASH     = 100_000.0
COMMISSION        = 0.001      # 0.1% per trade (realistic for ETFs at IBKR)


def run_momentum_backtest():
    print("=" * 58)
    print("  MOMENTUM ROTATION STRATEGY  —  Claude's Arena Entry")
    print("=" * 58)
    print(f"  Universe   : {UNIVERSE}")
    print(f"  Period     : {COMPETITION_START} to {COMPETITION_END}")
    print(f"  Capital    : ${STARTING_CASH:,.2f}")
    print(f"  Commission : {COMMISSION*100:.1f}% per trade")
    print("=" * 58)

    # ── Extend start backwards for indicator warmup ─────────────────────────
    warmup_start = (
        pd.Timestamp(COMPETITION_START) - pd.DateOffset(months=WARMUP_MONTHS)
    ).strftime('%Y-%m-%d')

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(STARTING_CASH)
    cerebro.broker.setcommission(commission=COMMISSION)
    cerebro.broker.set_coc(True)      # Fill at today's close price

    # ── Download & register each ticker ────────────────────────────────────
    feeds_added = 0
    for ticker in UNIVERSE:
        print(f"  Downloading {ticker:5s} ...", end=' ', flush=True)
        df = yf.download(
            ticker, start=warmup_start, end=COMPETITION_END,
            interval='1d', progress=False
        )
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        if df.empty:
            print("SKIP (no data)")
            continue

        data = bt.feeds.PandasData(dataname=df, name=ticker)
        cerebro.adddata(data, name=ticker)
        feeds_added += 1
        print(f"OK  ({len(df)} bars from {df.index[0].date()})")

    if feeds_added == 0:
        print("\nERROR: No data feeds available. Aborting.")
        return

    # ── Strategy ────────────────────────────────────────────────────────────
    cerebro.addstrategy(
        MomentumRotationStrategy,
        top_n=2,
        momentum_period=126,           # 6-month momentum
        rebalance_frequency=21,        # Monthly rotation
        cash_buffer=0.02,
        trade_start=datetime.date(2026, 1, 14),   # Competition start
    )

    # ── Analyzers ───────────────────────────────────────────────────────────
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe',
                        riskfreerate=0.04, annualize=True)
    cerebro.addanalyzer(bt.analyzers.DrawDown,    _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns,     _name='returns')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    print(f"\n  Starting Portfolio Value : ${cerebro.broker.getvalue():,.2f}")
    print("  Running backtest ...\n")

    results  = cerebro.run()
    strat    = results[0]

    # ── Core metrics ────────────────────────────────────────────────────────
    final_value = cerebro.broker.getvalue()
    profit      = final_value - STARTING_CASH
    roi         = (profit / STARTING_CASH) * 100

    sharpe_a  = strat.analyzers.sharpe.get_analysis()
    dd_a      = strat.analyzers.drawdown.get_analysis()
    trade_a   = strat.analyzers.trades.get_analysis()

    sharpe_ratio = sharpe_a.get('sharperatio', None)
    max_dd       = dd_a.get('max', {}).get('drawdown', None)
    total_trades = trade_a.get('total', {}).get('closed', 0)

    print("=" * 58)
    print("  RESULTS")
    print("=" * 58)
    print(f"  Starting Portfolio  :  $100,000.00")
    print(f"  Final Portfolio     :  ${final_value:>12,.2f}")
    print(f"  Absolute Profit     :  ${profit:>+12,.2f}")
    print(f"  ROI                 :  {roi:>+.2f}%")
    if sharpe_ratio:
        print(f"  Sharpe Ratio        :  {sharpe_ratio:.3f}")
    if max_dd:
        print(f"  Max Drawdown        :  {max_dd:.2f}%")
    print(f"  Total Trades        :  {total_trades}")
    print("=" * 58)

    # ── Benchmark comparison ────────────────────────────────────────────────
    antigravity_profit = 5_669.41
    edge = profit - antigravity_profit
    print(f"\n  vs Antigravity (+${antigravity_profit:,.2f})  ->  "
          f"Claude edge: ${edge:+,.2f}  "
          f"({'WINNING' if edge > 0 else 'LOSING'})")

    # ── Save plot ───────────────────────────────────────────────────────────
    try:
        print("\n  Generating plot ...")
        fig = cerebro.plot(style='bar', volume=False)[0][0]
        fname = 'MomentumRotation_backtest.png'
        fig.savefig(fname, dpi=150, bbox_inches='tight')
        print(f"  Plot saved -> {fname}")
    except Exception as e:
        print(f"  Plot error (non-fatal): {e}")

    return final_value, profit, roi, sharpe_ratio, max_dd, total_trades


if __name__ == '__main__':
    run_momentum_backtest()
