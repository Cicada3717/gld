"""
Visualize the Competition Arena: Claude vs Antigravity on GLD.
Generates a comparison chart saved as arena_comparison.png
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

# ── Results from verified backtests ──────────────────────────────────────────
agents = ['Claude\n(GoldAlpha 5x)', 'Antigravity\n(GodMode v2.0 5x)']
roi =        [81.18, 109.92]
max_dd =     [5.42, 5.96]
sharpe =     [0.707, 0.707]
trades =     [1, 2]
final_value = [181178.19, 209923.97]

colors_claude = '#FF8C00'   # Orange for Claude
colors_anti   = '#1E90FF'   # Blue for Antigravity
bar_colors = [colors_claude, colors_anti]

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('GLD Arena: Claude vs Antigravity (2026-01-01 to 2026-03-14)',
             fontsize=16, fontweight='bold', y=0.98)

# ── 1. ROI Bar Chart ────────────────────────────────────────────────────────
ax = axes[0, 0]
bars = ax.bar(agents, roi, color=bar_colors, width=0.5, edgecolor='black', linewidth=1.2)
for bar, val in zip(bars, roi):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1.5,
            f'+{val:.1f}%', ha='center', va='bottom', fontsize=14, fontweight='bold')
ax.set_ylabel('Return on Investment (%)', fontsize=12)
ax.set_title('ROI', fontsize=14, fontweight='bold')
ax.set_ylim(0, max(roi) * 1.25)
ax.axhline(y=15.71, color='gray', linestyle='--', alpha=0.6, label='Buy & Hold (+15.7%)')
ax.legend(fontsize=9)
ax.grid(axis='y', alpha=0.3)

# ── 2. Max Drawdown (lower is better) ───────────────────────────────────────
ax = axes[0, 1]
bars = ax.bar(agents, max_dd, color=bar_colors, width=0.5, edgecolor='black', linewidth=1.2)
for bar, val in zip(bars, max_dd):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
            f'{val:.1f}%', ha='center', va='bottom', fontsize=14, fontweight='bold')
ax.set_ylabel('Max Drawdown (%)', fontsize=12)
ax.set_title('Max Drawdown (lower = better)', fontsize=14, fontweight='bold')
ax.set_ylim(0, max(max_dd) * 1.5)
ax.grid(axis='y', alpha=0.3)

# ── 3. Sharpe Ratio ─────────────────────────────────────────────────────────
ax = axes[1, 0]
bars = ax.bar(agents, sharpe, color=bar_colors, width=0.5, edgecolor='black', linewidth=1.2)
for bar, val in zip(bars, sharpe):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02,
            f'{val:.3f}', ha='center', va='bottom', fontsize=14, fontweight='bold')
ax.set_ylabel('Sharpe Ratio', fontsize=12)
ax.set_title('Sharpe Ratio (higher = better)', fontsize=14, fontweight='bold')
ax.set_ylim(0, max(sharpe) * 1.4)
ax.grid(axis='y', alpha=0.3)

# ── 4. Final Portfolio Value ─────────────────────────────────────────────────
ax = axes[1, 1]
bars = ax.bar(agents, final_value, color=bar_colors, width=0.5, edgecolor='black', linewidth=1.2)
for bar, val in zip(bars, final_value):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1500,
            f'${val:,.0f}', ha='center', va='bottom', fontsize=13, fontweight='bold')
ax.set_ylabel('Portfolio Value ($)', fontsize=12)
ax.set_title('Final Portfolio Value', fontsize=14, fontweight='bold')
ax.set_ylim(80000, max(final_value) * 1.15)
ax.axhline(y=100000, color='red', linestyle='--', alpha=0.5, label='Starting Capital ($100K)')
ax.legend(fontsize=9)
ax.grid(axis='y', alpha=0.3)

# ── Layout ───────────────────────────────────────────────────────────────────
plt.tight_layout(rect=[0, 0, 1, 0.95])
fname = 'arena_comparison.png'
plt.savefig(fname, dpi=200, bbox_inches='tight', facecolor='white')
print(f"Saved comparison chart -> {fname}")
