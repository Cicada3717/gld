import argparse
import datetime
import calendar
import backtrader as bt
import yfinance as yf
import pandas as pd

class ORBStrategy(bt.Strategy):
    params = (
        ('orb_mins', 30), # First 30 mins is Opening Range
        ('trail_mult', 2.0),
        ('leverage', 5.0),
    )

    def __init__(self):
        self.atr = bt.indicators.ATR(self.data, period=14)
        
        self.current_day = None
        self.orb_high = -1.0
        self.orb_low = float('inf')
        self.orb_active = False
        self.trailing_stop = 0.0
        self.count = 0

    def _qty(self, price):
        return int(100000.0 * self.params.leverage / price)

    def next(self):
        dt = self.data.datetime.date(0)
        time = self.data.datetime.time(0)
        price = self.data.close[0]
        high = self.data.high[0]
        low = self.data.low[0]

        # Reset parameters at start of a new day
        if self.current_day is None or dt > self.current_day:
            self.current_day = dt
            self.orb_high = high
            self.orb_low = low
            self.orb_active = False
            
            # Close any lingering positions just in case
            if self.position:
                self.close()
                self.trailing_stop = 0.0

        # Build Opening Range (9:30 to 10:00 for a 30 min ORB)
        # yfinance minute data is usually exchange local time. Assuming 09:30 EST open.
        if time < datetime.time(10, 0): # Hardcoded for 30m ORB assumption
            self.orb_high = max(self.orb_high, high)
            self.orb_low = min(self.orb_low, low)
            return
        elif time == datetime.time(10, 0):
            self.orb_active = True # ORB is locked in

        # EOD Close (Close out at 15:50)
        if time >= datetime.time(15, 50):
            if self.position:
                self.close()
                self.trailing_stop = 0.0
            self.orb_active = False
            return

        # Main Trading Logic 
        if self.orb_active and not self.position:
            # We only take ONE trade per day. If broke high, go long.
            if price > self.orb_high:
                qty = self._qty(price)
                if qty > 0:
                    self.buy(size=qty)
                    self.trailing_stop = price - self.atr[0] * self.params.trail_mult
                    self.orb_active = False # prevent re-entry today
                    
            elif price < self.orb_low:
                # Optionally short
                qty = self._qty(price)
                if qty > 0:
                    self.sell(size=qty)
                    self.trailing_stop = price + self.atr[0] * self.params.trail_mult
                    self.orb_active = False # prevent re-entry today

        # Trailing stop management
        if self.position:
            if self.position.size > 0: # Long
                new_stop = price - self.atr[0] * self.params.trail_mult
                if new_stop > self.trailing_stop:
                    self.trailing_stop = new_stop
                if price <= self.trailing_stop:
                    self.close()
                    self.trailing_stop = 0.0
            elif self.position.size < 0: # Short
                new_stop = price + self.atr[0] * self.params.trail_mult
                if new_stop < self.trailing_stop:
                    self.trailing_stop = new_stop
                if price >= self.trailing_stop:
                    self.close()
                    self.trailing_stop = 0.0


def run_orb_backtest(ticker="GLD"):
    print(f"Downloading 60d of 5-minute Intraday data for ORB Backtest on {ticker}...")
    df = yf.download(ticker, period='60d', interval="5m", progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
        
    if df.empty:
        print("Error: No intraday data fetched.")
        return

    # Convert UTC to US/Eastern naive time for accurate Backtrader hours
    df.index = df.index.tz_convert('America/New_York').tz_localize(None)

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(1_000_000.0)
    cerebro.broker.setcommission(commission=0.005)
    cerebro.broker.set_shortcash(False)
    
    data = bt.feeds.PandasData(dataname=df, timeframe=bt.TimeFrame.Minutes)
    cerebro.adddata(data)
    
    cerebro.addstrategy(ORBStrategy)
    
    print("Starting ORB Intraday Backtest...")
    cerebro.run()
    
    raw = cerebro.broker.getvalue()
    final = raw - 900000.0
    roi = ((final - 100000.0) / 100000.0) * 100
    
    print(f"Final ORB Portfolio Value: ${final:.2f}")
    print(f"Total ORB ROI: {roi:.2f}%")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--ticker', type=str, default='GLD')
    args = parser.parse_args()
    run_orb_backtest(args.ticker)
