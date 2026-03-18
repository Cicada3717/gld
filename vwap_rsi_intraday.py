import argparse
import datetime
import pandas as pd
import yfinance as yf
import backtrader as bt

class IntradayVWAP(bt.Indicator):
    lines = ('vwap',)
    plotinfo = dict(subplot=False)

    def __init__(self):
        self.cumvol = 0.0
        self.cumtypvol = 0.0
        self.current_day = None

    def next(self):
        dt = self.data.datetime.date(0)
        
        # Reset at the start of a new trading day
        if self.current_day is None or dt > self.current_day:
            self.current_day = dt
            self.cumvol = 0.0
            self.cumtypvol = 0.0

        typ_price = (self.data.high[0] + self.data.low[0] + self.data.close[0]) / 3.0
        vol = self.data.volume[0]

        self.cumvol += vol
        self.cumtypvol += typ_price * vol

        if self.cumvol > 0:
            self.lines.vwap[0] = self.cumtypvol / self.cumvol
        else:
            self.lines.vwap[0] = typ_price

class VWAPRSIStrategy(bt.Strategy):
    """
    Advanced Intraday Mean Reversion / Scalp Strategy
    Logic:
    - VWAP gives us the baseline fair value for the day.
    - RSI measures extreme extensions (overbought/oversold).
    - Long: Price dips BELOW VWAP significantly, but RSI is heavily OVERSOLD (< 30) and turning up.
    - Short: Price spikes ABOVE VWAP significantly, but RSI is heavily OVERBOUGHT (> 70) and turning down.
    - Exit: Reversion back to VWAP, or End-of-Day liquidation.
    """
    params = (
        ('rsi_period', 14),
        ('rsi_overbought', 75),
        ('rsi_oversold', 25),
        ('vwap_dist_pct', 0.012), # Require at least 1.2% distance from VWAP to fade
        ('stop_loss_pct', 0.015), # 1.5% hard stop loss
        ('leverage', 5.0),
    )

    def __init__(self):
        self.vwap = IntradayVWAP(self.data)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.params.rsi_period)
        
        # Tracking states
        self.entry_price = 0.0

    def _qty(self, price):
        return int(100000.0 * self.params.leverage / price)

    def next(self):
        dt = self.data.datetime.time(0)
        price = self.data.close[0]
        v = self.vwap[0]
        r = self.rsi[0]

        if len(self.data) < self.params.rsi_period:
            return

        # 1. EOD Liquidation (15:50 US Eastern)
        if dt >= datetime.time(15, 50):
            if self.position:
                self.close()
            return
            
        # 2. Prevent taking new trades too late in the day or right at open
        if dt < datetime.time(9, 45) or dt > datetime.time(15, 30):
            return

        # Distance from VWAP calculation
        dist_from_vwap = (price - v) / v

        if not self.position:
            # SHORT LOGIC (Price is too high above VWAP, RSI Overbought)
            if dist_from_vwap > self.params.vwap_dist_pct and r > self.params.rsi_overbought:
                qty = self._qty(price)
                if qty > 0:
                    self.sell(size=qty)
                    self.entry_price = price

            # LONG LOGIC (Price is deeply below VWAP, RSI Oversold)
            elif dist_from_vwap < -self.params.vwap_dist_pct and r < self.params.rsi_oversold:
                qty = self._qty(price)
                if qty > 0:
                    self.buy(size=qty)
                    self.entry_price = price
                    
        else:
            # 3. Position Management (Take Profit at VWAP or Hard Stop)
            if self.position.size > 0: # Long
                # Stop Loss
                if price <= self.entry_price * (1.0 - self.params.stop_loss_pct):
                    self.close()
                # Take Profit (Mean reverted to VWAP)
                elif price >= v:
                    self.close()
                    
            elif self.position.size < 0: # Short
                # Stop Loss
                if price >= self.entry_price * (1.0 + self.params.stop_loss_pct):
                    self.close()
                # Take Profit (Mean reverted to VWAP)
                elif price <= v:
                    self.close()


def run_vwap_backtest(ticker="QQQ"):
    print(f"Downloading 60d of 5-minute Intraday data for VWAP+RSI Backtest on {ticker}...")
    df = yf.download(ticker, period='60d', interval="5m", progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
        
    if df.empty:
        print("Error: No intraday data fetched.")
        return

    # Convert to standard naive eastern time for strict backtrader matching
    df.index = df.index.tz_convert('America/New_York').tz_localize(None)

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(1_000_000.0)
    cerebro.broker.setcommission(commission=0.005)
    cerebro.broker.set_shortcash(False)
    
    data = bt.feeds.PandasData(dataname=df, timeframe=bt.TimeFrame.Minutes)
    cerebro.adddata(data)
    
    cerebro.addstrategy(VWAPRSIStrategy)
    
    print(f"Starting Mean Reversion Intraday Backtest for {ticker}...")
    cerebro.run()
    
    raw = cerebro.broker.getvalue()
    final = raw - 900000.0
    roi = ((final - 100000.0) / 100000.0) * 100
    
    print(f"Final Intraday VWAP Portfolio Value: ${final:.2f}")
    print(f"Total Intraday VWAP ROI: {roi:.2f}%")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--ticker', type=str, default='GLD')
    args = parser.parse_args()
    run_vwap_backtest(args.ticker)
