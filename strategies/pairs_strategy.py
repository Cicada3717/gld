import backtrader as bt
import numpy as np

class PairsTradingStrategy(bt.Strategy):
    """
    A Statistical Arbitrage (Pairs Trading) Strategy based on Z-Score.
    Assumes `data0` is Asset A (e.g., KO) and `data1` is Asset B (e.g., PEP).
    """
    params = (
        ('period', 20),      # Lookback period for moving average & std dev
        ('entry_z', 2.0),    # Z-score to enter trade
        ('exit_z', 0.5),     # Z-score to exit trade
    )

    def __init__(self):
        self.asset_a = self.datas[0]
        self.asset_b = self.datas[1]

        # In a more advanced version, we'd dynamically calculate the hedge ratio
        # using OLS regression. For simplicity, we assume a 1:1 price ratio or normalized.
        # Alternatively, we calculate the spread: log(A) - log(B) or A/B
        # Let's use the price ratio A/B
        self.ratio = self.asset_a.close / self.asset_b.close
        
        # Calculate moving average and standard deviation of the ratio
        self.ratio_ma = bt.indicators.SMA(self.ratio, period=self.params.period)
        self.ratio_std = bt.indicators.StdDev(self.ratio, period=self.params.period)
        
        # Current Z-Score: (Current Ratio - Ratio MA) / Ratio StdDev
        self.zscore = (self.ratio - self.ratio_ma) / self.ratio_std
        
        # We need an indicator we can plot
        self.lines.zscore = self.zscore

    def next(self):
        # Ensure we have enough data
        if len(self) < self.params.period:
            return

        # Z-Score > Entry Z: Ratio is too high. 
        # Asset A is relatively overvalued compared to Asset B.
        # Action: Short A, Long B
        if self.zscore[0] > self.params.entry_z and not self.position:
            # We want roughly equal dollar amounts.
            # Easiest way in backtrader without advanced sizers is manual quantities.
            # Simplified sizing for demonstration: allocate half portfolio dynamically
            cash = self.broker.get_cash()
            value_per_leg = cash * 0.45
            
            qty_a = value_per_leg / self.asset_a.close[0]
            qty_b = value_per_leg / self.asset_b.close[0]
            
            self.sell(data=self.asset_a, size=qty_a)
            self.buy(data=self.asset_b, size=qty_b)

        # Z-Score < -Entry Z: Ratio is too low.
        # Asset A is relatively undervalued compared to Asset B.
        # Action: Long A, Short B
        elif self.zscore[0] < -self.params.entry_z and not self.position:
            cash = self.broker.get_cash()
            value_per_leg = cash * 0.45
            
            qty_a = value_per_leg / self.asset_a.close[0]
            qty_b = value_per_leg / self.asset_b.close[0]
            
            self.buy(data=self.asset_a, size=qty_a)
            self.sell(data=self.asset_b, size=qty_b)
            
        # Exit rules: Z-Score reverts towards mean (0)
        elif self.position:
            # If we are long A (which means short B, our overall position via backtrader isn't exactly
            # clear using just 'self.position' as it merges, but we can check the Z-score mean reversion)
            
            # If Z-score enters the exit threshold [-exit_z, exit_z], we close all positions
            if abs(self.zscore[0]) < self.params.exit_z:
                self.close(data=self.asset_a)
                self.close(data=self.asset_b)
