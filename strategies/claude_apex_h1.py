"""
ClaudeAPEX-H1 — Opening Bar Breakout + VEI + Trend (1h bars)
==============================================================

Designed specifically for 1h bars where gap continuation fails.

Key Insight: On 1h, bar 0 (9:30-10:30 AM) establishes the opening range.
A breakout above/below bar 0 WITH the daily trend has predictive power.
The STOP is defined by bar 0's extreme (market-defined, not ATR-based).

Strategy:
  TREND FILTER:
    EMA(trend_ema) on 1h bars (e.g., 105 ≈ daily EMA(15))
    Price > EMA(trend) → only LONG
    Price < EMA(trend) → only SHORT

  VEI REGIME GATE:
    VEI = ATR(10) / ATR(50) < vei_max → stable

  ENTRY (bar 1-3):
    LONG:  close > bar_0_high AND trend bullish AND VEI stable
    SHORT: close < bar_0_low  AND trend bearish AND VEI stable
    Volume confirmation optional.
    Max 1 trade per day.

  STOP: bar 0 low (for longs), bar 0 high (for shorts)
    This is a MARKET-DEFINED stop, not ATR-based.

  TARGET: 2× opening range from entry (R:R = 2:1)
    OR EOD exit at bar 6.
"""

import backtrader as bt


class ClaudeAPEX_H1(bt.Strategy):

    params = (
        # VEI
        ('atr_short',   10),
        ('atr_long',    50),
        ('vei_max',     1.05),
        # Trend
        ('trend_ema',   105),    # 105h ≈ 15 trading days ≈ 3 weeks
        # Entry
        ('entry_start', 1),      # Bar 1 (10:30 AM)
        ('entry_end',   3),      # Bar 3 (12:30 PM)
        ('eod_bar',     6),      # Force close
        # Target R:R
        ('target_rr',   2.0),    # Target = 2× risk (opening range)
        # Max opening range (skip wide-range days)
        ('max_or_atr',  1.5),    # OR must be < 1.5× ATR(14) — skip huge days
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
        self.ema_t   = bt.indicators.EMA(self.data.close, period=self.params.trend_ema)

        self._prev_date = None
        self._bar       = 0
        self._bar0_high = 0.
        self._bar0_low  = 0.
        self._bar0_range = 0.
        self._traded    = False
        self._eod       = False

        self._dir    = 0
        self._stoplvl   = 0.
        self._target = 0.

    def _qty(self, risk_per_share):
        close = self.data.close[0]
        if risk_per_share <= 0 or close <= 0:
            return 0
        risk_shares = int(self.params.real_cash * self.params.risk_pct / risk_per_share)
        lev_shares  = int(self.params.real_cash * self.params.leverage / close)
        return min(risk_shares, lev_shares)

    def _vei(self):
        al = self.atr_l[0]
        return self.atr_s[0] / al if al > 0 else 1.0

    def next(self):
        if self.params.trade_start and self.data.datetime.date(0) < self.params.trade_start:
            return

        warm = max(self.params.atr_long, self.params.trend_ema,
                   self.params.atr_period) + 5
        if len(self.data) < warm:
            return

        today = self.data.datetime.date(0)
        close = self.data.close[0]

        # ── New day ────────────────────────────────────────────────────────
        if today != self._prev_date:
            if self.position:
                self.close()
                self._dir = 0; self._stoplvl = 0.; self._target = 0.
            self._prev_date  = today
            self._bar        = 0
            self._bar0_high  = self.data.high[0]
            self._bar0_low   = self.data.low[0]
            self._bar0_range = self.data.high[0] - self.data.low[0]
            self._traded     = False
            self._eod        = False
            self._bar       += 1
            return

        self._bar += 1
        b = self._bar

        # ── EOD force-close ─────────────────────────────────────────────────
        if b >= self.params.eod_bar:
            if self.position and not self._eod:
                self.close()
                self._eod = True
                self._dir = 0; self._stoplvl = 0.; self._target = 0.
            return

        # ── Manage open position ────────────────────────────────────────────
        if self.position:
            if self._dir == 1:
                if close <= self._stoplvl or close >= self._target:
                    self.close(); self._dir = 0
            elif self._dir == -1:
                if close >= self._stoplvl or close <= self._target:
                    self.close(); self._dir = 0
            return

        # ── Entry scan ──────────────────────────────────────────────────────
        if self._traded or b < self.params.entry_start or b > self.params.entry_end:
            return

        # VEI gate
        if self._vei() >= self.params.vei_max:
            return

        # Skip very wide opening ranges (choppy/volatile days)
        atr = self.atr[0]
        if atr <= 0 or self._bar0_range > atr * self.params.max_or_atr:
            return

        # Skip tiny ranges (no setup)
        if self._bar0_range < atr * 0.3:
            return

        trend_bull = close > self.ema_t[0]
        or_range   = self._bar0_range

        # LONG: breakout above bar 0 high + bullish trend
        if close > self._bar0_high and trend_bull:
            risk = close - self._bar0_low  # Stop at bar 0 low
            qty  = self._qty(risk)
            if qty <= 0: return
            self.buy(size=qty)
            self._stoplvl   = self._bar0_low
            self._target = close + or_range * self.params.target_rr
            self._dir    = 1
            self._traded = True

        # SHORT: breakdown below bar 0 low + bearish trend
        elif close < self._bar0_low and not trend_bull:
            risk = self._bar0_high - close  # Stop at bar 0 high
            qty  = self._qty(risk)
            if qty <= 0: return
            self.sell(size=qty)
            self._stoplvl   = self._bar0_high
            self._target = close - or_range * self.params.target_rr
            self._dir    = -1
            self._traded = True
