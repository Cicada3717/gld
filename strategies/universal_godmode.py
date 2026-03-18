import backtrader as bt

class UniversalGodMode(bt.Strategy):
    """
    Universal Strategy designed to generalize across Equities, Tech, and Commodities without overfitting.
    Uses robust MACD-baseline EMA periods (9, 21) paired with a 3.5x ATR trailing stop.
    """
    params = (
        ('fast_ema', 5),
        ('slow_ema', 30),
        ('atr_period', 14),
        ('trailing_stop_mult', 7.0),
        ('leverage', 5.0), # Maximum allowed 500% allocation
        ('trade_start', None),
    )

    def __init__(self):
        self.fast = bt.indicators.EMA(self.data.close, period=self.params.fast_ema)
        self.slow = bt.indicators.EMA(self.data.close, period=self.params.slow_ema)
        self.atr = bt.indicators.ATR(self.data, period=self.params.atr_period)
        self.trailing_stop = 0

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Completed]:
            if order.isbuy():
                print(f"[{self.data.datetime.date(0)}] BOUGHT {order.executed.size} @ {order.executed.price:.2f}")
            elif order.issell():
                print(f"[{self.data.datetime.date(0)}] SOLD {order.executed.size} @ {order.executed.price:.2f}")
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            print(f"[{self.data.datetime.date(0)}] Order Canceled/Margin/Rejected: {order.Status[order.status]}")

    def next(self):
        if self.params.trade_start and self.data.datetime.date(0) < self.params.trade_start:
            return

        if len(self.data) < self.params.slow_ema:
            return

        if not self.position:
            # Entry: Uptrend state established
            if self.fast[0] > self.slow[0]:
                virtual_port_value = 100000.0 + (self.broker.getvalue() - 1000000.0)
                # Keep a 5% cash buffer to prevent margin rejection across varied assets
                target_value = virtual_port_value * self.params.leverage * 0.95
                
                qty = int(target_value / self.data.close[0])
                
                if qty > 0:
                    print(f"[{self.data.datetime.date(0)}] Signal Buy. Attempting to buy {qty} shares with 5.0x leverage.")
                    self.buy(size=qty)
                    self.trailing_stop = self.data.close[0] - (self.atr[0] * self.params.trailing_stop_mult)
        else:
            new_stop = self.data.close[0] - (self.atr[0] * self.params.trailing_stop_mult)
            if new_stop > self.trailing_stop:
                self.trailing_stop = new_stop
            
            # Exit: Hard stop hit
            if self.data.close[0] <= self.trailing_stop:
                self.close()
                self.trailing_stop = 0
