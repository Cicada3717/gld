"""
ClaudeAPEX v12 — VEI-Gated Gap Momentum + Daily Trend Filter
==============================================================

v11 Results:
  GLD 5m  (59 days, 2026): +7.92%, PF 1.84  ← WORKS
  GLD 1h (249 days, 2025): -14.07%, PF 0.72 ← FAILS

v12 Fixes:
  1. DAILY TREND FILTER: EMA(trend_ema) on data timeframe.
     On 1h: EMA(105) ≈ daily EMA(15) ≈ 3-week trend
     Only LONG when price > EMA(trend) (uptrend)
     Only SHORT when price < EMA(trend) (downtrend)
     This prevents fighting the dominant trend.

  2. FIXED TARGET option: On 1h bars, trailing stop alone fails
     because 7 bars/day = stop never triggers, everything exits at EOD
     randomly. Adding ATR × target_mult gives controlled exits.
     Set target_mult=0 to disable (trailing only, for 5m).

  3. ADAPTIVE STOP: stop uses ATR(atr_period) which scales with
     the timeframe naturally.

Research Foundation:
  1. VEI Regime Gate — Prabuddha-Peramuna (2024, TASC)
  2. Gap Continuation — Crabel (1990)
  3. VWAP Institutional Anchor — Berkowitz (1988)
  4. Trend Following — "The trend is your friend" (Dow theory)
     Trading WITH the daily trend increases win rate by 10-15%.

Strategy:
  DAILY TREND GATE:
    price > EMA(trend_ema) → longs only
    price < EMA(trend_ema) → shorts only

  VEI REGIME GATE:
    VEI = ATR(short) / ATR(long)
    VEI < vei_max → stable → entries allowed

  ENTRY:
    Gap UP  >= gap_min: LONG  if close > VWAP AND EMA_fast > EMA_slow
    Gap DN  <= -gap_min: SHORT if close < VWAP AND EMA_fast < EMA_slow
    Max 1 trade per day

  EXIT:
    Trailing stop: ATR × stop_mult
    Fixed target:  ATR × target_mult (0 = disabled)
    EOD force-close at eod_bar
"""

import backtrader as bt


class VWAP(bt.Indicator):
    """Daily VWAP — resets each trading day."""
    lines    = ('vwap',)
    plotinfo  = dict(subplot=False)

    def __init__(self):
        self._cpv = 0.
        self._cv  = 0.
        self._prev = None

    def next(self):
        today = self.data.datetime.date(0)
        if today != self._prev:
            self._cpv = 0.
            self._cv  = 0.
            self._prev = today
        tp  = (self.data.high[0] + self.data.low[0] + self.data.close[0]) / 3.
        vol = max(self.data.volume[0], 1)
        self._cpv += tp * vol
        self._cv  += vol
        self.lines.vwap[0] = self._cpv / self._cv


class ClaudeAPEX(bt.Strategy):

    params = (
        # VEI Regime Filter
        ('atr_short',  10),
        ('atr_long',   50),
        ('vei_max',    1.08),
        # Trend (intraday)
        ('ema_fast',   9),
        ('ema_slow',   21),
        # Daily trend filter (0 = disabled)
        ('trend_ema',  0),
        # Indicators
        ('atr_period', 14),
        # Gap threshold
        ('gap_min',    0.0010),   # 0.10% (was 0.15% — IB commission allows tighter)
        # Entry window
        ('entry_start', 2),
        ('entry_end',  25),       # ~11:35 AM (was 10:45 — wider for more trades)
        ('eod_bar',    72),
        # Exit
        ('stop_mult',  3.0),
        ('target_mult', 0.0),   # 0 = disabled (trail only)
        # Risk
        ('risk_pct',   0.02),
        ('leverage',   5.0),
        ('real_cash',  100_000.0),
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

        # Daily trend EMA (optional)
        self._use_trend = self.params.trend_ema > 0
        if self._use_trend:
            self.ema_trend = bt.indicators.EMA(
                self.data.close, period=self.params.trend_ema)

        self._prev_date   = None
        self._bar         = 0
        self._prior_close = 0.
        self._traded      = False
        self._eod         = False

        self._dir    = 0
        self._trail  = 0.
        self._target = 0.
        self._entry  = 0.
        self._size   = 0
        self._exit_reason = ''

        # Trade detail log (strategy pushes details here for the analyzer)
        self.trade_details = []

    def _qty(self):
        atr   = self.atr[0]
        close = self.data.close[0]
        if atr <= 0 or close <= 0:
            return 0
        risk_shares = int(self.params.real_cash * self.params.risk_pct /
                          (atr * self.params.stop_mult))
        lev_shares  = int(self.params.real_cash * self.params.leverage / close)
        return min(risk_shares, lev_shares)

    def _vei(self):
        al = self.atr_l[0]
        if al <= 0:
            return 1.0
        return self.atr_s[0] / al

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
        atr   = self.atr[0]

        # ── New day ────────────────────────────────────────────────────────
        if today != self._prev_date:
            if self.position:
                self._exit_reason = 'NEW_DAY'
                self.close()
                self._dir = 0; self._trail = 0.; self._target = 0.
            if self._prev_date is not None:
                self._prior_close = self.data.close[-1]
            self._prev_date = today
            self._bar       = 0
            self._traded    = False
            self._eod       = False
            self._bar      += 1
            return

        self._bar += 1
        b = self._bar

        # ── EOD force-close ─────────────────────────────────────────────────
        if b >= self.params.eod_bar:
            if self.position and not self._eod:
                self._exit_reason = 'EOD'
                self.close()
                self._eod = True
                self._dir = 0; self._trail = 0.; self._target = 0.
            return

        # ── Manage open position ────────────────────────────────────────────
        if self.position:
            if self._dir == 1:
                new_tr = close - atr * self.params.stop_mult
                if new_tr > self._trail: self._trail = new_tr
                hit_stop   = close <= self._trail
                hit_target = (self._target > 0 and close >= self._target)
                if hit_stop or hit_target:
                    self._exit_reason = 'STOP' if hit_stop else 'TARGET'
                    self.close(); self._dir = 0
            elif self._dir == -1:
                new_tr = close + atr * self.params.stop_mult
                if new_tr < self._trail: self._trail = new_tr
                hit_stop   = close >= self._trail
                hit_target = (self._target > 0 and close <= self._target)
                if hit_stop or hit_target:
                    self._exit_reason = 'STOP' if hit_stop else 'TARGET'
                    self.close(); self._dir = 0
            return

        # ── Entry scan ──────────────────────────────────────────────────────
        if self._traded or b < self.params.entry_start or b > self.params.entry_end:
            return

        if self._prior_close <= 0:
            return

        # VEI regime gate
        vei = self._vei()
        if vei >= self.params.vei_max:
            return

        # Daily trend gate
        if self._use_trend:
            trend_bull = close > self.ema_trend[0]
        else:
            trend_bull = None  # No filter

        gap      = (close - self._prior_close) / self._prior_close
        vwap     = self.vwap.lines.vwap[0]
        ema_bull = self.ema_f[0] > self.ema_s[0]

        qty = self._qty()
        if qty <= 0:
            return

        tm = self.params.target_mult

        # LONG: gap up + above VWAP + EMA bullish + trend bullish (if enabled)
        if (gap >= self.params.gap_min and
            close > vwap and ema_bull and
            (trend_bull is None or trend_bull)):
            self.buy(size=qty)
            self._trail  = close - atr * self.params.stop_mult
            self._target = close + atr * tm if tm > 0 else 0.
            self._entry  = close
            self._dir    = 1
            self._size   = qty
            self._exit_reason = ''
            self._traded = True
            self.trade_details.append({
                'entry_px': round(close, 3),
                'shares': qty,
                'dir': 'LONG',
                'stop': round(self._trail, 3),
                'target': round(self._target, 3) if self._target > 0 else None,
                'vwap': round(vwap, 3),
                'gap_pct': round(gap * 100, 3),
                'atr': round(atr, 3),
                'vei': round(vei, 3),
                'bar': b,
            })

        # SHORT: gap down + below VWAP + EMA bearish + trend bearish
        elif (gap <= -self.params.gap_min and
              close < vwap and not ema_bull and
              (trend_bull is None or not trend_bull)):
            self.sell(size=qty)
            self._trail  = close + atr * self.params.stop_mult
            self._target = close - atr * tm if tm > 0 else 0.
            self._entry  = close
            self._dir    = -1
            self._size   = qty
            self._exit_reason = ''
            self._traded = True
            self.trade_details.append({
                'entry_px': round(close, 3),
                'shares': qty,
                'dir': 'SHORT',
                'stop': round(self._trail, 3),
                'target': round(self._target, 3) if self._target > 0 else None,
                'vwap': round(vwap, 3),
                'gap_pct': round(gap * 100, 3),
                'atr': round(atr, 3),
                'vei': round(vei, 3),
                'bar': b,
            })
