"""
btc_trades.py -- Run ClaudeGoldAlpha on BTC-USD from 2026-01-01 to 2026-03-14.
BTC is priced ~$90K-$110K so we use fractional sizing (qty as float).
"""
import datetime
import warnings
warnings.filterwarnings('ignore')

import backtrader as bt
import yfinance as yf
import pandas as pd

WARMUP_MONTHS = 14
CASH = 100_000.0
TICKER = 'BTC-USD'
START  = '2026-01-01'
END    = '2026-03-14'


class BTCAlpha(bt.Strategy):
    """
    ClaudeGoldAlpha logic adapted for BTC (fractional sizing, no int truncation).
    EMA5 > EMA30 entry, ATR x4.0 trailing stop, 5x leverage.
    """
    params = (
        ('fast_ema', 5),
        ('slow_ema', 30),
        ('atr_period', 14),
        ('trailing_stop_mult', 4.0),
        ('leverage', 5.0),
        ('real_cash', 100_000.0),
        ('trade_start', None),
    )

    def __init__(self):
        self.fast = bt.indicators.EMA(self.data.close, period=self.params.fast_ema)
        self.slow = bt.indicators.EMA(self.data.close, period=self.params.slow_ema)
        self.atr  = bt.indicators.ATR(self.data, period=self.params.atr_period)
        self.trailing_stop = 0
        self.trades_log = []
        self.entry_price = None
        self.entry_date  = None
        self.entry_qty   = None

    def next(self):
        if self.params.trade_start and self.data.datetime.date(0) < self.params.trade_start:
            return
        if len(self.data) < self.params.slow_ema:
            return

        dt    = self.data.datetime.date(0)
        close = self.data.close[0]
        atr   = self.atr[0]

        if not self.position:
            if self.fast[0] > self.slow[0]:
                target_value = self.params.real_cash * self.params.leverage * 0.90
                qty = target_value / close          # float -- fractional BTC
                self.buy(size=qty)
                self.trailing_stop = close - atr * self.params.trailing_stop_mult
                self.entry_price = close
                self.entry_date  = dt
                self.entry_qty   = qty
                print(f"  [BUY ] {dt}  price={close:,.2f}  qty={qty:.6f} BTC  "
                      f"stop={self.trailing_stop:,.2f}")
        else:
            new_stop = close - atr * self.params.trailing_stop_mult
            if new_stop > self.trailing_stop:
                self.trailing_stop = new_stop

            if close <= self.trailing_stop:
                pnl     = (close - self.entry_price) * self.entry_qty
                pnl_pct = (close - self.entry_price) / self.entry_price * 100 * self.params.leverage
                print(f"  [STOP] {dt}  price={close:,.2f}  "
                      f"stop={self.trailing_stop:,.2f}  "
                      f"P&L={pnl:+,.0f} ({pnl_pct:+.2f}%)")
                self.trades_log.append(dict(
                    entry_date=self.entry_date, entry_price=self.entry_price,
                    exit_date=dt, exit_price=close,
                    qty=self.entry_qty, pnl=pnl, pnl_pct=pnl_pct, reason='stop'
                ))
                self.close()
                self.trailing_stop = 0
                self.entry_price = None

    def stop(self):
        if self.position and self.entry_price:
            close   = self.data.close[0]
            dt      = self.data.datetime.date(0)
            pnl     = (close - self.entry_price) * self.entry_qty
            pnl_pct = (close - self.entry_price) / self.entry_price * 100 * self.params.leverage
            print(f"  [END ] {dt}  price={close:,.2f}  "
                  f"P&L={pnl:+,.0f} ({pnl_pct:+.2f}%)")
            self.trades_log.append(dict(
                entry_date=self.entry_date, entry_price=self.entry_price,
                exit_date=dt, exit_price=close,
                qty=self.entry_qty, pnl=pnl, pnl_pct=pnl_pct, reason='period-end'
            ))


# -- SETUP ---------------------------------------------------------------------

warmup_start = (
    pd.Timestamp(START) - pd.DateOffset(months=WARMUP_MONTHS)
).strftime('%Y-%m-%d')
trade_start = datetime.date.fromisoformat(START)

print(f"\nDownloading {TICKER}  warmup from {warmup_start} to {END} ...")
df = yf.download(TICKER, start=warmup_start, end=END, interval='1d', progress=False)
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.droplevel(1)

print(f"Bars downloaded: {len(df)}  |  "
      f"Price range: ${df['Close'].min():,.0f} - ${df['Close'].max():,.0f}")

cerebro = bt.Cerebro()
cerebro.broker.setcash(CASH * 10.0)       # padding for leverage
cerebro.broker.set_shortcash(False)
cerebro.broker.set_coc(True)
cerebro.broker.setcommission(commission=0.005)

data = bt.feeds.PandasData(dataname=df)
cerebro.adddata(data)

cerebro.addstrategy(BTCAlpha,
                    trade_start=trade_start,
                    leverage=5.0,
                    real_cash=CASH)

cerebro.addanalyzer(bt.analyzers.DrawDown, _name='dd')

print(f"\nStarting portfolio : ${CASH:,.0f}")
print(f"Leverage           : 5x  (effective exposure ~${CASH*5:,.0f})")
print(f"Commission         : 0.5% per trade")
print(f"Competition window : {START}  to  {END}")
print()
print("-" * 60)
print("  TRADES")
print("-" * 60)

results = cerebro.run()
strat = results[0]

final_val  = cerebro.broker.getvalue() - (CASH * 9.0)
roi        = (final_val - CASH) / CASH * 100
max_dd     = strat.analyzers.dd.get_analysis().max.drawdown

print("-" * 60)
print()

# -- BTC price context ---------------------------------------------------------
comp_df = df[df.index >= START]
btc_start  = comp_df['Close'].iloc[0]
btc_end    = comp_df['Close'].iloc[-1]
btc_return = (btc_end - btc_start) / btc_start * 100

print("=" * 60)
print("  RESULTS  --  ClaudeGoldAlpha on BTC-USD  (2026)")
print("=" * 60)
print(f"  Start date       : {START}")
print(f"  End date         : {END}")
print(f"  BTC price start  : ${btc_start:,.2f}")
print(f"  BTC price end    : ${btc_end:,.2f}")
print(f"  BTC buy-&-hold   : {btc_return:+.2f}%  ({btc_return*5:+.2f}% at 5x)")
print()
print(f"  Strategy ROI     : {roi:+.2f}%")
print(f"  Final value      : ${final_val:,.0f}  (started $100,000)")
print(f"  Max Drawdown     : {max_dd:.2f}%")
print(f"  Total trades     : {len(strat.trades_log)}")
print()

if strat.trades_log:
    print("  Trade Detail:")
    for i, t in enumerate(strat.trades_log, 1):
        days = (t['exit_date'] - t['entry_date']).days
        print(f"   Trade {i}: {t['entry_date']} -> {t['exit_date']}  ({days}d)")
        print(f"            Buy  ${t['entry_price']:>10,.2f}   Qty {t['qty']:.6f} BTC")
        print(f"            Sell ${t['exit_price']:>10,.2f}   [{t['reason']}]")
        print(f"            P&L  ${t['pnl']:>+10,.0f}   ({t['pnl_pct']:+.2f}%)")
        print()

print("=" * 60)
