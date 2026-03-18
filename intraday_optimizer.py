import itertools
import pandas as pd
import yfinance as yf
import backtrader as bt
import datetime

class IntradayOptimizerStrategy(bt.Strategy):
    params = (
        ('fast_ema', 5),
        ('slow_ema', 20),
        ('atr_period', 14),
        ('trail_mult', 3.0),
        ('leverage', 5.0),
        ('eod_close', True)
    )

    def __init__(self):
        self.fast = bt.indicators.EMA(self.data.close, period=self.params.fast_ema)
        self.slow = bt.indicators.EMA(self.data.close, period=self.params.slow_ema)
        self.atr  = bt.indicators.ATR(self.data, period=self.params.atr_period)
        self.trailing_stop = 0.0

    def _qty(self, price):
        return int(100000.0 * self.params.leverage / price)

    def next(self):
        dt = self.data.datetime.time(0)
        
        # Liquidate positions right before standard US market close (15:50)
        if self.params.eod_close and dt >= datetime.time(15, 50):
            if self.position:
                self.close()
                self.trailing_stop = 0.0
            return

        if len(self.data) < self.params.slow_ema:
            return

        price = self.data.close[0]
        uptrend = self.fast[0] > self.slow[0]

        if not self.position:
            # Look for entries only between 09:30 and 15:00
            if uptrend and datetime.time(9, 30) <= dt < datetime.time(15, 0):
                qty = self._qty(price)
                if qty > 0:
                    self.buy(size=qty)
                    self.trailing_stop = price - self.atr[0] * self.params.trail_mult
        else:
            new_stop = price - self.atr[0] * self.params.trail_mult
            if new_stop > self.trailing_stop:
                self.trailing_stop = new_stop
            if price <= self.trailing_stop:
                self.close()
                self.trailing_stop = 0.0


def run_optimizer():
    tickers = ['QQQ', 'TSLA']
    print(f"Downloading 60d of 5-minute data for {tickers}...")
    
    data_dict = {}
    for ticker in tickers:
        df = yf.download(ticker, period='60d', interval='5m', progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        if df.empty:
            continue
        df.index = df.index.tz_convert('America/New_York').tz_localize(None)
        data_dict[ticker] = df

    fast_emas = [5, 9, 21]
    slow_emas = [40, 60, 100]
    trail_mults = [2.0, 3.0, 5.0]

    combinations = list(itertools.product(fast_emas, slow_emas, trail_mults))
    print(f"Testing {len(combinations)} intraday grid setups across {len(tickers)} tickers...")

    best_roi = -1000
    best_params = None

    for fast, slow, trail in combinations:
        if fast >= slow:
            continue
            
        total_roi = 0.0
        for ticker in tickers:
            cerebro = bt.Cerebro()
            cerebro.broker.setcash(1000000.0) # padding for 5x leverage
            cerebro.broker.setcommission(commission=0.005)
            cerebro.broker.set_shortcash(False)
            cerebro.broker.set_coc(True)
            
            data = bt.feeds.PandasData(dataname=data_dict[ticker], timeframe=bt.TimeFrame.Minutes)
            cerebro.adddata(data)
            
            cerebro.addstrategy(IntradayOptimizerStrategy, fast_ema=fast, slow_ema=slow, trail_mult=trail)
            
            try:
                cerebro.run()
                raw = cerebro.broker.getvalue()
                final_val = raw - 900000.0
                roi = ((final_val - 100000.0) / 100000.0) * 100
                total_roi += roi
            except Exception as e:
                pass
                
        if total_roi > best_roi:
            best_roi = total_roi
            best_params = (fast, slow, trail)
            print(f"New Best Multiple-Asset Intraday ROI (Total): {total_roi:.2f}% | Fast:{fast} Slow:{slow} ATR:{trail}")

    print(f"\nOPTIMAL INTRADAY PARAMS: {best_params} -> {best_roi:.2f}%")

if __name__ == '__main__':
    run_optimizer()
