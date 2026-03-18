import itertools
import pandas as pd
import yfinance as yf
import backtrader as bt
import datetime

class IntradayVWAP(bt.Indicator):
    lines = ('vwap',)
    plotinfo = dict(subplot=False)

    def __init__(self):
        self.cumvol = 0.0
        self.cumtypvol = 0.0
        self.current_day = None

    def next(self):
        dt = self.data.datetime.date(0)
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


class VWAPOptimStrategy(bt.Strategy):
    params = (
        ('rsi_period', 9),
        ('rsi_overbought', 80),
        ('rsi_oversold', 20),
        ('vwap_dist_pct', 0.005), 
        ('stop_loss_pct', 0.015),
        ('leverage', 5.0),
    )

    def __init__(self):
        self.vwap = IntradayVWAP(self.data)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.params.rsi_period)
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

        if dt >= datetime.time(15, 50):
            if self.position:
                self.close()
            return
            
        if dt < datetime.time(9, 45) or dt > datetime.time(15, 30):
            return

        dist_from_vwap = (price - v) / v

        if not self.position:
            if dist_from_vwap > self.params.vwap_dist_pct and r > self.params.rsi_overbought:
                qty = self._qty(price)
                if qty > 0:
                    self.sell(size=qty)
                    self.entry_price = price

            elif dist_from_vwap < -self.params.vwap_dist_pct and r < self.params.rsi_oversold:
                qty = self._qty(price)
                if qty > 0:
                    self.buy(size=qty)
                    self.entry_price = price
                    
        else:
            if self.position.size > 0: 
                if price <= self.entry_price * (1.0 - self.params.stop_loss_pct):
                    self.close()
                elif price >= v:
                    self.close()
            elif self.position.size < 0: 
                if price >= self.entry_price * (1.0 + self.params.stop_loss_pct):
                    self.close()
                elif price <= v:
                    self.close()


def run_optimizer():
    tickers = ['GLD']
    print(f"Downloading 60d of 5-minute data for VWAP optimization on {tickers}...")
    
    data_dict = {}
    for ticker in tickers:
        df = yf.download(ticker, period='60d', interval='5m', progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        if df.empty:
            continue
        df.index = df.index.tz_convert('America/New_York').tz_localize(None)
        data_dict[ticker] = df

    rsi_periods = [9, 14]
    rsi_thresholds = [(75, 25), (80, 20), (85, 15)]
    vwap_dists = [0.003, 0.005, 0.008, 0.012]
    stop_losses = [0.01, 0.015, 0.02, 0.05]

    combinations = list(itertools.product(rsi_periods, rsi_thresholds, vwap_dists, stop_losses))
    print(f"Testing {len(combinations)} intraday mean reversion parameter matrices...")

    best_roi = -1000
    best_params = None

    for rsi_per, rsi_thresh, vwap_dist, sl in combinations:
        ob, os = rsi_thresh
        total_roi = 0.0
        
        for ticker in tickers:
            cerebro = bt.Cerebro()
            cerebro.broker.setcash(1000000.0)
            cerebro.broker.setcommission(commission=0.005)
            cerebro.broker.set_shortcash(False)
            cerebro.broker.set_coc(True)
            
            data = bt.feeds.PandasData(dataname=data_dict[ticker], timeframe=bt.TimeFrame.Minutes)
            cerebro.adddata(data)
            
            cerebro.addstrategy(
                VWAPOptimStrategy, 
                rsi_period=rsi_per, 
                rsi_overbought=ob, 
                rsi_oversold=os, 
                vwap_dist_pct=vwap_dist, 
                stop_loss_pct=sl
            )
            
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
            best_params = (rsi_per, ob, os, vwap_dist, sl)
            print(f"New Best Total Intraday ROI: {total_roi:.2f}% | Period:{rsi_per} OB/OS:{ob}/{os} Dist:{vwap_dist} SL:{sl}")

    print(f"\nOPTIMAL MEAN REVERSION PARAMS: {best_params} -> {best_roi:.2f}%")

if __name__ == '__main__':
    run_optimizer()
