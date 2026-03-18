"""
ClaudeAPEX v15 — High-Frequency Gap Momentum + VWAP Bounce (5m bars)
=====================================================================

v12: +8.99%, PF 2.02, 19 trades (2.2/week) — proven but too few trades
v13: -49%, 47 trades — too many bad signals (IB/VWAP/VA noise)
v14: -16.5%, 54 trades — IB signal adds no edge

v15 APPROACH: Instead of adding new signal TYPES, expand the PROVEN
gap momentum with two changes:
  1. More permissive gap threshold (0.08% vs 0.15%)
  2. Add VWAP Trend Bounce as second entry (same exit logic)
  3. Wider entry window (bar 2-40 vs bar 2-15)

SIGNAL A — Gap Momentum (relaxed from v12):
  Gap >= 0.08% + close > VWAP + EMA_fast > EMA_slow → LONG
  Gap <= -0.08% + close < VWAP + EMA bearish → SHORT
  Same trailing stop exit as v12.

SIGNAL B — VWAP Trend Bounce:
  In bullish trend (EMA fast > slow), price pulls back to touch VWAP
  and bounces → LONG. Vice versa for shorts.
  This catches intraday pullback entries that gap continuation misses.
  Key: only when price was ABOVE VWAP earlier today (established trend)
  then touches VWAP = institutional buying level.

Both signals share: VEI gate, trailing stop, EOD close, max 1 trade/day.
"""

import backtrader as bt


class VWAP(bt.Indicator):
    lines = ('vwap',)
    plotinfo = dict(subplot=False)

    def __init__(self):
        self._cpv = 0.
        self._cv = 0.
        self._prev = None

    def next(self):
        today = self.data.datetime.date(0)
        if today != self._prev:
            self._cpv = 0.
            self._cv = 0.
            self._prev = today
        tp = (self.data.high[0] + self.data.low[0] + self.data.close[0]) / 3.
        vol = max(self.data.volume[0], 1)
        self._cpv += tp * vol
        self._cv += vol
        self.lines.vwap[0] = self._cpv / self._cv


class ClaudeAPEX_v15(bt.Strategy):

    params = (
        # VEI Regime Filter
        ('atr_short',   10),
        ('atr_long',    50),
        ('vei_max',     1.08),
        # Trend (intraday)
        ('ema_fast',    9),
        ('ema_slow',    21),
        # Daily trend filter
        ('trend_ema',   0),
        # Indicators
        ('atr_period',  14),
        # Gap threshold (more permissive than v12's 0.0015)
        ('gap_min',     0.0008),
        # VWAP bounce params
        ('vwap_touch_atr', 0.3),  # Price within 0.3×ATR of VWAP = "touching"
        ('vwap_bounce_bars', 3),  # Must bounce away within 3 bars
        # Entry window (wider than v12)
        ('entry_start', 2),
        ('entry_end',   40),       # ~12:50 PM (was 15 in v12)
        ('eod_bar',     72),
        # Exit
        ('stop_mult',   3.0),
        ('target_mult', 0.0),     # 0 = trailing only
        # Risk
        ('risk_pct',    0.02),
        ('leverage',    5.0),
        ('real_cash',   100_000.0),
        ('trade_start', None),
        ('bars_per_day', 78),
    )

    def __init__(self):
        self.vwap  = VWAP(self.data)
        self.atr   = bt.indicators.ATR(self.data, period=self.params.atr_period)
        self.atr_s = bt.indicators.ATR(self.data, period=self.params.atr_short)
        self.atr_l = bt.indicators.ATR(self.data, period=self.params.atr_long)
        self.ema_f = bt.indicators.EMA(self.data.close, period=self.params.ema_fast)
        self.ema_s = bt.indicators.EMA(self.data.close, period=self.params.ema_slow)

        self._use_trend = self.params.trend_ema > 0
        if self._use_trend:
            self.ema_trend = bt.indicators.EMA(
                self.data.close, period=self.params.trend_ema)

        self._prev_date = None
        self._bar = 0
        self._prior_close = 0.
        self._traded = False
        self._eod = False

        # VWAP bounce tracking
        self._above_vwap_today = False  # Was price above VWAP at some point
        self._below_vwap_today = False  # Was price below VWAP at some point
        self._vwap_touched = False       # Did price touch VWAP after being away
        self._vwap_touch_bar = 0         # Bar when VWAP was touched

        self._dir = 0
        self._trail = 0.
        self._target = 0.
        self._entry = 0.

    def _qty(self):
        atr = self.atr[0]
        close = self.data.close[0]
        if atr <= 0 or close <= 0:
            return 0
        risk_shares = int(self.params.real_cash * self.params.risk_pct /
                          (atr * self.params.stop_mult))
        lev_shares = int(self.params.real_cash * self.params.leverage / close)
        return min(risk_shares, lev_shares)

    def _vei(self):
        al = self.atr_l[0]
        return self.atr_s[0] / al if al > 0 else 1.0

    def next(self):
        if self.params.trade_start and self.data.datetime.date(0) < self.params.trade_start:
            return

        warm = max(self.params.atr_long, self.params.ema_slow,
                   self.params.atr_period)
        if self._use_trend:
            warm = max(warm, self.params.trend_ema)
        if len(self.data) < warm + 5:
            return

        today = self.data.datetime.date(0)
        close = self.data.close[0]
        atr = self.atr[0]

        # ── New day ────────────────────────────────────────────────────────
        if today != self._prev_date:
            if self.position:
                self.close()
                self._dir = 0; self._trail = 0.; self._target = 0.
            if self._prev_date is not None:
                self._prior_close = self.data.close[-1]
            self._prev_date = today
            self._bar = 0
            self._traded = False
            self._eod = False
            self._above_vwap_today = False
            self._below_vwap_today = False
            self._vwap_touched = False
            self._vwap_touch_bar = 0
            self._bar += 1
            return

        self._bar += 1
        b = self._bar

        # Track VWAP relationship
        vwap = self.vwap.lines.vwap[0]
        vwap_dist = abs(close - vwap)
        touch_zone = atr * self.params.vwap_touch_atr if atr > 0 else 0.5

        if close > vwap + touch_zone:
            self._above_vwap_today = True
        if close < vwap - touch_zone:
            self._below_vwap_today = True

        # Detect VWAP touch (price returns to VWAP after being away)
        if vwap_dist <= touch_zone:
            if (self._above_vwap_today or self._below_vwap_today) and not self._vwap_touched:
                self._vwap_touched = True
                self._vwap_touch_bar = b

        # ── EOD force-close ─────────────────────────────────────────────────
        if b >= self.params.eod_bar:
            if self.position and not self._eod:
                self.close()
                self._eod = True
                self._dir = 0; self._trail = 0.; self._target = 0.
            return

        # ── Manage open position ────────────────────────────────────────────
        if self.position:
            if self._dir == 1:
                new_tr = close - atr * self.params.stop_mult
                if new_tr > self._trail:
                    self._trail = new_tr
                hit_stop = close <= self._trail
                hit_target = (self._target > 0 and close >= self._target)
                if hit_stop or hit_target:
                    self.close(); self._dir = 0
            elif self._dir == -1:
                new_tr = close + atr * self.params.stop_mult
                if new_tr < self._trail:
                    self._trail = new_tr
                hit_stop = close >= self._trail
                hit_target = (self._target > 0 and close <= self._target)
                if hit_stop or hit_target:
                    self.close(); self._dir = 0
            return

        # ── Entry scan ──────────────────────────────────────────────────────
        if self._traded or b < self.params.entry_start or b > self.params.entry_end:
            return

        # VEI regime gate
        if self._vei() >= self.params.vei_max:
            return

        ema_bull = self.ema_f[0] > self.ema_s[0]

        # Daily trend gate
        if self._use_trend:
            trend_bull = close > self.ema_trend[0]
        else:
            trend_bull = None

        qty = self._qty()
        if qty <= 0:
            return

        tm = self.params.target_mult

        # ── SIGNAL A: Gap Momentum ─────────────────────────────────────────
        if self._prior_close > 0:
            gap = (close - self._prior_close) / self._prior_close

            # LONG: gap up + above VWAP + EMA bullish
            if (gap >= self.params.gap_min and close > vwap and ema_bull and
                (trend_bull is None or trend_bull)):
                self.buy(size=qty)
                self._trail = close - atr * self.params.stop_mult
                self._target = close + atr * tm if tm > 0 else 0.
                self._entry = close
                self._dir = 1
                self._traded = True
                return

            # SHORT: gap down + below VWAP + EMA bearish
            if (gap <= -self.params.gap_min and close < vwap and not ema_bull and
                (trend_bull is None or not trend_bull)):
                self.sell(size=qty)
                self._trail = close + atr * self.params.stop_mult
                self._target = close - atr * tm if tm > 0 else 0.
                self._entry = close
                self._dir = -1
                self._traded = True
                return

        # ── SIGNAL B: VWAP Trend Bounce ────────────────────────────────────
        # Only after bar 12 (first hour) and if VWAP was touched after being away
        if b >= 12 and self._vwap_touched:
            bars_since_touch = b - self._vwap_touch_bar
            if 1 <= bars_since_touch <= self.params.vwap_bounce_bars:

                # LONG bounce: was above VWAP, touched VWAP, now bouncing up
                if (self._above_vwap_today and close > vwap and ema_bull and
                    (trend_bull is None or trend_bull)):
                    self.buy(size=qty)
                    self._trail = close - atr * self.params.stop_mult
                    self._target = close + atr * tm if tm > 0 else 0.
                    self._entry = close
                    self._dir = 1
                    self._traded = True
                    return

                # SHORT bounce: was below VWAP, touched VWAP, now rejecting down
                if (self._below_vwap_today and close < vwap and not ema_bull and
                    (trend_bull is None or not trend_bull)):
                    self.sell(size=qty)
                    self._trail = close + atr * self.params.stop_mult
                    self._target = close - atr * tm if tm > 0 else 0.
                    self._entry = close
                    self._dir = -1
                    self._traded = True
                    return
