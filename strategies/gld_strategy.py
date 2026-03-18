import backtrader as bt

class GLDAggressive(bt.Strategy):
    """
    An aggressive fast-EMA crossover strategy designed for a short 2.5-month window
    on a highly trending single asset (GLD).
    """
    params = (
        ('fast_ema', 4),
        ('slow_ema', 10),
        ('atr_period', 5),
        ('trailing_stop_mult', 2.0),
    )

    def __init__(self):
        self.fast = bt.indicators.EMA(self.data.close, period=self.params.fast_ema)
        self.slow = bt.indicators.EMA(self.data.close, period=self.params.slow_ema)
        self.crossover = bt.indicators.CrossOver(self.fast, self.slow)
        self.atr = bt.indicators.ATR(self.data, period=self.params.atr_period)
        self.trailing_stop = 0

    def next(self):
        # We need enough data for ATR and EMA
        if len(self.data) < self.params.slow_ema:
            return

        if not self.position:
            # Entry: Fast EMA crosses above Slow EMA
            if self.crossover > 0:
                self.buy() # Sizer in backtest.py handles 90% allocation
                self.trailing_stop = self.data.close[0] - (self.atr[0] * self.params.trailing_stop_mult)
        else:
            # Update trailing stop (ratchet only upwards)
            new_stop = self.data.close[0] - (self.atr[0] * self.params.trailing_stop_mult)
            if new_stop > self.trailing_stop:
                self.trailing_stop = new_stop
            
            # Exit conditions: Trend reverses OR stop loss hit
            if self.crossover < 0 or self.data.close[0] <= self.trailing_stop:
                self.close()
                self.trailing_stop = 0
