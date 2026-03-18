import backtrader as bt

class CLDonchianBreakout(bt.Strategy):
    """
    Claude's GLD entry: Donchian Channel Breakout.

    Entry  — price closes above the highest close of the last `entry_period` bars
             (captures momentum surges on a trending asset like GLD).
    Exit   — price closes below the lowest close of the last `exit_period` bars
             OR RSI becomes overbought (> rsi_overbought).
    """
    params = (
        ('entry_period', 10),       # Buy on N-day channel high breakout
        ('exit_period', 5),         # Sell on M-day channel low breakdown
        ('rsi_period', 10),         # Fast RSI for short competition window
        ('rsi_overbought', 78),
        ('trade_start', None),      # Only trade on/after this date
    )

    def __init__(self):
        self.highest = bt.indicators.Highest(self.data.close, period=self.params.entry_period)
        self.lowest  = bt.indicators.Lowest(self.data.close,  period=self.params.exit_period)
        self.rsi     = bt.indicators.RSI(self.data.close,     period=self.params.rsi_period)

    def next(self):
        if self.params.trade_start and self.data.datetime.date(0) < self.params.trade_start:
            return

        if not self.position:
            # Enter when today's close equals the N-day high (breakout)
            if self.data.close[0] >= self.highest[-1]:
                self.buy()
        else:
            # Exit on M-day low breakdown or RSI overbought
            if self.data.close[0] <= self.lowest[-1] or self.rsi[0] > self.params.rsi_overbought:
                self.close()
