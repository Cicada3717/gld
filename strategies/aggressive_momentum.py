import backtrader as bt

class AggressiveMomentum(bt.Strategy):
    """
    An aggressive momentum breakout strategy designed for a short 2-month window.
    Uses a very fast moving average (e.g., 5 days) to avoid wasting time warming up,
    and allocates 95% of the portfolio to the strongest trending asset.
    """
    params = (
        ('fast_ma', 5),
        ('slow_ma', 10),
    )

    def __init__(self):
        self.inds = {}
        for d in self.datas:
            self.inds[d] = {
                'fast': bt.indicators.SMA(d.close, period=self.params.fast_ma),
                'slow': bt.indicators.SMA(d.close, period=self.params.slow_ma),
                'crossover': bt.indicators.CrossOver(
                    bt.indicators.SMA(d.close, period=self.params.fast_ma),
                    bt.indicators.SMA(d.close, period=self.params.slow_ma)
                )
            }

    def next(self):
        # We only have a 40-trading-day window, every day counts.
        # Find the asset with the strongest positive spread between fast and slow MA
        best_asset = None
        best_spread = 0

        for d in self.datas:
            if len(d) >= self.params.slow_ma:
                spread = (self.inds[d]['fast'][0] - self.inds[d]['slow'][0]) / d.close[0]
                if spread > best_spread and spread > 0:
                    best_spread = spread
                    best_asset = d

        # If we have a clear winner, put our money to work
        if best_asset:
            # First, close any positions in assets that aren't the best
            for d in self.datas:
                if self.getposition(d).size > 0 and d != best_asset:
                    self.close(data=d)
            
            # Then buy the best asset if we don't already own it
            if self.getposition(best_asset).size == 0:
                print(f"[{self.data.datetime.date(0)}] Buying {best_asset._name} with spread {best_spread:.4f}")
                
                # Use 95% of portfolio to avoid margin rejection completely
                port_value = self.broker.getvalue()
                target_value = port_value * 0.95
                qty = int(target_value / best_asset.close[0])
                self.buy(data=best_asset, size=qty)
        else:
            # If no assets are trending up, close everything to protect capital
            for d in self.datas:
                if self.getposition(d).size > 0:
                    self.close(data=d)
