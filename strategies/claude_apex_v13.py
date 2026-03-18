"""
ClaudeAPEX v13 — Multi-Signal Intraday (5m bars)
==================================================

TARGET: 5-6 trades per week on GLD 5m.

Three independent signal generators, all sharing the same
risk management, VEI regime gate, and position management.

SIGNAL 1 — IB Breakout Retracement (gold-specific):
  First hour (bars 0-11) defines Initial Balance (IB).
  After IB breakout, wait for retracement back inside IB.
  Enter 10% inside the IB boundary.
  Stop: 35% of IB range. Target: 30% of IB range above IB High.
  Source: TradeSwing backtested gold strategy, 70% WR.

SIGNAL 2 — VWAP 2SD Mean Reversion:
  When price touches VWAP -2SD band → long (oversold bounce).
  When price touches VWAP +2SD band → short (overbought rejection).
  Target: VWAP (the mean). Stop: beyond 3SD band.
  Best during first 2h and last hour.

SIGNAL 3 — Prior Day Value Area Rotation (80% Rule):
  If price opens outside prior day's value area and re-enters it,
  80% probability it traverses the full value area.
  Long: price opens below prior VAL, crosses back above → target POC/VAH.
  Short: price opens above prior VAH, crosses back below → target POC/VAL.

SHARED:
  VEI regime gate (ATR_short / ATR_long < vei_max)
  Max 1 position at a time
  EOD force close
  Risk: 2% per trade, 5x leverage cap
"""

import backtrader as bt
import math


class VWAP_SD(bt.Indicator):
    """Daily VWAP with standard deviation bands."""
    lines = ('vwap', 'upper1', 'lower1', 'upper2', 'lower2', 'upper3', 'lower3')
    plotinfo = dict(subplot=False)

    def __init__(self):
        self._cpv = 0.
        self._cv = 0.
        self._cpv2 = 0.  # sum of tp^2 * vol for variance calc
        self._prev = None

    def next(self):
        today = self.data.datetime.date(0)
        if today != self._prev:
            self._cpv = 0.
            self._cv = 0.
            self._cpv2 = 0.
            self._prev = today

        tp = (self.data.high[0] + self.data.low[0] + self.data.close[0]) / 3.
        vol = max(self.data.volume[0], 1)
        self._cpv += tp * vol
        self._cv += vol
        self._cpv2 += tp * tp * vol

        vwap = self._cpv / self._cv
        # Variance = E[X^2] - E[X]^2
        variance = max(self._cpv2 / self._cv - vwap * vwap, 0)
        sd = math.sqrt(variance) if variance > 0 else 0.001

        self.lines.vwap[0] = vwap
        self.lines.upper1[0] = vwap + sd
        self.lines.lower1[0] = vwap - sd
        self.lines.upper2[0] = vwap + 2 * sd
        self.lines.lower2[0] = vwap - 2 * sd
        self.lines.upper3[0] = vwap + 3 * sd
        self.lines.lower3[0] = vwap - 3 * sd


class ClaudeAPEX_v13(bt.Strategy):

    params = (
        # VEI
        ('atr_short',   10),
        ('atr_long',    50),
        ('vei_max',     1.08),
        # Trend
        ('ema_fast',    9),
        ('ema_slow',    21),
        ('trend_ema',   0),       # 0 = disabled
        # IB (Initial Balance)
        ('ib_bars',     12),      # 12 × 5min = 1 hour
        ('ib_retr_pct', 0.10),    # Enter 10% inside IB boundary
        ('ib_stop_pct', 0.35),    # Stop at 35% of IB range
        ('ib_tgt_pct',  0.30),    # Target 30% of IB range above breakout
        ('ib_min_range', 0.004),  # Min IB range as % of price (0.4%)
        ('ib_max_range', 0.020),  # Max IB range as % of price (2.0%)
        # VWAP
        ('vwap_timeout', 18),     # Exit if no revert in 18 bars (90 min)
        # Value Area
        ('va_confirm_bars', 6),   # Price must hold inside VA for 6 bars (30 min)
        # Timing
        ('entry_start', 12),      # After IB completes (bar 12 = 10:30 AM)
        ('eod_bar',     72),      # 3:30 PM force close
        # Risk
        ('atr_period',  14),
        ('risk_pct',    0.02),
        ('leverage',    5.0),
        ('real_cash',   100_000.0),
        ('trade_start', None),
        ('bars_per_day', 78),
    )

    def __init__(self):
        self.vwap_sd = VWAP_SD(self.data)
        self.atr     = bt.indicators.ATR(self.data, period=self.params.atr_period)
        self.atr_s   = bt.indicators.ATR(self.data, period=self.params.atr_short)
        self.atr_l   = bt.indicators.ATR(self.data, period=self.params.atr_long)
        self.ema_f   = bt.indicators.EMA(self.data.close, period=self.params.ema_fast)
        self.ema_s   = bt.indicators.EMA(self.data.close, period=self.params.ema_slow)

        if self.params.trend_ema > 0:
            self.ema_trend = bt.indicators.EMA(
                self.data.close, period=self.params.trend_ema)

        # Day state
        self._prev_date = None
        self._bar = 0
        self._traded = False
        self._eod = False

        # IB tracking
        self._ib_high = 0.
        self._ib_low = 0.
        self._ib_range = 0.
        self._ib_broken_up = False
        self._ib_broken_down = False

        # Prior day Value Area
        self._prior_vah = 0.
        self._prior_val = 0.
        self._prior_poc = 0.
        # Current day volume profile for computing VA
        self._day_prices = []   # (typical_price, volume) tuples
        self._va_entered = False  # Price re-entered VA from outside
        self._va_confirm_count = 0
        self._opened_above_vah = False
        self._opened_below_val = False

        # Position state
        self._dir = 0
        self._stoplvl = 0.
        self._target = 0.
        self._entry_bar = 0
        self._signal_type = ''
        self._timeout = 0

    def _qty(self, risk_per_share):
        close = self.data.close[0]
        if risk_per_share <= 0 or close <= 0:
            return 0
        risk_shares = int(self.params.real_cash * self.params.risk_pct / risk_per_share)
        lev_shares = int(self.params.real_cash * self.params.leverage / close)
        return min(risk_shares, lev_shares)

    def _vei(self):
        al = self.atr_l[0]
        return self.atr_s[0] / al if al > 0 else 1.0

    def _compute_value_area(self):
        """Compute POC, VAH, VAL from accumulated day prices."""
        if not self._day_prices:
            return 0., 0., 0.

        # Build simple histogram: bin prices, weight by volume
        prices = self._day_prices
        if len(prices) < 5:
            return 0., 0., 0.

        # Get price range and create bins
        all_tp = [p[0] for p in prices]
        all_vol = [p[1] for p in prices]
        lo, hi = min(all_tp), max(all_tp)
        if hi - lo < 0.01:
            mid = (hi + lo) / 2
            return mid, mid, mid

        n_bins = 30
        bin_size = (hi - lo) / n_bins
        bins = [0.0] * n_bins

        for tp, vol in prices:
            idx = min(int((tp - lo) / bin_size), n_bins - 1)
            bins[idx] += vol

        # POC = bin with most volume
        poc_idx = bins.index(max(bins))
        poc = lo + (poc_idx + 0.5) * bin_size

        # Value Area = 70% of total volume, expanding from POC
        total_vol = sum(bins)
        va_vol = 0.0
        va_lo_idx = poc_idx
        va_hi_idx = poc_idx
        va_vol += bins[poc_idx]

        while va_vol < total_vol * 0.70:
            up_vol = bins[va_hi_idx + 1] if va_hi_idx + 1 < n_bins else 0
            dn_vol = bins[va_lo_idx - 1] if va_lo_idx - 1 >= 0 else 0
            if up_vol == 0 and dn_vol == 0:
                break
            if up_vol >= dn_vol:
                va_hi_idx += 1
                va_vol += up_vol
            else:
                va_lo_idx -= 1
                va_vol += dn_vol

        vah = lo + (va_hi_idx + 1) * bin_size
        val_ = lo + va_lo_idx * bin_size

        return poc, vah, val_

    def next(self):
        if self.params.trade_start and self.data.datetime.date(0) < self.params.trade_start:
            return

        warm = max(self.params.atr_long, self.params.ema_slow,
                   self.params.atr_period) + 5
        if self.params.trend_ema > 0:
            warm = max(warm, self.params.trend_ema)
        if len(self.data) < warm:
            return

        today = self.data.datetime.date(0)
        close = self.data.close[0]
        high = self.data.high[0]
        low = self.data.low[0]

        # ── New day ────────────────────────────────────────────────────────
        if today != self._prev_date:
            # Close any open position
            if self.position:
                self.close()
                self._dir = 0; self._stoplvl = 0.; self._target = 0.

            # Compute prior day's value area before resetting
            if self._day_prices:
                poc, vah, val_ = self._compute_value_area()
                if poc > 0:
                    self._prior_poc = poc
                    self._prior_vah = vah
                    self._prior_val = val_

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

            # Reset VA tracking
            self._day_prices = []
            self._va_entered = False
            self._va_confirm_count = 0

            # Check if opened outside prior VA
            self._opened_above_vah = (close > self._prior_vah > 0)
            self._opened_below_val = (close < self._prior_val > 0)

            self._signal_type = ''
            self._timeout = 0

            # Record bar 0 in volume profile
            tp = (high + low + close) / 3.
            vol = max(self.data.volume[0], 1)
            self._day_prices.append((tp, vol))

            self._bar += 1
            return

        self._bar += 1
        b = self._bar

        # Accumulate volume profile data
        tp = (high + low + close) / 3.
        vol = max(self.data.volume[0], 1)
        self._day_prices.append((tp, vol))

        # Build IB during first hour
        if b <= self.params.ib_bars:
            if high > self._ib_high:
                self._ib_high = high
            if low < self._ib_low:
                self._ib_low = low
            if b == self.params.ib_bars:
                self._ib_range = self._ib_high - self._ib_low
            return

        # Track IB breakouts
        if self._ib_range > 0:
            if close > self._ib_high and not self._ib_broken_up:
                self._ib_broken_up = True
            if close < self._ib_low and not self._ib_broken_down:
                self._ib_broken_down = True

        # Track VA re-entry
        if self._prior_vah > 0 and self._prior_val > 0:
            inside_va = self._prior_val <= close <= self._prior_vah
            if inside_va and (self._opened_above_vah or self._opened_below_val):
                if not self._va_entered:
                    self._va_entered = True
                    self._va_confirm_count = 0
                self._va_confirm_count += 1
            elif not inside_va:
                self._va_confirm_count = 0

        # ── EOD force-close ─────────────────────────────────────────────────
        if b >= self.params.eod_bar:
            if self.position and not self._eod:
                self.close()
                self._eod = True
                self._dir = 0; self._stoplvl = 0.; self._target = 0.
            return

        # ── Manage open position ────────────────────────────────────────────
        if self.position:
            # Timeout for VWAP signals
            if self._signal_type == 'VWAP' and self._timeout > 0:
                if b >= self._timeout:
                    self.close()
                    self._dir = 0; self._stoplvl = 0.; self._target = 0.
                    return

            if self._dir == 1:
                if close <= self._stoplvl or close >= self._target:
                    self.close(); self._dir = 0
            elif self._dir == -1:
                if close >= self._stoplvl or close <= self._target:
                    self.close(); self._dir = 0
            return

        # ── Entry scan ──────────────────────────────────────────────────────
        if self._traded or b < self.params.entry_start:
            return

        # VEI gate
        if self._vei() >= self.params.vei_max:
            return

        vwap = self.vwap_sd.lines.vwap[0]
        ema_bull = self.ema_f[0] > self.ema_s[0]

        # ── SIGNAL 1: IB Breakout Retracement ──────────────────────────────
        if self._ib_range > 0:
            ib_pct = self._ib_range / close if close > 0 else 0
            if self.params.ib_min_range <= ib_pct <= self.params.ib_max_range:
                retr_dist = self._ib_range * self.params.ib_retr_pct

                # Long: broke above IB, now retracted back near IB high
                if (self._ib_broken_up and
                    self._ib_high - retr_dist <= close <= self._ib_high + retr_dist * 0.5 and
                    ema_bull):
                    risk = self._ib_range * self.params.ib_stop_pct
                    target_dist = self._ib_range * self.params.ib_tgt_pct
                    qty = self._qty(risk)
                    if qty > 0:
                        self.buy(size=qty)
                        self._stoplvl = close - risk
                        self._target = self._ib_high + target_dist
                        self._dir = 1
                        self._traded = True
                        self._signal_type = 'IB'
                        self._entry_bar = b
                        return

                # Short: broke below IB, now retracted back near IB low
                if (self._ib_broken_down and
                    self._ib_low - retr_dist * 0.5 <= close <= self._ib_low + retr_dist and
                    not ema_bull):
                    risk = self._ib_range * self.params.ib_stop_pct
                    target_dist = self._ib_range * self.params.ib_tgt_pct
                    qty = self._qty(risk)
                    if qty > 0:
                        self.sell(size=qty)
                        self._stoplvl = close + risk
                        self._target = self._ib_low - target_dist
                        self._dir = -1
                        self._traded = True
                        self._signal_type = 'IB'
                        self._entry_bar = b
                        return

        # ── SIGNAL 2: VWAP 2SD Mean Reversion ──────────────────────────────
        lower2 = self.vwap_sd.lines.lower2[0]
        upper2 = self.vwap_sd.lines.upper2[0]
        lower3 = self.vwap_sd.lines.lower3[0]
        upper3 = self.vwap_sd.lines.upper3[0]

        # Long: price at or below -2SD
        if close <= lower2 and close > lower3:
            risk = close - lower3
            if risk > 0:
                qty = self._qty(risk)
                if qty > 0:
                    self.buy(size=qty)
                    self._stoplvl = lower3
                    self._target = vwap  # Target = VWAP mean
                    self._dir = 1
                    self._traded = True
                    self._signal_type = 'VWAP'
                    self._entry_bar = b
                    self._timeout = b + self.params.vwap_timeout
                    return

        # Short: price at or above +2SD
        if close >= upper2 and close < upper3:
            risk = upper3 - close
            if risk > 0:
                qty = self._qty(risk)
                if qty > 0:
                    self.sell(size=qty)
                    self._stoplvl = upper3
                    self._target = vwap  # Target = VWAP mean
                    self._dir = -1
                    self._traded = True
                    self._signal_type = 'VWAP'
                    self._entry_bar = b
                    self._timeout = b + self.params.vwap_timeout
                    return

        # ── SIGNAL 3: Prior Day Value Area Rotation (80% Rule) ─────────────
        if (self._prior_poc > 0 and self._va_entered and
            self._va_confirm_count >= self.params.va_confirm_bars):

            # Long: opened below VAL, re-entered VA → target POC
            if self._opened_below_val and close > self._prior_val:
                risk = close - self._prior_val
                atr = self.atr[0]
                if 0 < risk < atr * 2:
                    qty = self._qty(risk)
                    if qty > 0:
                        self.buy(size=qty)
                        self._stoplvl = self._prior_val - risk * 0.2
                        self._target = self._prior_poc
                        self._dir = 1
                        self._traded = True
                        self._signal_type = 'VA80'
                        self._entry_bar = b
                        return

            # Short: opened above VAH, re-entered VA → target POC
            if self._opened_above_vah and close < self._prior_vah:
                risk = self._prior_vah - close
                atr = self.atr[0]
                if 0 < risk < atr * 2:
                    qty = self._qty(risk)
                    if qty > 0:
                        self.sell(size=qty)
                        self._stoplvl = self._prior_vah + risk * 0.2
                        self._target = self._prior_poc
                        self._dir = -1
                        self._traded = True
                        self._signal_type = 'VA80'
                        self._entry_bar = b
                        return
