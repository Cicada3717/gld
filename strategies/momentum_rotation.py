import backtrader as bt
import numpy as np
import datetime


class MomentumRotationStrategy(bt.Strategy):
    """
    Global Asset Momentum Rotation Strategy — Claude's Arena Entry.

    Logic:
        - Every ~21 trading days (monthly), rank all assets by 6-month
          Rate-of-Change (ROC).
        - Rotate into the top N assets that also have *positive* momentum
          (absolute momentum filter — avoids holding assets in freefall).
        - Equal-weight the selected assets using ~98% of portfolio value.
        - If no assets have positive momentum, hold cash entirely.
        - Enforces a `trade_start` date so warmup data can be pre-loaded
          without distorting the competition period's P&L.

    Why it should win:
        2022 — XLE (energy) surged ~+60% while equities/bonds crashed.
                Momentum picks it up within the first rotation cycle.
        2023 — Tech (QQQ/XLK) surged ~+55%. Strategy rotates in as energy
                momentum fades and tech momentum reaccelerates.
    """

    params = (
        ('top_n', 2),                # Hold top-N assets at once
        ('momentum_period', 126),    # 6-month lookback (~126 trading days)
        ('rebalance_frequency', 21), # Rebalance every ~21 bars (monthly)
        ('cash_buffer', 0.02),       # Keep 2% cash to cover commissions
        ('trade_start', None),       # datetime.date — ignore bars before this
    )

    def __init__(self):
        self.rebalance_counter = 0

        # Rate-of-Change indicator for each data feed
        self.momentum = {}
        for d in self.datas:
            self.momentum[d._name] = bt.indicators.ROC(
                d.close, period=self.params.momentum_period
            )

    def next(self):
        self.rebalance_counter += 1

        # ── Respect competition start date (warmup guard) ──────────────────
        if self.params.trade_start:
            current_date = self.datas[0].datetime.date(0)
            if current_date < self.params.trade_start:
                return

        # ── Only rebalance on schedule ──────────────────────────────────────
        if self.rebalance_counter % self.params.rebalance_frequency != 0:
            return

        # ── Rank assets by momentum; require positive momentum ─────────────
        rankings = []
        for d in self.datas:
            mom = self.momentum[d._name][0]
            if not np.isnan(mom) and mom > 0:
                rankings.append((d, mom))

        rankings.sort(key=lambda x: x[1], reverse=True)
        target_assets = [d for d, _ in rankings[: self.params.top_n]]

        # ── Exit positions NOT in the target set ────────────────────────────
        for d in self.datas:
            pos = self.getposition(d)
            if pos.size > 0 and d not in target_assets:
                self.close(data=d)

        # ── If nothing qualifies, stay 100% cash ───────────────────────────
        if not target_assets:
            return

        # ── Equal-weight the target assets ──────────────────────────────────
        alloc = (1.0 - self.params.cash_buffer) / len(target_assets)
        portfolio_value = self.broker.getvalue()

        for d in target_assets:
            target_value = portfolio_value * alloc
            current_value = self.getposition(d).size * d.close[0]
            diff = target_value - current_value

            if diff > 50:                          # Add to / open position
                self.buy(data=d, size=diff / d.close[0])
            elif diff < -50:                       # Trim position
                self.sell(data=d, size=abs(diff) / d.close[0])
