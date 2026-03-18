"""
ClaudeAPEX-H1 v3 — Momentum Bar + Trend (1h bars)
===================================================

Previous failures:
  v1 (Opening Bar Breakout): -26.58%, PF 0.59, 33% WR — too many false breakouts
  v2 (Trend Pullback):       -12.12%, PF 0.00, 0% WR — too few signals, all wrong

NEW APPROACH — Momentum Bar Continuation:
  On 1h bars, bar 0 (9:30-10:30) often sets the day's direction.
  If bar 0 is a STRONG move AND aligns with the daily trend,
  the momentum tends to continue.

  Key difference from v1: we don't wait for a "breakout" of bar 0's range.
  Instead, we look at bar 0's CHARACTER:
    - Strong close near high → bullish momentum → continue long
    - Strong close near low → bearish momentum → continue short
  Then enter on bar 1 if the momentum continues.

Strategy:
  TREND: EMA(21) vs EMA(63) on 1h — clear trend direction

  BAR 0 MOMENTUM (9:30-10:30 AM):
    bar_body = close - open
    bar_range = high - low
    momentum_pct = bar_body / open (% move)

    BULLISH BAR 0: momentum_pct > +min_momentum AND close in top 30% of range
    BEARISH BAR 0: momentum_pct < -min_momentum AND close in bottom 30% of range

  ENTRY (bar 1-2):
    LONG:  bullish bar 0 + bullish trend + VEI stable
           Enter if bar 1 close > bar 0 close (momentum continues)
    SHORT: bearish bar 0 + bearish trend + VEI stable
           Enter if bar 1 close < bar 0 close (momentum continues)

  STOP: bar 0 opposite extreme (tight, market-defined)
  TARGET: 2× risk OR EOD
"""

import backtrader as bt


class ClaudeAPEX_H1v3(bt.Strategy):

    params = (
        # VEI
        ('atr_short',      10),
        ('atr_long',       50),
        ('vei_max',        1.05),
        # Trend
        ('ema_fast',       21),
        ('ema_slow',       63),
        # Momentum threshold
        ('min_momentum',   0.002),   # 0.2% min bar 0 body
        ('close_pct',      0.30),    # Close must be in top/bottom 30% of range
        # Entry
        ('entry_start',    1),
        ('entry_end',      2),       # Only bar 1-2
        ('eod_bar',        6),
        # Target
        ('target_rr',      2.0),
        # Risk
        ('atr_period',     14),
        ('risk_pct',       0.02),
        ('leverage',       5.0),
        ('real_cash',      100_000.0),
        ('trade_start',    None),
        ('bars_per_day',   7),
    )

    def __init__(self):
        self.atr     = bt.indicators.ATR(self.data, period=self.params.atr_period)
        self.atr_s   = bt.indicators.ATR(self.data, period=self.params.atr_short)
        self.atr_l   = bt.indicators.ATR(self.data, period=self.params.atr_long)
        self.ema_f   = bt.indicators.EMA(self.data.close, period=self.params.ema_fast)
        self.ema_sl  = bt.indicators.EMA(self.data.close, period=self.params.ema_slow)

        self._prev_date = None
        self._bar       = 0
        self._traded    = False
        self._eod       = False

        # Bar 0 data
        self._bar0_open  = 0.
        self._bar0_close = 0.
        self._bar0_high  = 0.
        self._bar0_low   = 0.
        self._bar0_bull  = False
        self._bar0_bear  = False

        self._dir     = 0
        self._stoplvl = 0.
        self._target  = 0.

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

        warm = max(self.params.atr_long, self.params.ema_slow,
                   self.params.atr_period) + 5
        if len(self.data) < warm:
            return

        today = self.data.datetime.date(0)
        close = self.data.close[0]

        # ── New day → this IS bar 0 ───────────────────────────────────────
        if today != self._prev_date:
            if self.position:
                self.close()
                self._dir = 0; self._stoplvl = 0.; self._target = 0.
            self._prev_date  = today
            self._bar        = 0
            self._traded     = False
            self._eod        = False
            self._bar0_bull  = False
            self._bar0_bear  = False

            # Record bar 0 data
            self._bar0_open  = self.data.open[0]
            self._bar0_close = close
            self._bar0_high  = self.data.high[0]
            self._bar0_low   = self.data.low[0]

            bar_range = self._bar0_high - self._bar0_low
            if bar_range > 0 and self._bar0_open > 0:
                body = close - self._bar0_open
                momentum = body / self._bar0_open
                # Close position within range (0=low, 1=high)
                close_pos = (close - self._bar0_low) / bar_range

                if (momentum >= self.params.min_momentum and
                    close_pos >= (1.0 - self.params.close_pct)):
                    self._bar0_bull = True

                if (momentum <= -self.params.min_momentum and
                    close_pos <= self.params.close_pct):
                    self._bar0_bear = True

            self._bar += 1
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

        # Trend
        trend_bull = self.ema_f[0] > self.ema_sl[0]

        # LONG: bullish bar 0 + bullish trend + momentum continues
        if (self._bar0_bull and trend_bull and
            close > self._bar0_close):
            risk = close - self._bar0_low
            atr = self.atr[0]
            if atr <= 0 or risk < atr * 0.1 or risk > atr * 3.0:
                return
            qty = self._qty(risk)
            if qty <= 0:
                return
            self.buy(size=qty)
            self._stoplvl = self._bar0_low
            self._target  = close + risk * self.params.target_rr
            self._dir     = 1
            self._traded  = True

        # SHORT: bearish bar 0 + bearish trend + momentum continues
        elif (self._bar0_bear and not trend_bull and
              close < self._bar0_close):
            risk = self._bar0_high - close
            atr = self.atr[0]
            if atr <= 0 or risk < atr * 0.1 or risk > atr * 3.0:
                return
            qty = self._qty(risk)
            if qty <= 0:
                return
            self.sell(size=qty)
            self._stoplvl = self._bar0_high
            self._target  = close - risk * self.params.target_rr
            self._dir     = -1
            self._traded  = True
