"""
show_trades.py  — Print every trade ClaudeGoldAlpha made across the 12-month arena.
"""
import datetime
import warnings
warnings.filterwarnings('ignore')

import backtrader as bt
import yfinance as yf
import pandas as pd
from strategies.claude_gold_alpha import ClaudeGoldAlpha

WARMUP_MONTHS = 14
CASH = 100_000.0

MONTHS = [
    ('2025-03-01', '2025-03-31'),
    ('2025-04-01', '2025-04-30'),
    ('2025-05-01', '2025-05-31'),
    ('2025-06-01', '2025-06-30'),
    ('2025-07-01', '2025-07-31'),
    ('2025-08-01', '2025-08-31'),
    ('2025-09-01', '2025-09-30'),
    ('2025-10-01', '2025-10-31'),
    ('2025-11-01', '2025-11-30'),
    ('2025-12-01', '2025-12-31'),
    ('2026-01-01', '2026-01-31'),
    ('2026-02-01', '2026-02-28'),
]


class TradeLogger(bt.Strategy):
    params = (
        ('fast_ema', 5),
        ('slow_ema', 30),
        ('atr_period', 14),
        ('trailing_stop_mult', 4.0),
        ('leverage', 5.0),
        ('real_cash', 100000.0),
        ('trade_start', None),
    )

    def __init__(self):
        self.fast = bt.indicators.EMA(self.data.close, period=self.params.fast_ema)
        self.slow = bt.indicators.EMA(self.data.close, period=self.params.slow_ema)
        self.atr = bt.indicators.ATR(self.data, period=self.params.atr_period)
        self.trailing_stop = 0
        self.trades_log = []
        self.entry_price = None
        self.entry_date = None
        self.entry_qty = None

    def next(self):
        if self.params.trade_start and self.data.datetime.date(0) < self.params.trade_start:
            return
        if len(self.data) < self.params.slow_ema:
            return

        if not self.position:
            if self.fast[0] > self.slow[0]:
                target_value = self.params.real_cash * self.params.leverage * 0.90
                qty = int(target_value / self.data.close[0])
                self.buy(size=qty)
                self.trailing_stop = self.data.close[0] - (self.atr[0] * self.params.trailing_stop_mult)
                self.entry_price = self.data.close[0]
                self.entry_date = self.data.datetime.date(0)
                self.entry_qty = qty
        else:
            new_stop = self.data.close[0] - (self.atr[0] * self.params.trailing_stop_mult)
            if new_stop > self.trailing_stop:
                self.trailing_stop = new_stop

            if self.data.close[0] <= self.trailing_stop:
                exit_price = self.data.close[0]
                exit_date = self.data.datetime.date(0)
                pnl = (exit_price - self.entry_price) * self.entry_qty
                pnl_pct = (exit_price - self.entry_price) / self.entry_price * 100 * self.params.leverage
                self.trades_log.append({
                    'entry_date': self.entry_date,
                    'entry_price': self.entry_price,
                    'exit_date': exit_date,
                    'exit_price': exit_price,
                    'qty': self.entry_qty,
                    'stop': self.trailing_stop,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'reason': 'stop'
                })
                self.close()
                self.trailing_stop = 0
                self.entry_price = None

    def stop(self):
        # If still in position at month end, record as forced close
        if self.position and self.entry_price:
            exit_price = self.data.close[0]
            exit_date = self.data.datetime.date(0)
            pnl = (exit_price - self.entry_price) * self.entry_qty
            pnl_pct = (exit_price - self.entry_price) / self.entry_price * 100 * self.params.leverage
            self.trades_log.append({
                'entry_date': self.entry_date,
                'entry_price': self.entry_price,
                'exit_date': exit_date,
                'exit_price': exit_price,
                'qty': self.entry_qty,
                'stop': self.trailing_stop,
                'pnl': pnl,
                'pnl_pct': pnl_pct,
                'reason': 'month-end'
            })


def run_month(start_str, end_str):
    warmup_start = (
        pd.Timestamp(start_str) - pd.DateOffset(months=WARMUP_MONTHS)
    ).strftime('%Y-%m-%d')
    trade_start = datetime.date.fromisoformat(start_str)

    # Download once
    df = yf.download('GLD', start=warmup_start, end=end_str, interval='1d', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    if df.empty:
        return None, []

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(CASH * 10.0)
    cerebro.broker.set_shortcash(False)
    cerebro.broker.set_coc(True)
    cerebro.broker.setcommission(commission=0.005)

    data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data)

    cerebro.addstrategy(TradeLogger,
                        trade_start=trade_start,
                        leverage=5.0,
                        real_cash=CASH)

    results = cerebro.run()
    strat = results[0]

    final_value = cerebro.broker.getvalue() - (CASH * 9.0)
    roi = (final_value - CASH) / CASH * 100

    return roi, strat.trades_log


# ── MAIN ─────────────────────────────────────────────────────────────────────

print()
print("=" * 72)
print("  ClaudeGoldAlpha  —  Full Trade Log  (Mar 2025 – Feb 2026)")
print("=" * 72)

all_trades = []
month_summary = []

for start, end in MONTHS:
    roi, trades = run_month(start, end)
    month_label = pd.Timestamp(start).strftime('%Y-%m')
    month_summary.append((month_label, roi, len(trades)))
    for t in trades:
        t['month'] = month_label
        all_trades.append(t)

# ── Per-month header + trade rows ─────────────────────────────────────────────
print(f"\n{'Month':<10} {'ROI':>8}   Trades")
print("-" * 40)
for label, roi, n in month_summary:
    bar = '+' if roi >= 0 else '-'
    roi_str = f"{roi:+.2f}%"
    print(f"{label:<10} {roi_str:>8}   {n} trade(s)")

# ── Full trade table ──────────────────────────────────────────────────────────
print()
print("=" * 80)
print(f"  {'Month':<8} {'Entry Date':<12} {'Buy @':>8} {'Exit Date':<12} {'Sell @':>8} "
      f"{'Qty':>6} {'P&L $':>10} {'P&L %':>8} {'Exit'}")
print("-" * 80)

total_pnl = 0
for t in all_trades:
    sign = '+' if t['pnl'] >= 0 else ''
    print(
        f"  {t['month']:<8} "
        f"{str(t['entry_date']):<12} "
        f"{t['entry_price']:>8.2f} "
        f"{str(t['exit_date']):<12} "
        f"{t['exit_price']:>8.2f} "
        f"{t['qty']:>6} "
        f"{sign}{t['pnl']:>9,.0f} "
        f"{t['pnl_pct']:>+7.2f}% "
        f"  [{t['reason']}]"
    )
    total_pnl += t['pnl']

print("-" * 80)
print(f"  {'TOTAL':>20}  {'':>12} {'':>8} {'':>12} {'':>8} {'':>6} "
      f"  {total_pnl:>+9,.0f}")

# ── Statistics ────────────────────────────────────────────────────────────────
wins  = [t for t in all_trades if t['pnl'] > 0]
loses = [t for t in all_trades if t['pnl'] <= 0]
stops = [t for t in all_trades if t['reason'] == 'stop']
mes   = [t for t in all_trades if t['reason'] == 'month-end']

print()
print("=" * 72)
print("  STATISTICS")
print("=" * 72)
print(f"  Total trades      : {len(all_trades)}")
print(f"  Winners           : {len(wins)}  ({len(wins)/max(len(all_trades),1)*100:.0f}%)")
print(f"  Losers            : {len(loses)}  ({len(loses)/max(len(all_trades),1)*100:.0f}%)")
print(f"  Stopped out       : {len(stops)}")
print(f"  Month-end closes  : {len(mes)}")
if wins:
    print(f"  Best trade        : {max(t['pnl_pct'] for t in all_trades):+.2f}%  ({max(all_trades, key=lambda x: x['pnl_pct'])['month']})")
if loses:
    print(f"  Worst trade       : {min(t['pnl_pct'] for t in all_trades):+.2f}%  ({min(all_trades, key=lambda x: x['pnl_pct'])['month']})")
print(f"  Total P&L         : ${total_pnl:+,.0f}")
print()
