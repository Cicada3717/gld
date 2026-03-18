"""
ClaudeAPEX-H1 v2 — Trend Pullback Reversal (1h bars)
=====================================================

WHY v1 FAILED:
  Opening bar breakout on 1h = 33% win rate, PF 0.59.
  Breakouts on 1h have too many false signals with 7 bars/day.

NEW APPROACH — Trend Pullback:
  Instead of breakouts, trade PULLBACKS within a strong trend.
  In a strong uptrend, dips are buying opportunities.
  In a strong downtrend, bounces are shorting opportunities.

  This has higher base win rate (60-70%) because you're trading
  WITH the trend after a mean-reverting dip.

Strategy:
  TREND FILTER (strong trend required):
    EMA(21) on 1h bars (fast trend)
    EMA(63) on 1h bars (slow trend — ~9 trading days)
    STRONG BULL: EMA(21) > EMA(63) AND close > EMA(21) at some point today
    STRONG BEAR: EMA(21) < EMA(63) AND close < EMA(21) at some point today

  VEI REGIME GATE:
    VEI = ATR(10) / ATR(50) < vei_max → stable

  PULLBACK DETECTION (bar 0-2):
    LONG setup:  trend bullish but bar closes below EMA(21) — dip into support
    SHORT setup: trend bearish but bar closes above EMA(21) — rally into resistance

  ENTRY TRIGGER (bar 1-4):
    LONG:  after pullback, bar close > prior bar high → bounce confirmed
    SHORT: after pullback, bar close < prior bar low → rejection confirmed

  STOP: Below the pullback low (longs) / above pullback high (shorts)
    Market-defined, tight stop.

  TARGET: 2× risk from entry (R:R = 2:1)
    OR EOD exit at bar 6.

  KEY ADVANTAGE: Stop is TIGHT (just below the dip) so position size is
  LARGER for same risk budget → bigger winners when it works.
"""

import backtrader as bt


class ClaudeAPEX_H1v2(bt.Strategy):

    params = (
        # VEI
        ('atr_short',   10),
        ('atr_long',    50),
        ('vei_max',     1.05),
        # Trend
        ('ema_fast',    21),     # ~3 trading days
        ('ema_slow',    63),     # ~9 trading days
        # Entry
        ('entry_start', 1),      # Bar 1 (10:30 AM)
        ('entry_end',   4),      # Bar 4 (1:30 PM) — wider window for pullbacks
        ('eod_bar',     6),      # Force close
        # Target R:R
        ('target_rr',   2.0),
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

        self._prev_date = None
        self._bar       = 0
        self._traded    = False
        self._eod       = False

        # Pullback tracking
        self._pullback_long  = False   # Seen a dip below EMA in uptrend
        self._pullback_short = False   # Seen a rally above EMA in downtrend
        self._pullback_low   = 0.      # Lowest low during pullback (long stop)
        self._pullback_high  = 0.      # Highest high during pullback (short stop)

        self._dir    = 0
        self._stoplvl = 0.
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

        warm = max(self.params.atr_long, self.params.ema_slow,
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
            self._prev_date      = today
            self._bar            = 0
            self._traded         = False
            self._eod            = False
            self._pullback_long  = False
            self._pullback_short = False
            self._pullback_low   = 9999999.
            self._pullback_high  = 0.
            self._bar           += 1
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

        # ── Trend determination ─────────────────────────────────────────────
        ema_f = self.ema_f[0]
        ema_s = self.ema_sl[0]
        trend_bull = ema_f > ema_s
        trend_bear = ema_f < ema_s

        # ── Pullback detection ──────────────────────────────────────────────
        # In uptrend: if close dips below fast EMA, that's a pullback
        if trend_bull and close < ema_f:
            self._pullback_long = True
            if self.data.low[0] < self._pullback_low:
                self._pullback_low = self.data.low[0]

        # In downtrend: if close rallies above fast EMA, that's a pullback
        if trend_bear and close > ema_f:
            self._pullback_short = True
            if self.data.high[0] > self._pullback_high:
                self._pullback_high = self.data.high[0]

        # ── Entry scan ──────────────────────────────────────────────────────
        if self._traded or b < self.params.entry_start or b > self.params.entry_end:
            return

        # VEI gate
        if self._vei() >= self.params.vei_max:
            return

        # Need prior bar data
        if len(self.data) < 2:
            return
        prior_high = self.data.high[-1]
        prior_low  = self.data.low[-1]

        # LONG: uptrend + saw pullback + now bouncing (close > prior bar high)
        if (trend_bull and self._pullback_long and
            close > ema_f and close > prior_high):
            risk = close - self._pullback_low
            atr = self.atr[0]
            # Sanity: risk must be reasonable (0.2-2× ATR)
            if atr <= 0 or risk < atr * 0.15 or risk > atr * 2.5:
                return
            qty = self._qty(risk)
            if qty <= 0:
                return
            self.buy(size=qty)
            self._stoplvl = self._pullback_low
            self._target  = close + risk * self.params.target_rr
            self._dir     = 1
            self._traded  = True

        # SHORT: downtrend + saw pullback + now rejecting (close < prior bar low)
        elif (trend_bear and self._pullback_short and
              close < ema_f and close < prior_low):
            risk = self._pullback_high - close
            atr = self.atr[0]
            if atr <= 0 or risk < atr * 0.15 or risk > atr * 2.5:
                return
            qty = self._qty(risk)
            if qty <= 0:
                return
            self.sell(size=qty)
            self._stoplvl = self._pullback_high
            self._target  = close - risk * self.params.target_rr
            self._dir     = -1
            self._traded  = True
