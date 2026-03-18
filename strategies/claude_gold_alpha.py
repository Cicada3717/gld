import backtrader as bt


class ClaudeGoldAlpha(bt.Strategy):
    """
    Claude's GLD strategy: Leveraged Trend Rider.

    Enter when uptrend confirmed (EMA5 > EMA30).
    Wide ATR trailing stop to ride the full trend.
    Leverage amplifies the single-trade approach.
    Minimal trades = minimal commission drag even with leverage.
    """
    params = (
        ('fast_ema', 5),
        ('slow_ema', 30),
        ('atr_period', 14),
        ('trailing_stop_mult', 4.0),
        ('leverage', 1.0),
        ('real_cash', 100000.0),
        ('trade_start', None),
    )

    def __init__(self):
        self.fast = bt.indicators.EMA(self.data.close, period=self.params.fast_ema)
        self.slow = bt.indicators.EMA(self.data.close, period=self.params.slow_ema)
        self.atr = bt.indicators.ATR(self.data, period=self.params.atr_period)
        self.trailing_stop = 0

    def next(self):
        if self.params.trade_start and self.data.datetime.date(0) < self.params.trade_start:
            return

        if len(self.data) < self.params.slow_ema:
            return

        if not self.position:
            if self.fast[0] > self.slow[0]:
                if self.params.leverage > 1.0:
                    # Manual sizing for leveraged trades
                    target_value = self.params.real_cash * self.params.leverage * 0.90
                    qty = int(target_value / self.data.close[0])
                    self.buy(size=qty)
                else:
                    self.buy()  # Default sizer handles it
                self.trailing_stop = self.data.close[0] - (self.atr[0] * self.params.trailing_stop_mult)
        else:
            new_stop = self.data.close[0] - (self.atr[0] * self.params.trailing_stop_mult)
            if new_stop > self.trailing_stop:
                self.trailing_stop = new_stop

            if self.data.close[0] <= self.trailing_stop:
                self.close()
                self.trailing_stop = 0
