"""
ClaudeAPEX-Swing — Multi-Day Trend Following on 1h bars
========================================================

WHY INTRADAY FAILS ON 1H:
  0.1% commission × 5x leverage = ~$700 per round trip.
  GLD intraday moves average $1-3. Commission eats the edge.

SOLUTION: Hold for MULTIPLE DAYS. Use 1h bars for precise entry timing,
but hold until the trend exhausts — capturing $5-20 moves instead of $1-3.
This reduces commission drag to <10% of gross P&L per trade.

Strategy:
  TREND: EMA(21) vs EMA(63) on 1h (same as before)
    LONG when EMA(21) > EMA(63), SHORT when EMA(21) < EMA(63)

  VEI REGIME GATE:
    VEI < vei_max → stable regime → enter

  ENTRY (any bar):
    LONG:  trend bullish + close > EMA(21) + close makes new 5-bar high
    SHORT: trend bearish + close < EMA(21) + close makes new 5-bar low
    Max 1 position at a time (no adding)

  EXIT (NOT forced at EOD):
    Trailing stop: ATR(14) × stop_mult below entry (moves up with price)
    Trend reversal: EMA(21) crosses below EMA(63) → close long (vice versa)
    Max hold: max_days calendar days

  No EOD exit. Positions carry overnight. This is SWING trading
  with intraday timing precision.
"""

import backtrader as bt
import datetime as dt


class ClaudeAPEX_Swing(bt.Strategy):

    params = (
        # VEI
        ('atr_short',   10),
        ('atr_long',    50),
        ('vei_max',     1.00),   # Strict VEI — calm regimes only
        # Trend
        ('ema_fast',    21),
        ('ema_slow',    63),
        # Entry
        ('lookback',    7),      # 1-day high/low (7 bars = 1 day)
        # Exit
        ('stop_mult',   3.0),    # ATR × 3 trailing stop (wide, ride trends)
        ('max_days',    15),     # Max hold in calendar days
        # Risk
        ('atr_period',  14),
        ('risk_pct',    0.02),
        ('leverage',    5.0),
        ('real_cash',   100_000.0),
        ('trade_start', None),
        ('bars_per_day', 7),
    )

    def __init__(self):
        self.atr     = bt.indicators.ATR(self.data, period=self.params.atr_period)
        self.atr_s   = bt.indicators.ATR(self.data, period=self.params.atr_short)
        self.atr_l   = bt.indicators.ATR(self.data, period=self.params.atr_long)
        self.ema_f   = bt.indicators.EMA(self.data.close, period=self.params.ema_fast)
        self.ema_sl  = bt.indicators.EMA(self.data.close, period=self.params.ema_slow)

        self._dir         = 0
        self._trail       = 0.
        self._entry_date  = None
        self._prev_date   = None

    def _qty(self):
        atr   = self.atr[0]
        close = self.data.close[0]
        if atr <= 0 or close <= 0:
            return 0
        risk_per_share = atr * self.params.stop_mult
        risk_shares = int(self.params.real_cash * self.params.risk_pct / risk_per_share)
        lev_shares  = int(self.params.real_cash * self.params.leverage / close)
        return min(risk_shares, lev_shares)

    def _vei(self):
        al = self.atr_l[0]
        return self.atr_s[0] / al if al > 0 else 1.0

    def _new_high(self, n):
        """Is current close the highest close in last n bars?"""
        c = self.data.close[0]
        for i in range(1, n + 1):
            if self.data.close[-i] >= c:
                return False
        return True

    def _new_low(self, n):
        """Is current close the lowest close in last n bars?"""
        c = self.data.close[0]
        for i in range(1, n + 1):
            if self.data.close[-i] <= c:
                return False
        return True

    def next(self):
        if self.params.trade_start and self.data.datetime.date(0) < self.params.trade_start:
            return

        warm = max(self.params.atr_long, self.params.ema_slow,
                   self.params.atr_period, self.params.lookback) + 5
        if len(self.data) < warm:
            return

        today = self.data.datetime.date(0)
        close = self.data.close[0]
        atr   = self.atr[0]

        trend_bull = self.ema_f[0] > self.ema_sl[0]

        # ── Manage open position ────────────────────────────────────────────
        if self.position:
            # Max hold check
            if self._entry_date:
                hold_days = (today - self._entry_date).days
                if hold_days >= self.params.max_days:
                    self.close()
                    self._dir = 0; self._trail = 0.
                    return

            # Trailing stop + trend reversal
            if self._dir == 1:
                new_tr = close - atr * self.params.stop_mult
                if new_tr > self._trail:
                    self._trail = new_tr
                if close <= self._trail or not trend_bull:
                    self.close()
                    self._dir = 0; self._trail = 0.
            elif self._dir == -1:
                new_tr = close + atr * self.params.stop_mult
                if new_tr < self._trail:
                    self._trail = new_tr
                if close >= self._trail or trend_bull:
                    self.close()
                    self._dir = 0; self._trail = 0.
            return

        # ── Entry scan ──────────────────────────────────────────────────────
        # VEI regime gate
        if self._vei() >= self.params.vei_max:
            return

        qty = self._qty()
        if qty <= 0:
            return

        # LONG: bullish trend + above fast EMA + new high
        if trend_bull and close > self.ema_f[0] and self._new_high(self.params.lookback):
            self.buy(size=qty)
            self._trail      = close - atr * self.params.stop_mult
            self._dir        = 1
            self._entry_date = today

        # SHORT: bearish trend + below fast EMA + new low
        elif (not trend_bull and close < self.ema_f[0] and
              self._new_low(self.params.lookback)):
            self.sell(size=qty)
            self._trail      = close + atr * self.params.stop_mult
            self._dir        = -1
            self._entry_date = today
