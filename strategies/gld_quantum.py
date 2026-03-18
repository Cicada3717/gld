import backtrader as bt

class GLDQuantum(bt.Strategy):
    """
    Bidirectional Long/Short Leveraged Strategy.
    Enters Long on EMA5 > EMA30.
    Enters Short on EMA5 < EMA30.
    5.0x Leverage applied to both directions.
    """
    params = (
        ('fast_ema', 5),
        ('slow_ema', 30),
        ('atr_period', 14),
        ('trailing_stop_mult', 5.0),
        ('leverage', 5.0),
        ('trade_start', None),
    )

    def __init__(self):
        self.fast = bt.indicators.EMA(self.data.close, period=self.params.fast_ema)
        self.slow = bt.indicators.EMA(self.data.close, period=self.params.slow_ema)
        self.atr = bt.indicators.ATR(self.data, period=self.params.atr_period)
        self.trailing_stop = 0
        self.entry_type = None  # 1 for Long, -1 for Short

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Completed]:
            action = "BOUGHT" if order.isbuy() else "SOLD"
            print(f"[{self.data.datetime.date(0)}] {action} {order.executed.size} @ {order.executed.price:.2f}")

    def next(self):
        if self.params.trade_start and self.data.datetime.date(0) < self.params.trade_start:
            return

        if len(self.data) < self.params.slow_ema:
            return

        virtual_port_value = 100000.0 + (self.broker.getvalue() - 1000000.0)
        target_value = virtual_port_value * self.params.leverage
        qty = int(target_value / self.data.close[0])

        if not self.position:
            if self.fast[0] > self.slow[0]:
                self.buy(size=qty)
                self.trailing_stop = self.data.close[0] - (self.atr[0] * self.params.trailing_stop_mult)
                self.entry_type = 1
            elif self.fast[0] < self.slow[0]:
                self.sell(size=qty)
                self.trailing_stop = self.data.close[0] + (self.atr[0] * self.params.trailing_stop_mult)
                self.entry_type = -1
        else:
            if self.entry_type == 1:
                # Long Trailing Stop
                new_stop = self.data.close[0] - (self.atr[0] * self.params.trailing_stop_mult)
                if new_stop > self.trailing_stop:
                    self.trailing_stop = new_stop
                
                if self.data.close[0] <= self.trailing_stop or self.fast[0] < self.slow[0]:
                    self.close()
                    self.trailing_stop = 0
                    self.entry_type = None

            elif self.entry_type == -1:
                # Short Trailing Stop
                new_stop = self.data.close[0] + (self.atr[0] * self.params.trailing_stop_mult)
                if new_stop < self.trailing_stop:
                    self.trailing_stop = new_stop
                
                if self.data.close[0] >= self.trailing_stop or self.fast[0] > self.slow[0]:
                    self.close()
                    self.trailing_stop = 0
                    self.entry_type = None
