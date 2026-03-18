import warnings; warnings.filterwarnings('ignore')
import backtrader as bt, yfinance as yf, pandas as pd

CASH = 100000.0

class VWAP(bt.Indicator):
    lines = ('vwap',)
    def __init__(self):
        self._cpv = 0.
        self._cv  = 0.
        self._prev = None
    def next(self):
        today = self.data.datetime.date(0)
        if today != self._prev:
            self._cpv = 0.
            self._cv  = 0.
            self._prev = today
        tp = (self.data.high[0] + self.data.low[0] + self.data.close[0]) / 3.
        v  = max(self.data.volume[0], 1)
        self._cpv += tp * v
        self._cv  += v
        self.lines.vwap[0] = self._cpv / self._cv

class Diag(bt.Strategy):
    def __init__(self):
        self.vwap  = VWAP(self.data)
        self.ema_f = bt.indicators.EMA(self.data.close, period=9)
        self.ema_s = bt.indicators.EMA(self.data.close, period=20)
        self.rsi   = bt.indicators.RSI(self.data.close, period=14)
        self.atr   = bt.indicators.ATR(self.data, period=14)
        self.adx   = bt.indicators.AverageDirectionalMovementIndex(self.data, period=14)
        self._prev = None
        self._bar  = 0
        self._orh  = 0.
        self._orl  = 0.
        self._pc   = 0.

    def next(self):
        today = self.data.datetime.date(0)
        if today != self._prev:
            if self._prev is not None:
                self._pc = self.data.close[-1]
            self._prev = today
            self._bar  = 0
            self._orh  = self.data.high[0]
            self._orl  = self.data.low[0]
            self._bar += 1
            return
        self._bar += 1
        b = self._bar
        if b <= 5:
            if self.data.high[0] > self._orh: self._orh = self.data.high[0]
            if self.data.low[0]  < self._orl: self._orl = self.data.low[0]
            return
        if b == 12 and len(self.data) > 30:
            c    = self.data.close[0]
            gap  = (c - self._pc) / self._pc * 100 if self._pc > 0 else 0.
            vwap = self.vwap.lines.vwap[0]
            adx  = self.adx.lines.adx[0]
            rsi  = self.rsi[0]
            ema_ok   = self.ema_f[0] > self.ema_s[0]
            long_ok  = (c > vwap and c > self._orh and ema_ok and gap >= 0.1 and rsi < 65)
            short_ok = (c < vwap and c < self._orl and not ema_ok and gap <= -0.1 and rsi > 35)
            print(f"{today} gap={gap:+.3f}% adx={adx:.1f} rsi={rsi:.1f} "
                  f"c_vs_vwap={'above' if c>vwap else 'below'} "
                  f"c_vs_orH={'>' if c>self._orh else '<='} "
                  f"ema={'+' if ema_ok else '-'} "
                  f"-> LONG={long_ok} SHORT={short_ok}")

df = yf.download('GLD', period='59d', interval='5m', progress=False)
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.droplevel(1)
df.dropna(inplace=True)
cerebro = bt.Cerebro()
cerebro.broker.setcash(CASH)
cerebro.adddata(bt.feeds.PandasData(dataname=df))
cerebro.addstrategy(Diag)
cerebro.run(stdstats=False)
