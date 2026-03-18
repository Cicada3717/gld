import backtrader as bt
import numpy as np
import datetime

class MasterProtocol(bt.Strategy):
    """
    Master Protocol: A collaborative strategy between Claude and Antigravity.
    
    Core Engine (Claude):
        - Monthly rotation into the top N assets based on 6-month Rate-of-Change (momentum).
        - Absolute momentum filter (cash if momentum is negative).
        
    Risk Engine (Antigravity):
        - Average True Range (ATR) based trailing stop-loss on active positions to 
          cut down the 20% drawdown observed in the bare momentum strategy.
        - Volatility scaling: We do not allocate blindly; we inversely weight based 
          on asset volatility.
    """

    params = (
        ('top_n', 2),                # Hold top-N assets at once
        ('momentum_period', 126),    # 6-month lookback (~126 trading days)
        ('rebalance_frequency', 21), # Rebalance every ~21 bars (monthly)
        ('cash_buffer', 0.05),       # Keep 5% cash for safety/commissions
        ('trade_start', None),       # datetime.date — ignore bars before this
        ('atr_period', 14),          # Lookback for volatility sizing
        ('trailing_stop_atr_mult', 3.0), # Trailing stop distance
    )

    def __init__(self):
        self.rebalance_counter = 0

        # Indicators for each data feed
        self.inds = {}
        for d in self.datas:
            self.inds[d._name] = {
                'momentum': bt.indicators.ROC(d.close, period=self.params.momentum_period),
                'atr': bt.indicators.ATR(d, period=self.params.atr_period),
                'highest': bt.indicators.Highest(d.high, period=self.params.rebalance_frequency)
            }
            
        # Track our dynamic trailing stops per asset
        self.trailing_stops = {}

    def next(self):
        self.rebalance_counter += 1

        # Respect competition start date (warmup guard)
        if self.params.trade_start:
            current_date = self.datas[0].datetime.date(0)
            if current_date < self.params.trade_start:
                return

        # --- Antigravity Risk Engine: Trailing Stop Loss Management ---
        for d in self.datas:
            pos = self.getposition(d)
            if pos.size > 0:
                # Update trailing stop if price goes up
                current_stop = self.trailing_stops.get(d._name, 0)
                new_stop = d.close[0] - (self.inds[d._name]['atr'][0] * self.params.trailing_stop_atr_mult)
                
                # Only ratchet the stop upwards
                if new_stop > current_stop:
                    self.trailing_stops[d._name] = new_stop
                    
                # Execute Stop Loss
                if d.close[0] <= self.trailing_stops[d._name]:
                    print(f"[{d.datetime.date(0)}] STOP LOSS Hit for {d._name}. Price: {d.close[0]:.2f}, Stop: {self.trailing_stops[d._name]:.2f}")
                    self.close(data=d)
                    self.trailing_stops[d._name] = 0 # Reset stop

        # --- Claude Core Engine: Scheduled Rebalancing ---
        if self.rebalance_counter % self.params.rebalance_frequency != 0:
            return

        # Rank assets by momentum; require positive momentum
        rankings = []
        for d in self.datas:
            mom = self.inds[d._name]['momentum'][0]
            if not np.isnan(mom) and mom > 0:
                rankings.append((d, mom))

        rankings.sort(key=lambda x: x[1], reverse=True)
        target_assets = [d for d, _ in rankings[: self.params.top_n]]

        # Exit positions NOT in the target set
        for d in self.datas:
            pos = self.getposition(d)
            if pos.size > 0 and d not in target_assets:
                print(f"[{d.datetime.date(0)}] Rebalance: Closing {d._name} (Lost Momentum)")
                self.close(data=d)
                self.trailing_stops[d._name] = 0

        # If nothing qualifies, stay in cash
        if not target_assets:
            return

        # Inverse Volatility Sizing (Antigravity Overlay)
        # Calculate inverse ATRs to assign smaller weights to highly volatile assets
        inv_atrs = []
        for d in target_assets:
            atr = self.inds[d._name]['atr'][0]
            # Avoid divide by zero
            inv_atrs.append(1.0 / atr if atr > 0 else 1.0)
            
        total_inv_atr = sum(inv_atrs)

        portfolio_value = self.broker.getvalue()
        usable_capital = portfolio_value * (1.0 - self.params.cash_buffer)

        for i, d in enumerate(target_assets):
            # Weight based on inverse volatility instead of naive equal weight
            weight = inv_atrs[i] / total_inv_atr
            target_value = usable_capital * weight
            
            current_value = self.getposition(d).size * d.close[0]
            diff = target_value - current_value

            if diff > 50:
                self.buy(data=d, size=diff / d.close[0])
                # Initialize trailing stop on new buy
                if self.trailing_stops.get(d._name, 0) == 0:
                    self.trailing_stops[d._name] = d.close[0] - (self.inds[d._name]['atr'][0] * self.params.trailing_stop_atr_mult)
            elif diff < -50:
                self.sell(data=d, size=abs(diff) / d.close[0])
