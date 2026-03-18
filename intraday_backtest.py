"""
intraday_backtest.py  --  ClaudeAPEX true intraday runner (5m bars)
"""
import argparse, warnings, sys, io
warnings.filterwarnings('ignore')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import backtrader as bt
import yfinance as yf
import pandas as pd
import numpy as np

from strategies.claude_apex import ClaudeAPEX

CASH       = 100_000.0
COMMISSION = 0.0001    # 0.01% per trade (Interactive Brokers)
TICKER     = 'GLD'
DAYS       = 59        # yfinance 5m rolling window max ~60 days


class IntradayTradeLogger(bt.Analyzer):
    def start(self):
        self.trades = []
        self._trade_idx = 0

    def notify_trade(self, trade):
        if trade.isclosed:
            open_dt  = bt.num2date(trade.dtopen)
            close_dt = bt.num2date(trade.dtclose)
            duration = int((close_dt - open_dt).total_seconds() / 60)
            # trade.size is 0 when closed; get shares from strategy details
            shares = 0
            strat_details = self.strategy.trade_details if hasattr(self.strategy, 'trade_details') else []
            if self._trade_idx < len(strat_details):
                shares = strat_details[self._trade_idx].get('shares', 0)
            # Compute exit price from entry + pnl
            if shares > 0:
                if trade.long:
                    exit_px = round(trade.price + trade.pnl / shares, 3)
                else:
                    exit_px = round(trade.price - trade.pnl / shares, 3)
            else:
                exit_px = 0

            # Merge with strategy's detailed entry info
            details = {}
            strat = self.strategy
            if hasattr(strat, 'trade_details') and self._trade_idx < len(strat.trade_details):
                details = strat.trade_details[self._trade_idx]
                self._trade_idx += 1

            # Get exit reason from strategy
            exit_reason = getattr(strat, '_exit_reason', '') or 'UNKNOWN'

            self.trades.append({
                'date'      : open_dt.strftime('%Y-%m-%d'),
                'entry_time': open_dt.strftime('%H:%M'),
                'exit_time' : close_dt.strftime('%H:%M'),
                'dir'       : 'LONG' if trade.long else 'SHORT',
                'shares'    : shares if shares > 0 else abs(trade.size),
                'entry_px'  : round(trade.price, 3),
                'exit_px'   : exit_px,
                'stop'      : details.get('stop', 0),
                'target'    : details.get('target'),
                'vwap'      : details.get('vwap', 0),
                'gap_pct'   : details.get('gap_pct', 0),
                'atr'       : details.get('atr', 0),
                'vei'       : details.get('vei', 0),
                'bar'       : details.get('bar', 0),
                'exit_reason': exit_reason,
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
    cerebro.addstrategy(ClaudeAPEX,
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
    print("=" * 130)
    print(f"  ClaudeAPEX v12 | {ticker} 5m Intraday | Gap Momentum | Comm {COMMISSION*100:.2f}% (IB)")
    print("=" * 130)

    days_pnl = {}
    wins = losses = 0

    for i, t in enumerate(trades):
        day = t['date']
        if day not in days_pnl:
            days_pnl[day] = 0.0
            print(f"\n  {'─'*126}")
            print(f"  [{day}]")

        days_pnl[day] += t['pnl_net']
        tag = 'WIN' if t['pnl_net'] > 0 else ('LOSS' if t['pnl_net'] < 0 else 'EVEN')
        tgt_str = f"${t['target']:.2f}" if t['target'] else 'trail'

        print(f"  #{i+1:<3} {t['dir']:>5}  {t['shares']:>5} shares @ ${t['entry_px']:<8.3f}"
              f"  Exit ${t['exit_px']:<8.3f} ({t['exit_reason']:<6})"
              f"  Net {t['pnl_net']:>+9.2f}  ROI {t['pnl_pct']:>+6.3f}%  [{tag}]")
        print(f"       Time {t['entry_time']}→{t['exit_time']} ({t['duration']}m)"
              f"  │ Stop ${t['stop']:.2f}  Target {tgt_str}"
              f"  │ Gap {t['gap_pct']:>+.2f}%  VWAP ${t['vwap']:.2f}  ATR ${t['atr']:.3f}  VEI {t['vei']:.2f}")

        if t['pnl_net'] > 0: wins   += 1
        else:                 losses += 1

    total_trades = wins + losses

    # ── DAILY SUMMARY ─────────────────────────────────────────────────────────
    print(f"\n{'='*98}")
    print(f"  DAILY P&L SUMMARY")
    print(f"  {'-'*60}")
    total_net = 0.0
    for day, pnl in sorted(days_pnl.items()):
        total_net += pnl
        bar = '#' * min(int(abs(pnl)/200), 25) if pnl >= 0 else '.' * min(int(abs(pnl)/200), 25)
        sign = '+' if pnl >= 0 else '-'
        print(f"  {day}  {pnl:>+10.2f}  {sign}|{bar}")
    print(f"  {'TOTAL':>12}  {total_net:>+10.2f}")

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
          f"  Sharpe (annualised) : N/A (too few days)")
    print(f"  {'-'*65}")
    print(f"  Total Trades        : {total_trades}")
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
    print(f"{'='*98}\n")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--ticker', default=TICKER)
    ap.add_argument('--days',   type=int, default=DAYS)
    args = ap.parse_args()
    run(ticker=args.ticker, days=args.days)
