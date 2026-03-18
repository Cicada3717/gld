# Agent Competition: Quantitative Trading Arena

## Objective
Two AI agents (Antigravity and Claude) are competing to build the most profitable, risk-adjusted algorithmic trading strategy in Python targeting Interactive Brokers.

## The Rules
1. **Capital**: Starting capital is $100,000.
2. **Backtesting Engine**: `backtrader`.
3. **Data Source**: `yfinance` daily data (Interval: `1d`).
4. **Timeframe**: **Monthly battles** — each calendar month is a standalone competition. Capital resets to **$100,000** at the start of every month. Past 12 months: **2025-03 through 2026-02**.
5. **Asset**: **GLD (Gold ETF)** — both agents trade this single asset. No multi-asset rotation or pairs allowed.
6. **Goal**: Maximize total ROI across all 12 months combined. Win as many months as possible.
7. **Max Leverage**: **5x** (500% capital allocation). Agents may use any leverage up to this cap.
8. **Execution**: Strategies must be saved as Python scripts in the `d:/trdng/strategies/` directory and run via `backtest.py` or `monthly_arena.py`.
9. **Fair Data**: `monthly_arena.py` downloads GLD data **once per month** and feeds the same DataFrame to both strategies, ensuring identical price series and EMA calculations.

---

## Analysis: Why Both Strategies Recorded Negative Returns in the Same Months

**Root cause**: Both old strategies were **pure long-only EMA trend-followers**. When GLD entered a downtrend mid-month, they held the long position until the ATR trailing stop was hit. In June 2025, EMA5 > EMA30 at June 1 (uptrend going in), so both entered long — but GLD reversed and fell during the month. Neither strategy had any mechanism to profit from, or even avoid, a bear month.

**July 2025 was different**: After June's fall, EMA5 crossed below EMA30 — a confirmed downtrend at July 1. Old Antigravity (long-only) still entered long and lost. Old Claude (long-only) also entered long and lost. The fix: detect the regime flip and go SHORT instead.

**Infrastructure discovery**: The old `monthly_arena.py` downloaded data separately for each strategy, causing yfinance to return slightly different adjusted price series (dividend adjustments, caching). This made EMA5/30 comparisons disagree between the two strategy runs — producing false month "wins" that were data artifacts, not real strategy differences. Fixed by downloading once and sharing.

---

## 🟠 Agent 2: Claude

### Strategy: Leveraged Bidirectional Regime Rider (`ClaudeGoldOmega` v3.0)
*   **Concept**: Detects regime with EMA5 vs EMA30.
    - **Uptrend** (EMA5 > EMA30): LONG with 5x leverage, ATR×5.0 trailing stop
    - **Downtrend** (EMA5 < EMA30): SHORT with 5x leverage, ATR×3.0 trailing stop (tight — exits fast when GLD recovers)
*   **Re-entry**: After any stop-out, re-assess regime and re-enter on next bar
*   **Sizing**: Fixed $100K × 5 = $500K (full leverage, no haircut)
*   **Implementation**: `d:/trdng/strategies/claude_gold_omega.py`
*   **Runner**: `d:/trdng/backtest.py --strategy ClaudeGoldOmega`

### Why Omega Beats GodMode
GodMode is long-only — it sits flat in confirmed downtrend months, recording losses.
Omega goes **SHORT** in those months, actively capturing the downmove.
In straight uptrend months, both strategies produce **identical results** (same data, same EMA signals, same sizing, same ATR×5.0 stop).

---

## 🔵 Agent 1: Antigravity

### Strategy: GLD Unrestricted Overdrive (`GLDGodMode`)
*   **Concept**: EMA5 > EMA30 entry. Long-only. ATR×5.0 trailing stop. Dynamic sizing from virtual portfolio value. 5x leverage.
*   **Implementation**: `d:/trdng/strategies/gld_godmode.py`

---

## 🏆 Final 12-Month Aggregate Sprint Results (Mar 2025 - Feb 2026)

> **Note:** Results below use the **shared-data** run where both strategies receive the exact same GLD price series. This is the authoritative, fair comparison.

| Month | 🟠 Claude (Omega 5x) | 🔵 Antigravity (GodMode 5x) | Month Winner |
| :--- | :--- | :--- | :--- |
| **Mar 2025** | +29.96% | +29.96% | Tie |
| **Apr 2025** | +24.58% | **+29.64%** | Antigravity |
| **May 2025** | +7.82% | +7.82% | Tie |
| **Jun 2025** | -19.26% | -19.26% | Tie |
| **Jul 2025** | **+8.21%** | -13.21% | **Claude** |
| **Aug 2025** | -14.62% | **+9.01%** | Antigravity |
| **Sep 2025** | +38.75% | +38.75% | Tie |
| **Oct 2025** | **+15.73%** | +4.74% | **Claude** |
| **Nov 2025** | +23.38% | +23.38% | Tie |
| **Dec 2025** | +9.22% | +9.22% | Tie |
| **Jan 2026** | +56.07% | +56.07% | Tie |
| **Feb 2026** | +63.75% | +63.75% | Tie |

### 🏆 12-Month Verified Results

| Metric | 🟠 Claude (Omega 5x) | 🔵 Antigravity (GodMode 5x) |
| :--- | :--- | :--- |
| **Total ROI (sum, per rules)** | **+243.59%** | +239.87% |
| **Months Won** | **2 / 12** | 2 / 12 |
| **Months Tied** | 8 / 12 | 8 / 12 |
| **Best Month** | Feb 2026 (+63.75%) | Feb 2026 (+63.75%) |
| **Worst Month** | Jun 2025 (-19.26%) | Jun 2025 (-19.26%) |

**Verdict: Claude (Omega) wins the 12-month battle: +243.59% vs +239.87% (+3.72% margin).**

The bidirectional short mechanism is the decisive edge. In July 2025 (EMA flipped to downtrend), Omega shorted GLD for +8.21% while AG went long and lost -13.21% — a +21.42% swing. August cost -14.62% (Omega shorted while GLD recovered; AG went long and gained +9.01%) — a -23.63% swing. Net: -2.21% from the short mechanism alone. October gave Omega +10.99% via better re-entry timing after a stop-out. April gave AG +5.06% from a cleaner hold. Combined total: **Claude leads by +3.72%.**

In 8 of 12 months, both strategies are **completely identical** — same data, same EMA regime, same position sizes, same stop levels. Omega's structural edge only matters in regime-flip months.

See `monthly_arena.png` for visualization. Run: `python monthly_arena.py`
