"""Diagnostic: print VEI values at entry time for each day."""
import backtrader as bt
import yfinance as yf
import datetime as dt


class VEIDiag(bt.Strategy):
    params = (
        ('atr_short', 10),
        ('atr_long', 50),
        ('atr_period', 14),
        ('ema_fast', 9),
        ('ema_slow', 21),
        ('orb_end', 5),
        ('entry_start', 12),
    )

    def __init__(self):
        self.atr   = bt.indicators.ATR(self.data, period=self.params.atr_period)
        self.atr_s = bt.indicators.ATR(self.data, period=self.params.atr_short)
        self.atr_l = bt.indicators.ATR(self.data, period=self.params.atr_long)
        self.ema_f = bt.indicators.EMA(self.data.close, period=self.params.ema_fast)
        self.ema_s = bt.indicators.EMA(self.data.close, period=self.params.ema_slow)
        self._prev_date = None
        self._bar = 0
        self._or_high = 0.
        self._or_low = 0.
        self._printed = False

    def next(self):
        if len(self.data) < 55:
            return
        today = self.data.datetime.date(0)
        if today != self._prev_date:
            self._prev_date = today
            self._bar = 0
            self._or_high = self.data.high[0]
            self._or_low = self.data.low[0]
            self._printed = False
            self._bar += 1
            return

        self._bar += 1
        b = self._bar

        if b <= self.params.orb_end:
            if self.data.high[0] > self._or_high: self._or_high = self.data.high[0]
            if self.data.low[0] < self._or_low: self._or_low = self.data.low[0]
            return

        if b == self.params.entry_start and not self._printed:
            al = self.atr_l[0]
            vei = self.atr_s[0] / al if al > 0 else 1.0
            close = self.data.close[0]
            above_or = close > self._or_high
            below_or = close < self._or_low
            ema_bull = self.ema_f[0] > self.ema_s[0]
            or_w = self._or_high - self._or_low
            atr_val = self.atr[0]

            direction = "ABOVE_OR" if above_or else ("BELOW_OR" if below_or else "IN_OR")
            ema_dir = "BULL" if ema_bull else "BEAR"

            print(f"  {today}  bar={b:2d}  VEI={vei:.3f}  "
                  f"ATRs={self.atr_s[0]:.3f}  ATRl={al:.3f}  "
                  f"OR_w={or_w:.2f}  ATR={atr_val:.3f}  "
                  f"{direction:8s}  EMA={ema_dir}  C={close:.2f}")
            self._printed = True


data = yf.download('GLD', period='59d', interval='5m', auto_adjust=True, progress=False)
if data.columns.nlevels > 1:
    data.columns = data.columns.droplevel(1)
data.index = data.index.tz_localize(None)

feed = bt.feeds.PandasData(dataname=data)
cerebro = bt.Cerebro()
cerebro.addstrategy(VEIDiag)
cerebro.adddata(feed)

print(f"\n  {'Date':12s}  {'bar':>4s}  {'VEI':>7s}  {'ATRs':>7s}  {'ATRl':>7s}  "
      f"{'OR_w':>6s}  {'ATR':>7s}  {'Direction':8s}  {'EMA':4s}  {'Close':>8s}")
print("  " + "-" * 100)
cerebro.run()
