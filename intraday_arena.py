"""
intraday_arena.py — ClaudeAPEX v2 vs AG Strategies
===================================================
APEX v2: Intraday ORB entry timing + overnight swing hold (hourly bars)
AG     : Daily EMA trend riders (daily bars)
"""

import datetime, warnings, sys, io
warnings.filterwarnings('ignore')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import backtrader as bt
import yfinance as yf
import pandas as pd

from strategies.claude_apex     import ClaudeAPEX
from strategies.gld_godmode     import GLDGodMode
from strategies.universal_godmode import UniversalGodMode

CASH   = 100_000.0
TICKER = 'GLD'

MONTHS = [
    ('2025-03-01', '2025-03-31'),
    ('2025-04-01', '2025-04-30'),
    ('2025-05-01', '2025-05-31'),
    ('2025-06-01', '2025-06-30'),
    ('2025-07-01', '2025-07-31'),
    ('2025-08-01', '2025-08-31'),
    ('2025-09-01', '2025-09-30'),
    ('2025-10-01', '2025-10-31'),
    ('2025-11-01', '2025-11-30'),
    ('2025-12-01', '2025-12-31'),
    ('2026-01-01', '2026-01-31'),
    ('2026-02-01', '2026-02-28'),
]


class TradeLogger(bt.Analyzer):
    def start(self):
        self.trades = []

    def notify_trade(self, trade):
        if trade.isclosed:
            # trade.history[-1].status == 'Closed': last bar has exit info
            entry_px = round(trade.price, 2)
            size_abs = abs(trade.historyon(0).event.size) if trade.history else abs(trade.size)
            # pnlcomm = net P&L after commission
            pnl_net  = round(trade.pnlcomm, 2)
            direction = 'LONG' if trade.long else 'SHORT'
            self.trades.append({
                'entry_date': bt.num2date(trade.dtopen).strftime('%Y-%m-%d'),
                'exit_date':  bt.num2date(trade.dtclose).strftime('%Y-%m-%d'),
                'direction':  direction,
                'size':       int(abs(trade.size) + abs(trade.history[-1].event.size)
                                  if trade.history else abs(trade.size)),
                'entry_px':   entry_px,
                'pnl':        pnl_net,
                'pnl_pct':    round(pnl_net / CASH * 100, 3),
            })

    def get_analysis(self):
        return self.trades


def run_apex(start_str, end_str, verbose=False):
    warmup_start = (pd.Timestamp(start_str) - pd.DateOffset(months=3)).strftime('%Y-%m-%d')
    trade_start  = datetime.date.fromisoformat(start_str)

    df = yf.download(TICKER, start=warmup_start, end=end_str,
                     interval='1h', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    df.dropna(inplace=True)

    if df.empty or len(df) < 80:
        return 0.0, 0, []

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(CASH * 10.0)
    cerebro.broker.set_shortcash(False)
    cerebro.broker.setcommission(commission=0.001)   # 0.1% intraday ETF

    cerebro.adddata(bt.feeds.PandasData(dataname=df))
    cerebro.addstrategy(ClaudeAPEX,
                        trade_start=trade_start,
                        leverage=5.0,
                        real_cash=CASH)
    cerebro.addanalyzer(TradeLogger,      _name='tl')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='ta')

    results = cerebro.run(stdstats=False)
    strat   = results[0]
    final   = cerebro.broker.getvalue() - CASH * 9.0
    roi     = (final - CASH) / CASH * 100
    trades  = strat.analyzers.tl.get_analysis()
    return roi, len(trades), trades


def run_daily(strat_cls, start_str, end_str):
    warmup_start = (pd.Timestamp(start_str) - pd.DateOffset(months=14)).strftime('%Y-%m-%d')
    trade_start  = datetime.date.fromisoformat(start_str)

    df = yf.download(TICKER, start=warmup_start, end=end_str,
                     interval='1d', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    df.dropna(inplace=True)

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(CASH * 10.0)
    cerebro.broker.set_shortcash(False)
    cerebro.broker.setcommission(commission=0.005)

    cerebro.adddata(bt.feeds.PandasData(dataname=df))
    cerebro.addstrategy(strat_cls, trade_start=trade_start)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='ta')

    results = cerebro.run(stdstats=False)
    final   = cerebro.broker.getvalue() - CASH * 9.0
    roi     = (final - CASH) / CASH * 100
    ta      = results[0].analyzers.ta.get_analysis()
    n       = ta.get('total', {}).get('closed', 0)
    return roi, n


# ══════════════════════════════════════════════════════════════════════════════
print()
print("=" * 95)
print("  GLD ARENA  |  ClaudeAPEX v2 (1h ORB swing) vs GLDGodMode vs UniversalGodMode")
print("  APEXv2: intraday entry timing + overnight hold | Commission 0.1%")
print("  AG strategies: daily EMA trend + hold all month | Commission 0.5%")
print("=" * 95)

all_apex, all_gm, all_ugm = [], [], []
all_trades = []

for i, (start, end) in enumerate(MONTHS):
    label = pd.Timestamp(start).strftime('%Y-%m')
    print(f"\n  [{i+1:02d}/12] {label}", flush=True)

    aroi, an, atrades = run_apex(start, end)
    groi, gn          = run_daily(GLDGodMode,      start, end)
    uroi, un          = run_daily(UniversalGodMode, start, end)

    all_apex.append((label, aroi, an))
    all_gm.append((label, groi, gn))
    all_ugm.append((label, uroi, un))

    if atrades:
        print(f"  {'Entry':>12} {'Exit':>12} {'Dir':>6} {'Entry$':>8} {'P&L':>10} {'ROI%':>7}")
        print(f"  {'-'*68}")
        for t in atrades:
            pnl_sign = '+' if t['pnl'] >= 0 else ''
            print(f"  {t['entry_date']:>12} {t['exit_date']:>12} {t['direction']:>6} "
                  f"{t['entry_px']:>8.2f} {pnl_sign}{t['pnl']:>9.2f} {pnl_sign}{t['pnl_pct']:>6.3f}%")
        all_trades.extend([(label, t) for t in atrades])
    else:
        print(f"  (no closed trades this month)")

    winner = 'APEX' if aroi > groi + 0.05 else ('GodMode' if groi > aroi + 0.05 else 'Tie')
    print(f"\n  APEX {aroi:+.2f}% ({an}t)  |  GodMode {groi:+.2f}%  |  Universal {uroi:+.2f}%  -> {winner}")

# ── SCORECARD ────────────────────────────────────────────────────────────────
print()
print("=" * 95)
print(f"  {'Month':<10} {'APEX v2':>10} {'Trd':>4} | {'GodMode':>10} | {'Universal':>10}  Winner")
print("-" * 95)

apex_tot = gm_tot = ugm_tot = 0
apex_w = gm_w = ties = 0

for (lbl, ar, an), (_, gr, _), (_, ur, _) in zip(all_apex, all_gm, all_ugm):
    apex_tot += ar
    gm_tot   += gr
    ugm_tot  += ur
    if ar > gr + 0.05:   apex_w += 1; w = 'APEX'
    elif gr > ar + 0.05: gm_w   += 1; w = 'GodMode'
    else:                ties   += 1; w = 'Tie'
    print(f"  {lbl:<10} {ar:>+9.2f}% {an:>4} | {gr:>+9.2f}% | {ur:>+9.2f}%  {w}")

print("-" * 95)
print(f"  {'TOTAL':<10} {apex_tot:>+9.2f}%      | {gm_tot:>+9.2f}% | {ugm_tot:>+9.2f}%")
print()
print(f"  ClaudeAPEX v2 : {apex_w}W - {gm_w}L - {ties}T vs GodMode | {apex_tot:+.2f}% vs {gm_tot:+.2f}%")
print()

# -- All APEX trades summary
if all_trades:
    total_pnl = sum(t['pnl'] for _, t in all_trades)
    wins = sum(1 for _, t in all_trades if t['pnl'] > 0)
    total = len(all_trades)
    print(f"  APEX trade summary: {total} total trades | {wins}W/{total-wins}L "
          f"| Win rate {wins/total*100:.1f}% | Total P&L ${total_pnl:+,.0f}")

if apex_tot > gm_tot:
    print(f"\n  >>> ClaudeAPEX v2 BEATS GLDGodMode by {apex_tot - gm_tot:.2f}% <<<")
else:
    print(f"\n  >>> Gap to close: {gm_tot - apex_tot:.2f}% — strategy needs tuning <<<")
print("=" * 95)
