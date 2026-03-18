"""
backtest_2025.py — ClaudeAPEX-H1 Opening Bar Breakout on GLD 1h, 2025
======================================================================
Tests the H1-specific strategy: bar 0 defines the opening range,
breakout above/below WITH trend = entry. Market-defined stop at bar 0 extreme.
"""

import warnings, sys, io
warnings.filterwarnings('ignore')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import backtrader as bt
import yfinance as yf
import pandas as pd
import numpy as np

from strategies.claude_apex_swing import ClaudeAPEX_Swing

CASH       = 100_000.0
COMMISSION = 0.001
TICKER     = 'GLD'
START      = '2025-01-01'
END        = '2025-12-31'

# ── H1 params ────────────────────────────────────────────────────────────────
H1_PARAMS = dict(
    atr_short    = 10,
    atr_long     = 50,
    vei_max      = 1.00,     # Strict but not ultra-strict
    ema_fast     = 21,
    ema_slow     = 63,
    lookback     = 7,        # 1-day high/low (7 bars = 1 day)
    stop_mult    = 3.0,      # Wide trailing stop
    max_days     = 15,
    atr_period   = 14,
    risk_pct     = 0.02,
    leverage     = 5.0,
    real_cash    = CASH,
)


class IntradayTradeLogger(bt.Analyzer):
    def start(self):
        self.trades = []

    def notify_trade(self, trade):
        if trade.isclosed:
            open_dt  = bt.num2date(trade.dtopen)
            close_dt = bt.num2date(trade.dtclose)
            duration = int((close_dt - open_dt).total_seconds() / 60)
            self.trades.append({
                'date'      : open_dt.strftime('%Y-%m-%d'),
                'month'     : open_dt.strftime('%Y-%m'),
                'entry_time': open_dt.strftime('%H:%M'),
                'exit_time' : close_dt.strftime('%H:%M'),
                'dir'       : 'LONG' if trade.long else 'SHORT',
                'entry_px'  : round(trade.price, 3),
                'pnl_gross' : round(trade.pnl, 2),
                'pnl_net'   : round(trade.pnlcomm, 2),
                'pnl_pct'   : round(trade.pnlcomm / CASH * 100, 4),
                'duration'  : duration,
            })

    def get_analysis(self):
        return self.trades


def run():
    print(f"\n  Downloading {TICKER} 1h | {START} → {END} ...", flush=True)
    df = yf.download(TICKER, start=START, end=END,
                     interval='1h', auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    df.index = df.index.tz_localize(None)
    df.dropna(inplace=True)

    days_actual = df.index.normalize().nunique()
    bpd = len(df) / days_actual
    print(f"  {len(df):,} bars | {days_actual} trading days | {bpd:.1f} bars/day\n")

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(CASH * 10.0)
    cerebro.broker.set_shortcash(False)
    cerebro.broker.setcommission(commission=COMMISSION)

    cerebro.adddata(bt.feeds.PandasData(dataname=df))
    cerebro.addstrategy(ClaudeAPEX_Swing, **H1_PARAMS, bars_per_day=int(bpd))
    cerebro.addanalyzer(IntradayTradeLogger, _name='tl')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sr',
                        timeframe=bt.TimeFrame.Days, annualize=True,
                        riskfreerate=0.04)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='dd')

    results = cerebro.run(stdstats=False)
    strat   = results[0]
    trades  = strat.analyzers.tl.get_analysis()
    dd      = strat.analyzers.dd.get_analysis()
    sr_val  = strat.analyzers.sr.get_analysis().get('sharperatio', 0) or 0

    final     = cerebro.broker.getvalue() - CASH * 9.0
    total_roi = (final - CASH) / CASH * 100

    # ── TRADE TABLE ───────────────────────────────────────────────────────────
    print("=" * 98)
    print(f"  ClaudeAPEX-Swing | GLD 1h | Multi-Day Trend Following | 2025 | Comm 0.1%")
    print("=" * 98)
    print(f"  {'Date':<12} {'In':>5} {'Out':>5} {'Dir':>5} "
          f"{'Entry$':>8} {'Gross':>9} {'Net':>9} {'ROI%':>7} {'Hrs':>4}  Result")
    print(f"  {'-'*90}")

    days_pnl   = {}
    months_pnl = {}
    wins = losses = 0

    for t in trades:
        day = t['date']; mo = t['month']
        if day not in days_pnl:
            days_pnl[day] = 0.0
            print(f"\n  [{day}]")
        days_pnl[day]   += t['pnl_net']
        months_pnl[mo]   = months_pnl.get(mo, 0) + t['pnl_net']
        tag = ' WIN' if t['pnl_net'] > 0 else (' LOSS' if t['pnl_net'] < 0 else ' EVEN')
        hrs = t['duration'] // 60
        print(f"  {day:<12} {t['entry_time']:>5} {t['exit_time']:>5} {t['dir']:>5} "
              f"{t['entry_px']:>8.3f} "
              f"{t['pnl_gross']:>+9.2f} {t['pnl_net']:>+9.2f} "
              f"{t['pnl_pct']:>+6.3f}%  {hrs:>2}h  {tag}")
        if t['pnl_net'] > 0: wins   += 1
        else:                 losses += 1

    total_trades = wins + losses

    # ── MONTHLY SUMMARY ───────────────────────────────────────────────────────
    print(f"\n{'='*98}")
    print(f"  MONTHLY P&L SUMMARY")
    print(f"  {'-'*60}")
    running = 0.0
    for mo in sorted(months_pnl):
        pnl = months_pnl[mo]
        running += pnl
        bar  = '#' * min(int(abs(pnl)/300), 25) if pnl >= 0 else '.' * min(int(abs(pnl)/300), 25)
        sign = '+' if pnl >= 0 else '-'
        print(f"  {mo}   {pnl:>+10.2f}   running: {running:>+10.2f}   {sign}|{bar}")
    total_net = sum(months_pnl.values())
    print(f"  {'YEAR TOTAL':>10}   {total_net:>+10.2f}")

    # ── METRICS ───────────────────────────────────────────────────────────────
    win_rate = wins / total_trades * 100 if total_trades else 0
    avg_win  = np.mean([t['pnl_net'] for t in trades if t['pnl_net'] > 0]) if wins   else 0
    avg_loss = np.mean([t['pnl_net'] for t in trades if t['pnl_net'] <= 0]) if losses else 0
    pf       = abs(avg_win / avg_loss) if avg_loss else 0
    exp_val  = (win_rate/100 * avg_win) + ((1-win_rate/100) * avg_loss)
    avg_dur  = np.mean([t['duration'] for t in trades]) if trades else 0

    print(f"\n{'='*98}")
    print(f"  PERFORMANCE METRICS  |  {days_actual} trading days  |  {total_trades} trades")
    print(f"  {'-'*65}")
    print(f"  Starting Capital    : ${CASH:>12,.0f}")
    print(f"  Final Portfolio     : ${final:>12,.2f}")
    print(f"  Net P&L             : ${total_net:>+12,.2f}")
    print(f"  Total ROI           : {total_roi:>+9.2f}%")
    print(f"  Max Drawdown        : {dd.max.drawdown:.2f}%")
    print(f"  Sharpe (annualised) : {sr_val:.2f}" if sr_val else
          f"  Sharpe (annualised) : N/A")
    print(f"  {'-'*65}")
    print(f"  Total Trades        : {total_trades}")
    print(f"  Winners             : {wins}  ({win_rate:.1f}%)")
    print(f"  Losers              : {losses}  ({100-win_rate:.1f}%)")
    print(f"  Avg Win             : ${avg_win:>+,.2f}")
    print(f"  Avg Loss            : ${avg_loss:>+,.2f}")
    print(f"  Profit Factor       : {pf:.2f}")
    print(f"  Expected Value/tr   : ${exp_val:>+,.2f}")
    print(f"  Avg Trade Duration  : {avg_dur/60:.1f} hrs")
    print(f"  Active Trading Days : {len(days_pnl)} / {days_actual}")
    if days_pnl:
        print(f"  Trades/Active Day   : {total_trades/len(days_pnl):.1f}")
    print(f"{'='*98}\n")


if __name__ == '__main__':
    run()
