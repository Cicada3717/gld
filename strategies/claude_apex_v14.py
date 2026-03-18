"""
ClaudeAPEX v14 — Dual-Signal Intraday (5m bars)
=================================================

v12 had +8.99% / PF 2.02 but only 19 trades (2.2/week).
v13 multi-signal had 47 trades but -49% — too many noise signals.

v14 APPROACH: Keep the PROVEN v12 gap momentum signal + add ONE
additional signal — IB Breakout Retracement — with strict filters.

SIGNAL A — Gap Momentum (from v12, proven PF 2.02):
  Gap UP  >= gap_min + close > VWAP + EMA_fast > EMA_slow → LONG
  Gap DOWN <= -gap_min + close < VWAP + EMA_fast < EMA_slow → SHORT
  Trailing stop: ATR × stop_mult
  Max 1 trade per day from this signal

SIGNAL B — IB Breakout Retracement (gold-specific):
  First hour defines Initial Balance (IB high/low).
  After breakout of IB, wait for retracement BACK to IB boundary.
  Enter on the retracement with tight stop.
  STRICT FILTERS:
    - IB range must be 0.4-1.5% of price (skip tiny/huge ranges)
    - Breakout must be confirmed (close > IB high, not just wick)
    - Retracement must be clean (price returns to within 15% of IB boundary)
    - Trend must align (EMA_fast direction matches trade direction)
    - Only if Signal A didn't trigger today
  Stop: 40% of IB range below entry
  Target: IB high + 35% of IB range (for longs)

SHARED:
  VEI regime gate
  Daily VWAP
  EOD force close
  Max 1 trade per day (either signal, not both)
"""

import backtrader as bt


class VWAP(bt.Indicator):
    """Daily VWAP — resets each trading day."""
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


class ClaudeAPEX_v14(bt.Strategy):

    params = (
        # VEI Regime Filter
        ('atr_short',   10),
        ('atr_long',    50),
        ('vei_max',     1.08),
        # Trend (intraday)
        ('ema_fast',    9),
        ('ema_slow',    21),
        # Daily trend filter (0 = disabled)
        ('trend_ema',   0),
        # Indicators
        ('atr_period',  14),
        # Gap threshold (Signal A)
        ('gap_min',     0.0015),
        # IB params (Signal B)
        ('ib_bars',     12),       # 12 × 5min = 1 hour
        ('ib_retr_pct', 0.15),     # Enter within 15% of IB boundary
        ('ib_stop_pct', 0.40),     # Stop at 40% of IB range
        ('ib_tgt_pct',  0.35),     # Target 35% above IB boundary
        ('ib_min_range', 0.004),   # Min IB range 0.4% of price
        ('ib_max_range', 0.015),   # Max IB range 1.5% of price
        # Entry window
        ('entry_start', 2),        # Signal A: bar 2 onward
        ('ib_entry_start', 13),    # Signal B: after IB completes
        ('entry_end',   50),       # Both signals cutoff (~2:00 PM)
        ('eod_bar',     72),       # EOD force close
        # Exit (Signal A)
        ('stop_mult',   3.0),
        ('target_mult', 0.0),      # 0 = trailing only for gap signal
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

        # Day state
        self._prev_date = None
        self._bar = 0
        self._prior_close = 0.
        self._traded = False
        self._eod = False

        # IB tracking
        self._ib_high = 0.
        self._ib_low = 0.
        self._ib_range = 0.
        self._ib_broken_up = False
        self._ib_broken_down = False
        self._ib_valid = False  # IB range passes filters

        # Position state
        self._dir = 0
        self._trail = 0.
        self._target = 0.
        self._entry = 0.
        self._signal_type = ''

    def _qty_risk(self, risk_per_share):
        """Size by risk per share (for IB signal)."""
        close = self.data.close[0]
        if risk_per_share <= 0 or close <= 0:
            return 0
        risk_shares = int(self.params.real_cash * self.params.risk_pct / risk_per_share)
        lev_shares = int(self.params.real_cash * self.params.leverage / close)
        return min(risk_shares, lev_shares)

    def _qty_atr(self):
        """Size by ATR (for gap signal)."""
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
        return self.atr_s[0] / al if al <= 0 else self.atr_s[0] / al

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
        high = self.data.high[0]
        low = self.data.low[0]
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

            # Reset IB
            self._ib_high = high
            self._ib_low = low
            self._ib_range = 0.
            self._ib_broken_up = False
            self._ib_broken_down = False
            self._ib_valid = False
            self._signal_type = ''

            self._bar += 1
            return

        self._bar += 1
        b = self._bar

        # Build IB during first hour
        if b <= self.params.ib_bars:
            if high > self._ib_high:
                self._ib_high = high
            if low < self._ib_low:
                self._ib_low = low
            if b == self.params.ib_bars:
                self._ib_range = self._ib_high - self._ib_low
                ib_pct = self._ib_range / close if close > 0 else 0
                self._ib_valid = (self.params.ib_min_range <= ib_pct
                                  <= self.params.ib_max_range)

        # Track IB breakouts (only after IB forms)
        if b > self.params.ib_bars and self._ib_range > 0:
            if close > self._ib_high and not self._ib_broken_up:
                self._ib_broken_up = True
            if close < self._ib_low and not self._ib_broken_down:
                self._ib_broken_down = True

        # ── EOD force-close ─────────────────────────────────────────────────
        if b >= self.params.eod_bar:
            if self.position and not self._eod:
                self.close()
                self._eod = True
                self._dir = 0; self._trail = 0.; self._target = 0.
            return

        # ── Manage open position ────────────────────────────────────────────
        if self.position:
            if self._signal_type == 'GAP':
                # Trailing stop (from v12)
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
            else:
                # Fixed stop/target (for IB signal)
                if self._dir == 1:
                    if close <= self._trail or close >= self._target:
                        self.close(); self._dir = 0
                elif self._dir == -1:
                    if close >= self._trail or close <= self._target:
                        self.close(); self._dir = 0
            return

        # ── Entry scan ──────────────────────────────────────────────────────
        if self._traded:
            return

        # VEI regime gate
        vei = self._vei()
        if vei >= self.params.vei_max:
            return

        vwap = self.vwap.lines.vwap[0]
        ema_bull = self.ema_f[0] > self.ema_s[0]

        # Daily trend gate
        if self._use_trend:
            trend_bull = close > self.ema_trend[0]
        else:
            trend_bull = None

        # ── SIGNAL A: Gap Momentum (proven v12 logic) ──────────────────────
        if (b >= self.params.entry_start and b <= self.params.entry_end and
            self._prior_close > 0):

            gap = (close - self._prior_close) / self._prior_close
            qty = self._qty_atr()
            tm = self.params.target_mult

            # LONG: gap up + above VWAP + EMA bullish
            if (gap >= self.params.gap_min and close > vwap and ema_bull and
                (trend_bull is None or trend_bull) and qty > 0):
                self.buy(size=qty)
                self._trail = close - atr * self.params.stop_mult
                self._target = close + atr * tm if tm > 0 else 0.
                self._entry = close
                self._dir = 1
                self._traded = True
                self._signal_type = 'GAP'
                return

            # SHORT: gap down + below VWAP + EMA bearish
            if (gap <= -self.params.gap_min and close < vwap and not ema_bull and
                (trend_bull is None or not trend_bull) and qty > 0):
                self.sell(size=qty)
                self._trail = close + atr * self.params.stop_mult
                self._target = close - atr * tm if tm > 0 else 0.
                self._entry = close
                self._dir = -1
                self._traded = True
                self._signal_type = 'GAP'
                return

        # ── SIGNAL B: IB Breakout Retracement ──────────────────────────────
        if (b >= self.params.ib_entry_start and b <= self.params.entry_end and
            self._ib_valid and self._ib_range > 0):

            retr_zone = self._ib_range * self.params.ib_retr_pct
            stop_dist = self._ib_range * self.params.ib_stop_pct
            tgt_dist = self._ib_range * self.params.ib_tgt_pct

            # LONG: broke above IB, retracted to near IB high, EMA bullish
            if (self._ib_broken_up and ema_bull and
                self._ib_high - retr_zone <= close <= self._ib_high + retr_zone * 0.3):
                qty = self._qty_risk(stop_dist)
                if qty > 0:
                    self.buy(size=qty)
                    self._trail = close - stop_dist
                    self._target = self._ib_high + tgt_dist
                    self._entry = close
                    self._dir = 1
                    self._traded = True
                    self._signal_type = 'IB'
                    return

            # SHORT: broke below IB, retracted to near IB low, EMA bearish
            if (self._ib_broken_down and not ema_bull and
                self._ib_low - retr_zone * 0.3 <= close <= self._ib_low + retr_zone):
                qty = self._qty_risk(stop_dist)
                if qty > 0:
                    self.sell(size=qty)
                    self._trail = close + stop_dist
                    self._target = self._ib_low - tgt_dist
                    self._entry = close
                    self._dir = -1
                    self._traded = True
                    self._signal_type = 'IB'
                    return
