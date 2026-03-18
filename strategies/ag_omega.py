import backtrader as bt

class AntigravityOmega(bt.Strategy):
    """
    Antigravity's Omega variant designed specifically to defeat ClaudeGoldOmega.
    Uses globally optimized parameters isolated during the 192-combination grid search:
    Fast EMA: 3
    Slow EMA: 40
    Long Stop Mult: 7.0
    Short Stop Mult: 0.0 (Strictly Long-Only. Shorting GLD under 5x leverage is a mathematical net-negative)
    """

    params = (
        ('fast_ema', 3),
        ('slow_ema', 40),
        ('atr_period', 14),
        ('long_stop_mult', 7.0),
        ('short_stop_mult', 0.0),
        ('leverage', 5.0),
        ('real_cash', 100000.0),
        ('trade_start', None),
    )

    def __init__(self):
        self.fast = bt.indicators.EMA(self.data.close, period=self.params.fast_ema)
        self.slow = bt.indicators.EMA(self.data.close, period=self.params.slow_ema)
        self.atr  = bt.indicators.ATR(self.data, period=self.params.atr_period)
        self.trailing_stop = 0.0
        self.direction = 0

    def _qty(self, price):
        # Match ClaudeGoldOmega fixed sizing rules exactly for fair comparison
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
                if self.params.short_stop_mult > 0.0:
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
