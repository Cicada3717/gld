import backtrader as bt


class ClaudeGoldOmega(bt.Strategy):
    """
    Claude's Bidirectional Regime Rider (Omega v3.0)

    What went wrong in v1/v2 and how this fixes it:

    v1 issue: ATR*4.5 stop on shorts was too WIDE. In Aug 2025, short held all the way
              through GLD's recovery, bleeding -15%. Should have exited sooner.

    v2 issue: EMA trend-flip exit caused immediate WHIPSAW. EMA5 can flip on a single
              day's recovery. Entering short on Jul 1, exiting on Jul 2 (1-day bounce),
              re-entering LONG → lost more money.

    v3 solution:
      LONGS:  ATR*5.0 stop (same as Antigravity) — ride the trend far.
      SHORTS: ATR*3.0 stop (tight) — exit quickly if GLD bounces. No trend-flip exit.
              Tighter short stop means faster exit in recoveries (Aug 2025: exits earlier
              → less loss, then re-enters long for the rest of the up move).

    Design:
    - EMA5 > EMA30 → LONG  with 5x leverage, ATR*5.0 trailing stop
    - EMA5 < EMA30 → SHORT with 5x leverage, ATR*3.0 trailing stop
    - After any exit: re-assess EMA regime and re-enter on next bar
    - Fixed sizing based on $100K (not dynamic — dynamic compounds losses in bad months)
    """

    params = (
        ('fast_ema', 5),
        ('slow_ema', 30),
        ('atr_period', 14),
        ('long_stop_mult', 5.0),    # Match AG's wide stop — ride longs fully
        ('short_stop_mult', 3.0),   # Tight short stop — exit fast on recovery
        ('leverage', 5.0),
        ('real_cash', 100000.0),
        ('trade_start', None),
    )

    def __init__(self):
        self.fast = bt.indicators.EMA(self.data.close, period=self.params.fast_ema)
        self.slow = bt.indicators.EMA(self.data.close, period=self.params.slow_ema)
        self.atr  = bt.indicators.ATR(self.data, period=self.params.atr_period)
        self.trailing_stop = 0.0
        self.direction = 0   # 1 = long, -1 = short, 0 = flat

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            action = 'BUY ' if order.isbuy() else 'SELL'
            print(f"[{self.data.datetime.date(0)}] {action} {order.executed.size} @ {order.executed.price:.2f}")
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            print(f"[{self.data.datetime.date(0)}] Order {order.Status[order.status]}")

    def _qty(self, price):
        """Fixed sizing: always use real_cash * leverage regardless of prior P&L.
        No 0.90 haircut — match AG's full leverage sizing."""
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
                print(f"[{self.data.datetime.date(0)}] ENTER LONG  {qty} @ {price:.2f} | stop={self.trailing_stop:.2f}")
            else:
                self.sell(size=qty)
                self.trailing_stop = price + atr * self.params.short_stop_mult
                self.direction = -1
                print(f"[{self.data.datetime.date(0)}] ENTER SHORT {qty} @ {price:.2f} | stop={self.trailing_stop:.2f}")

        elif self.direction == 1:
            # Long: trail stop upward, exit only on ATR stop (no trend-flip exit)
            new_stop = price - atr * self.params.long_stop_mult
            if new_stop > self.trailing_stop:
                self.trailing_stop = new_stop
            if price <= self.trailing_stop:
                self.close()
                self.trailing_stop = 0.0
                self.direction = 0
                print(f"[{self.data.datetime.date(0)}] EXIT LONG  (stop) @ {price:.2f}")

        elif self.direction == -1:
            # Short: trail stop downward, exit only on ATR stop (tight: *3.0)
            # No trend-flip exit — avoids whipsaw from brief EMA5 reversals
            new_stop = price + atr * self.params.short_stop_mult
            if new_stop < self.trailing_stop:
                self.trailing_stop = new_stop
            if price >= self.trailing_stop:
                self.close()
                self.trailing_stop = 0.0
                self.direction = 0
                print(f"[{self.data.datetime.date(0)}] EXIT SHORT (stop) @ {price:.2f}")
