import backtrader as bt
import yfinance as yf
import pandas as pd
import datetime
import calendar
import itertools

class BidirGodMode(bt.Strategy):
    params = (
        ('fast_ema', 5),
        ('slow_ema', 30),
        ('atr_period', 14),
        ('long_stop_mult', 5.0),
        ('short_stop_mult', 3.0),
        ('leverage', 5.0),
        ('trade_start', None),
        ('real_cash', 100000.0)
    )

    def __init__(self):
        self.fast = bt.indicators.EMA(self.data.close, period=self.params.fast_ema)
        self.slow = bt.indicators.EMA(self.data.close, period=self.params.slow_ema)
        self.atr  = bt.indicators.ATR(self.data, period=self.params.atr_period)
        self.trailing_stop = 0.0
        self.direction = 0

    def _qty(self, price):
        return int(self.params.real_cash * self.params.leverage / price)

    def next(self):
        if self.params.trade_start and self.data.datetime.date(0) < self.params.trade_start:
            return
        if len(self.data) < self.params.slow_ema:
            return

        price   = self.data.close[0]
        atr     = self.atr[0]
        uptrend = self.fast[0] > self.slow[0]

        if not self.position:
            qty = self._qty(price)
            if uptrend:
                self.buy(size=qty)
                self.trailing_stop = price - atr * self.params.long_stop_mult
                self.direction = 1
            else:
                if self.params.short_stop_mult > 0:
                    self.sell(size=qty)
                    self.trailing_stop = price + atr * self.params.short_stop_mult
                    self.direction = -1

        elif self.direction == 1:
            new_stop = price - atr * self.params.long_stop_mult
            if new_stop > self.trailing_stop:
                self.trailing_stop = new_stop
            if price <= self.trailing_stop:
                self.close()
                self.trailing_stop = 0.0
                self.direction = 0

        elif self.direction == -1:
            new_stop = price + atr * self.params.short_stop_mult
            if new_stop < self.trailing_stop:
                self.trailing_stop = new_stop
            if price >= self.trailing_stop:
                self.close()
                self.trailing_stop = 0.0
                self.direction = 0

def run_optimizer():
    print("Downloading GLD data...")
    start_date = '2025-03-01'
    end_date = '2026-03-01'
    warmup_start = (pd.Timestamp(start_date) - pd.DateOffset(months=6)).strftime('%Y-%m-%d')
    df = yf.download('GLD', start=warmup_start, end=end_date, interval='1d', progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)

    months = []
    y, m = 2025, 3
    for _ in range(12):
        last_day = calendar.monthrange(y, m)[1]
        months.append((
            f'{y}-{m:02d}-01',
            f'{y}-{m:02d}-{last_day}',
            f'{y}-{m:02d}'
        ))
        m += 1
        if m > 12:
            m = 1
            y += 1
    trade_start_dates = [datetime.date.fromisoformat(s) for s, _, _ in months]

    # Grid search
    fast_emas = [3, 4, 5, 8]
    slow_emas = [21, 30, 40]
    long_stops = [4.0, 5.0, 6.0, 7.0]
    short_stops = [0.0, 2.0, 3.0, 4.0] # 0 = Long only

    combinations = list(itertools.product(fast_emas, slow_emas, long_stops, short_stops))
    print(f"Testing {len(combinations)} combinations strictly compliant with monthly_arena rules...")

    best_roi = -1000
    best_params = None

    for fast, slow, ls, ss in combinations:
        sum_roi = 0.0
        for (start, end, _), ts in zip(months, trade_start_dates):
            cerebro = bt.Cerebro()
            cerebro.broker.setcash(1000000.0) # 1M padding
            cerebro.broker.setcommission(commission=0.005)
            cerebro.broker.set_shortcash(False)
            cerebro.broker.set_coc(True)
            
            # Slice the df just like monthly arena shared approach
            month_mask = (df.index >= warmup_start) & (df.index <= end)
            month_df = df.loc[month_mask].copy()
            if month_df.empty:
                continue
            
            cerebro.adddata(bt.feeds.PandasData(dataname=month_df))
            cerebro.addstrategy(BidirGodMode, fast_ema=fast, slow_ema=slow, long_stop_mult=ls, short_stop_mult=ss, trade_start=ts)
            
            try:
                cerebro.run()
                raw = cerebro.broker.getvalue()
                final = raw - 900000.0
                sum_roi += ((final - 100000.0) / 100000.0) * 100
            except:
                pass
        
        if sum_roi > best_roi:
            best_roi = sum_roi
            best_params = (fast, slow, ls, ss)
            print(f"New Best! ROI: {sum_roi:.2f}% | F:{fast} S:{slow} LS:{ls} SS:{ss}")

    print(f"OPTIMAL BidirGodMode: {best_params} -> {best_roi:.2f}%")

if __name__ == '__main__':
    run_optimizer()
