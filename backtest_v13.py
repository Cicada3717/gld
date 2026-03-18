"""
backtest_v13.py — ClaudeAPEX v13 Multi-Signal Intraday on GLD 5m
=================================================================
Tests IB Breakout Retracement + VWAP 2SD Mean Reversion + Prior Day VA Rotation.
Target: 5-6 trades per week.
"""

import argparse, warnings, sys, io
warnings.filterwarnings('ignore')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import backtrader as bt
import yfinance as yf
import pandas as pd
import numpy as np

from strategies.claude_apex_v15 import ClaudeAPEX_v15

CASH       = 100_000.0
COMMISSION = 0.001
TICKER     = 'GLD'
DAYS       = 59


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


def run(ticker=TICKER, days=DAYS):
    print(f"\n  Downloading {ticker} 5m | last {days} days ...", flush=True)
    df = yf.download(ticker, period=f'{days}d', interval='5m', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    df.dropna(inplace=True)
    if df.empty:
        print("  ERROR: no data returned"); return

    days_actual = df.index.normalize().nunique()
    bpd = len(df) / days_actual
    print(f"  {len(df):,} bars | {days_actual} trading days | {bpd:.1f} bars/day\n")

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(CASH * 10.0)
    cerebro.broker.set_shortcash(False)
    cerebro.broker.setcommission(commission=COMMISSION)

    cerebro.adddata(bt.feeds.PandasData(dataname=df))
    cerebro.addstrategy(ClaudeAPEX_v15,
                        leverage=5.0,
                        real_cash=CASH,
                        bars_per_day=int(bpd))
    cerebro.addanalyzer(IntradayTradeLogger, _name='tl')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sr',
                        timeframe=bt.TimeFrame.Days, annualize=True, riskfreerate=0.04)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='dd')

    results = cerebro.run(stdstats=False)
    strat   = results[0]
    trades  = strat.analyzers.tl.get_analysis()
    dd      = strat.analyzers.dd.get_analysis()
    sr_val  = strat.analyzers.sr.get_analysis().get('sharperatio', 0) or 0

    final     = cerebro.broker.getvalue() - CASH * 9.0
    total_roi = (final - CASH) / CASH * 100

    # ── TRADE TABLE ──────────────────────────────────────────────────────────
    print("=" * 100)
    print(f"  ClaudeAPEX v15 | {ticker} 5m | Gap Momentum + VWAP Bounce | Comm {COMMISSION*100:.1f}%")
    print("=" * 100)
    print(f"  {'Date':<12} {'In':>5} {'Out':>5} {'Dir':>5} "
          f"{'Entry$':>8} {'Gross':>9} {'Net':>9} {'ROI%':>7} {'Min':>4}  Result")
    print(f"  {'-'*94}")

    days_pnl = {}
    weeks_pnl = {}
    wins = losses = 0

    for t in trades:
        day = t['date']
        # Week number
        week = pd.Timestamp(day).isocalendar()[1]
        week_key = f"{pd.Timestamp(day).year}-W{week:02d}"

        if day not in days_pnl:
            days_pnl[day] = 0.0
            print(f"\n  [{day}]")
        days_pnl[day] += t['pnl_net']
        weeks_pnl[week_key] = weeks_pnl.get(week_key, {'pnl': 0.0, 'trades': 0})
        weeks_pnl[week_key]['pnl'] += t['pnl_net']
        weeks_pnl[week_key]['trades'] += 1

        tag = ' WIN' if t['pnl_net'] > 0 else (' LOSS' if t['pnl_net'] < 0 else ' EVEN')
        print(f"  {day:<12} {t['entry_time']:>5} {t['exit_time']:>5} {t['dir']:>5} "
              f"{t['entry_px']:>8.3f} "
              f"{t['pnl_gross']:>+9.2f} {t['pnl_net']:>+9.2f} "
              f"{t['pnl_pct']:>+6.3f}%  {t['duration']:>3}m  {tag}")
        if t['pnl_net'] > 0: wins   += 1
        else:                 losses += 1

    total_trades = wins + losses

    # ── WEEKLY SUMMARY ───────────────────────────────────────────────────────
    print(f"\n{'='*100}")
    print(f"  WEEKLY SUMMARY")
    print(f"  {'-'*65}")
    total_net = 0.0
    for wk in sorted(weeks_pnl):
        pnl = weeks_pnl[wk]['pnl']
        cnt = weeks_pnl[wk]['trades']
        total_net += pnl
        bar = '#' * min(int(abs(pnl)/300), 25) if pnl >= 0 else '.' * min(int(abs(pnl)/300), 25)
        sign = '+' if pnl >= 0 else '-'
        print(f"  {wk}  {cnt} trades  {pnl:>+10.2f}  running: {total_net:>+10.2f}  {sign}|{bar}")
    total_net = sum(w['pnl'] for w in weeks_pnl.values())
    n_weeks = len(weeks_pnl)
    avg_trades_wk = total_trades / n_weeks if n_weeks else 0
    print(f"  {'TOTAL':>10}  {total_trades} trades  {total_net:>+10.2f}  ({avg_trades_wk:.1f} trades/week)")

    # ── METRICS ──────────────────────────────────────────────────────────────
    win_rate = wins / total_trades * 100 if total_trades else 0
    avg_win  = np.mean([t['pnl_net'] for t in trades if t['pnl_net'] > 0]) if wins   else 0
    avg_loss = np.mean([t['pnl_net'] for t in trades if t['pnl_net'] <= 0]) if losses else 0
    pf       = abs(avg_win / avg_loss) if avg_loss else 0
    exp_val  = (win_rate/100 * avg_win) + ((1-win_rate/100) * avg_loss)
    avg_dur  = np.mean([t['duration'] for t in trades]) if trades else 0

    print(f"\n{'='*100}")
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
    print(f"  Trades/Week         : {avg_trades_wk:.1f}")
    print(f"  Winners             : {wins}  ({win_rate:.1f}%)")
    print(f"  Losers              : {losses}  ({100-win_rate:.1f}%)")
    print(f"  Avg Win             : ${avg_win:>+,.2f}")
    print(f"  Avg Loss            : ${avg_loss:>+,.2f}")
    print(f"  Profit Factor       : {pf:.2f}")
    print(f"  Expected Value/tr   : ${exp_val:>+,.2f}")
    print(f"  Avg Trade Duration  : {avg_dur:.0f} min")
    print(f"  Active Trading Days : {len(days_pnl)} / {days_actual}")
    if days_pnl:
        print(f"  Trades/Active Day   : {total_trades/len(days_pnl):.1f}")
    print(f"{'='*100}\n")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--ticker', default=TICKER)
    ap.add_argument('--days',   type=int, default=DAYS)
    args = ap.parse_args()
    run(ticker=args.ticker, days=args.days)
