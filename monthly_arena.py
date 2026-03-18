"""
monthly_arena.py — 12-Month Monthly Battle: Claude vs Antigravity on GLD.

Rules:
  - Each calendar month is a standalone competition
  - Capital resets to $100,000 at the start of every month
  - Past 12 months: 2025-03 through 2026-02
  - Max leverage: 5x
  - Asset: GLD

Usage:
    python monthly_arena.py
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import backtrader as bt
import yfinance as yf
import pandas as pd
import datetime
import calendar

from strategies.claude_gold_omega import ClaudeGoldOmega
from strategies.gld_godmode import GLDGodMode
from strategies.ag_omega import AntigravityOmega

STARTING_CASH = 100_000.0
COMMISSION    = 0.005   # 0.5% per trade
WARMUP_MONTHS = 3       # 3 months of warmup for indicators
LEVERAGE      = 5.0
CASH_PADDING  = STARTING_CASH * 10.0  # Virtual bank padding for leverage


def run_month(strategy_cls, strategy_kwargs, df):
    """Run a single month backtest using pre-loaded data (shared between strategies).
    Returns (final_value, roi, max_dd, trades).
    """
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(CASH_PADDING)
    cerebro.broker.setcommission(commission=COMMISSION)
    cerebro.broker.set_shortcash(False)
    cerebro.broker.set_coc(True)
    cerebro.addsizer(bt.sizers.PercentSizer, percents=90)

    # IMPORTANT: Use .copy() so each strategy gets a fresh DataFrame
    cerebro.adddata(bt.feeds.PandasData(dataname=df.copy()))
    cerebro.addstrategy(strategy_cls, **strategy_kwargs)

    cerebro.addanalyzer(bt.analyzers.DrawDown,    _name='dd')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    results = cerebro.run()
    strat = results[0]

    raw_value  = cerebro.broker.getvalue()
    final_val  = raw_value - (STARTING_CASH * 9.0)   # Remove virtual bank padding
    roi        = (final_val - STARTING_CASH) / STARTING_CASH * 100
    max_dd     = strat.analyzers.dd.get_analysis().get('max', {}).get('drawdown', 0)
    ta         = strat.analyzers.trades.get_analysis()
    trades     = ta.get('total', {}).get('closed', 0) if isinstance(ta, dict) else 0

    return round(final_val, 2), round(roi, 2), round(max_dd, 2), trades


def main():
    # ── Generate 12 months: 2025-03 → 2026-02 ───────────────────────────────
    months = []
    y, m = 2025, 3
    for _ in range(12):
        last_day = calendar.monthrange(y, m)[1]
        months.append((
            f'{y}-{m:02d}-01',
            f'{y}-{m:02d}-{last_day}',
            f'{y}-{m:02d}'
        ))
        m += 1
        if m > 12:
            m = 1
            y += 1

    trade_start_dates = [datetime.date.fromisoformat(s) for s, _, _ in months]

    claude_kwargs = lambda ts: dict(trade_start=ts, leverage=LEVERAGE, real_cash=STARTING_CASH)
    ag_kwargs     = lambda ts: dict(trade_start=ts, leverage=LEVERAGE, real_cash=STARTING_CASH)

    print("=" * 70)
    print("  12-MONTH MONTHLY ARENA: Claude (Omega) vs Antigravity on GLD")
    print("=" * 70)
    print(f"  {'Month':<10} {'Claude ROI':>11} {'AG ROI':>10} {'Winner':<12} {'C-DD':>7} {'AG-DD':>7}")
    print("-" * 70)

    claude_rois, ag_rois = [], []
    claude_dds, ag_dds   = [], []
    claude_wins = ag_wins = ties = 0
    labels = []

    for (start, end, label), ts in zip(months, trade_start_dates):
        # ── Download data ONCE and share between both strategies ─────────────
        warmup_start = (
            pd.Timestamp(start) - pd.DateOffset(months=WARMUP_MONTHS)
        ).strftime('%Y-%m-%d')
        df = yf.download('GLD', start=warmup_start, end=end,
                         interval='1d', progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        if df.empty:
            print(f"  {label:<10} {'N/A':>11} {'N/A':>10}")
            continue

        c = run_month(ClaudeGoldOmega,  claude_kwargs(ts), df)
        a = run_month(AntigravityOmega, ag_kwargs(ts),     df)

        if c is None or a is None:
            print(f"  {label:<10} {'N/A':>11} {'N/A':>10}")
            continue

        c_val, c_roi, c_dd, c_t = c
        a_val, a_roi, a_dd, a_t = a

        if c_roi > a_roi:
            winner = '[C] Claude'
            claude_wins += 1
        elif a_roi > c_roi:
            winner = '[A] AG'
            ag_wins += 1
        else:
            winner = 'Tie'
            ties += 1

        print(f"  {label:<10} {c_roi:>+10.2f}% {a_roi:>+9.2f}% {winner:<12} {c_dd:>6.1f}% {a_dd:>6.1f}%")

        claude_rois.append(c_roi)
        ag_rois.append(a_roi)
        claude_dds.append(c_dd)
        ag_dds.append(a_dd)
        labels.append(label)

    print("-" * 70)
    print(f"  {'TOTAL':<10} {sum(claude_rois):>+10.2f}% {sum(ag_rois):>+9.2f}%")
    print(f"  Months won -- Claude: {claude_wins} | Antigravity: {ag_wins} | Ties: {ties}")
    print("=" * 70)

    # ── Visualization ────────────────────────────────────────────────────────
    fig, axes = plt.subplots(2, 1, figsize=(16, 11))
    fig.suptitle('12-Month Monthly Arena: Claude (Omega) vs Antigravity (Omega) on GLD\n(2025-03 -> 2026-02, $100K reset each month, 5x leverage)',
                 fontsize=14, fontweight='bold')

    x = range(len(labels))
    w = 0.38

    # ── Top: Monthly ROI bars ────────────────────────────────────────────────
    ax = axes[0]
    bc = ax.bar([i - w/2 for i in x], claude_rois, width=w,
                color='#FF8C00', label='Claude (Omega Bidir 5x)', edgecolor='black', linewidth=0.8)
    ba = ax.bar([i + w/2 for i in x], ag_rois,    width=w,
                color='#1E90FF', label='Antigravity (Omega 5x)', edgecolor='black', linewidth=0.8)

    for bar, val in zip(list(bc) + list(ba), claude_rois + ag_rois):
        if abs(val) > 1:
            ax.text(bar.get_x() + bar.get_width()/2,
                    bar.get_height() + (0.5 if val >= 0 else -2.5),
                    f'{val:+.0f}%', ha='center', va='bottom', fontsize=7, fontweight='bold')

    ax.axhline(0, color='black', linewidth=0.8)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=45, ha='right')
    ax.set_ylabel('Monthly ROI (%)')
    ax.set_title('Monthly ROI by Month')
    ax.legend()
    ax.grid(axis='y', alpha=0.3)

    # ── Bottom: Cumulative ROI line ──────────────────────────────────────────
    ax2 = axes[1]
    cum_claude = [sum(claude_rois[:i+1]) for i in range(len(claude_rois))]
    cum_ag     = [sum(ag_rois[:i+1])     for i in range(len(ag_rois))]

    ax2.plot(list(x), cum_claude, 'o-', color='#FF8C00', linewidth=2.5,
             markersize=6, label=f'Claude Omega (total {sum(claude_rois):+.1f}%)')
    ax2.plot(list(x), cum_ag,     's-', color='#1E90FF', linewidth=2.5,
             markersize=6, label=f'Antigravity (total {sum(ag_rois):+.1f}%)')
    ax2.axhline(0, color='black', linewidth=0.8, linestyle='--')
    ax2.fill_between(list(x), cum_claude, 0, alpha=0.1, color='#FF8C00')
    ax2.fill_between(list(x), cum_ag,     0, alpha=0.1, color='#1E90FF')
    ax2.set_xticks(list(x))
    ax2.set_xticklabels(labels, rotation=45, ha='right')
    ax2.set_ylabel('Cumulative ROI (%)')
    ax2.set_title(f'Cumulative ROI -- Claude {claude_wins}W | AG {ag_wins}W | {ties} Ties')
    ax2.legend()
    ax2.grid(alpha=0.3)

    plt.tight_layout()
    fname = 'monthly_arena.png'
    plt.savefig(fname, dpi=180, bbox_inches='tight', facecolor='white')
    print(f"\n  Chart saved -> {fname}")

    return labels, claude_rois, ag_rois, claude_wins, ag_wins


if __name__ == '__main__':
    main()
