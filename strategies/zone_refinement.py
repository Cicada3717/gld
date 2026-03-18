"""
ZoneRefinement — Supply & Demand Zone Refinement Strategy
==========================================================

Implements the "zone refinement" / sniper-entry technique:

1. Identify HTF (4H) supply and demand zones (candle that started a strong move).
2. Confirm market context: a break of structure (BOS) via EMA slope direction.
3. When price returns to the HTF zone, use the pre-refined LTF (1H) zone inside it.
4. Entry: price touches the refined zone edge but stays WITHIN the zone (not through it).
5. Stop: just beyond the refined zone; Target: prior swing high/low for improved R:R.

Two Steps Down Rule enforced externally: zones are pre-computed on 4H/1H, strategy
runs on 1H bars. (4H → 1H → 30M if needed; never more than two steps below HTF.)

Zone dict schema (pre-computed and passed in as params.zones):
  {
    'type':           'demand' | 'supply',
    'formed_at':      datetime,          # timestamp of HTF initiating candle
    'htf_top':        float,             # HTF zone upper bound (High of initiating candle)
    'htf_bottom':     float,             # HTF zone lower bound (Low  of initiating candle)
    'refined_top':    float,             # LTF refined zone upper bound
    'refined_bottom': float,             # LTF refined zone lower bound
    'consumed':       bool,              # True after first trade taken
  }
"""

import backtrader as bt


class ZoneRefinement(bt.Strategy):

    params = (
        # Pre-computed zones (list of dicts from zone_refinement_backtest.py)
        ('zones', []),
        # Stop buffer beyond refined zone edge
        ('stop_buffer', 0.001),      # 0.1% beyond zone edge
        # Break of structure filter
        ('bos_ema', 21),             # EMA period; rising = bullish BOS, falling = bearish
        ('bos_slope_bars', 3),       # Compare EMA[0] vs EMA[-N] for slope
        # Target: look back this many bars for prior swing high/low
        # Skips the nearest `target_skip` bars (the current retest pullback)
        ('target_lookback', 60),
        ('target_skip', 5),
        # Minimum R:R to take a trade
        ('min_rr', 3.0),
        # Risk sizing
        ('risk_pct', 0.02),
        ('leverage', 5.0),
        ('real_cash', 100_000.0),
        # Optional: ignore bars before this date (warmup)
        ('trade_start', None),
    )

    def __init__(self):
        self._zones       = [dict(z) for z in self.params.zones]  # mutable copy
        self._dir         = 0       # 1 = long, -1 = short, 0 = flat
        self._stoplvl     = 0.
        self._target      = 0.
        self._active_zone = None

        # Entry snapshot stored in next() at order-placement time;
        # read in notify_trade for the log. Avoids notify_order complications.
        self._pending     = None

        self.ema = bt.indicators.EMA(self.data.close, period=self.params.bos_ema)

        # Accessible after cerebro.run()
        self.trade_log = []

    # ── Sizing ────────────────────────────────────────────────────────────────

    def _qty(self, risk_per_share):
        close = self.data.close[0]
        if risk_per_share <= 0 or close <= 0:
            return 0
        risk_shares = int(self.params.real_cash * self.params.risk_pct / risk_per_share)
        lev_shares  = int(self.params.real_cash * self.params.leverage / close)
        return min(risk_shares, lev_shares)

    # ── Break-of-structure filters ────────────────────────────────────────────

    def _bos_bullish(self):
        """EMA is rising — price structure trending up (OK to buy demand)."""
        n = self.params.bos_slope_bars
        if len(self.data) < n + self.params.bos_ema:
            return False
        return self.ema[0] > self.ema[-n]

    def _bos_bearish(self):
        """EMA is falling — price structure trending down (OK to sell supply)."""
        n = self.params.bos_slope_bars
        if len(self.data) < n + self.params.bos_ema:
            return False
        return self.ema[0] < self.ema[-n]

    # ── Swing target helpers ──────────────────────────────────────────────────

    def _prior_high(self):
        """Max high from [target_skip .. target_lookback] bars ago (skips the retest pullback)."""
        skip = self.params.target_skip
        n    = min(self.params.target_lookback, len(self.data) - 1)
        if n <= skip:
            return max(self.data.high[-i] for i in range(1, max(n, 1) + 1))
        return max(self.data.high[-i] for i in range(skip, n + 1))

    def _prior_low(self):
        """Min low from [target_skip .. target_lookback] bars ago."""
        skip = self.params.target_skip
        n    = min(self.params.target_lookback, len(self.data) - 1)
        if n <= skip:
            return min(self.data.low[-i] for i in range(1, max(n, 1) + 1))
        return min(self.data.low[-i] for i in range(skip, n + 1))

    # ── Trade logging ─────────────────────────────────────────────────────────

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        if not self._pending:
            return
        p        = self._pending
        entry_px = trade.price                          # actual fill (backtrader = avg entry)
        size     = p['size']
        # Derive exit price from gross P&L:  pnl = (exit-entry)*size (long) or (entry-exit)*size (short)
        exit_px  = (entry_px + trade.pnl / size) if p['direction'] == 'LONG' \
                   else (entry_px - trade.pnl / size)
        pnl_pts  = (exit_px - entry_px) if p['direction'] == 'LONG' \
                   else (entry_px - exit_px)
        risk     = abs(entry_px - p['stop'])
        rr       = pnl_pts / risk if risk > 0 else 0.
        self.trade_log.append({
            'entry_date': p['entry_date'],
            'exit_date':  self.data.datetime.datetime(0),
            'direction':  p['direction'],
            'zone_type':  p['zone_type'],
            'size':       size,
            'entry_px':   round(entry_px,         3),
            'stop':       round(p['stop'],         3),
            'target':     round(p['target'],       3),
            'exit_px':    round(exit_px,           3),
            'pnl_pts':    round(pnl_pts,           3),
            'pnl_$':      round(trade.pnlcomm,     2),
            'rr':         round(rr,                2),
            'result':     'WIN' if trade.pnlcomm > 0 else 'LOSS',
        })
        self._pending = None

    # ── Main logic ────────────────────────────────────────────────────────────

    def next(self):
        if self.params.trade_start and self.data.datetime.date(0) < self.params.trade_start:
            return

        warm = self.params.bos_ema + self.params.bos_slope_bars + 5
        if len(self.data) < warm:
            return

        close = self.data.close[0]
        high  = self.data.high[0]
        low   = self.data.low[0]
        ts    = self.data.datetime.datetime(0)

        # ── Manage open position ──────────────────────────────────────────────
        if self.position:
            if self._dir == 1:
                if close <= self._stoplvl or close >= self._target:
                    self.close()
                    self._dir = 0
                    if self._active_zone:
                        self._active_zone['consumed'] = True
                        self._active_zone = None
            elif self._dir == -1:
                if close >= self._stoplvl or close <= self._target:
                    self.close()
                    self._dir = 0
                    if self._active_zone:
                        self._active_zone['consumed'] = True
                        self._active_zone = None
            return

        # ── Zone scan ─────────────────────────────────────────────────────────
        for zone in self._zones:
            if zone.get('consumed'):
                continue
            # Zone must have formed before this bar (no look-ahead)
            if zone['formed_at'] >= ts:
                continue

            ztop = zone['htf_top']
            zbot = zone['htf_bottom']
            rtop = zone['refined_top']
            rbot = zone['refined_bottom']
            buf  = self.params.stop_buffer

            if zone['type'] == 'demand':
                # Price must be inside the HTF demand zone
                if not (zbot <= close <= ztop):
                    continue
                # Bullish BOS required
                if not self._bos_bullish():
                    continue
                # Entry: price has touched the refined zone (low <= rtop)
                # but close is still ABOVE refined bottom (not fallen through zone)
                if low > rtop:
                    continue  # hasn't reached the refined zone yet
                if close < rbot:
                    continue  # blown through the refined zone — missed entry
                # Stop just below refined zone bottom; risk = close - stop (positive)
                stop = rbot * (1 - buf)
                risk = close - stop
                if risk <= 0:
                    continue
                # Target: prior swing high (skip recent pullback bars)
                target = self._prior_high()
                if target <= close:
                    continue
                rr = (target - close) / risk
                if rr < self.params.min_rr:
                    continue
                qty = self._qty(risk)
                if qty <= 0:
                    continue
                self.buy(size=qty)
                self._stoplvl     = stop
                self._target      = target
                self._dir         = 1
                self._active_zone = zone
                # Snapshot for trade log (COC fill = this bar's close)
                self._pending = {
                    'entry_date': ts,
                    'direction':  'LONG',
                    'zone_type':  zone['type'],
                    'size':       qty,
                    'entry_px':   close,
                    'stop':       stop,
                    'target':     target,
                }
                break

            elif zone['type'] == 'supply':
                # Price must be inside the HTF supply zone
                if not (zbot <= close <= ztop):
                    continue
                # Bearish BOS required
                if not self._bos_bearish():
                    continue
                # Entry: price has touched refined zone bottom (high >= rbot)
                # but close still BELOW refined top (not blown through zone)
                if high < rbot:
                    continue
                if close > rtop:
                    continue  # blown through — missed entry
                stop = rtop * (1 + buf)
                risk = stop - close
                if risk <= 0:
                    continue
                target = self._prior_low()
                if target >= close:
                    continue
                rr = (close - target) / risk
                if rr < self.params.min_rr:
                    continue
                qty = self._qty(risk)
                if qty <= 0:
                    continue
                self.sell(size=qty)
                self._stoplvl     = stop
                self._target      = target
                self._dir         = -1
                self._active_zone = zone
                self._pending = {
                    'entry_date': ts,
                    'direction':  'SHORT',
                    'zone_type':  zone['type'],
                    'size':       qty,
                    'entry_px':   close,
                    'stop':       stop,
                    'target':     target,
                }
                break
