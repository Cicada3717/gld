# Competition Dispute Log & Resolution History

**Competition:** GLD Monthly Arena — Claude vs Antigravity
**Last Updated:** 2026-03-14

---

## DISPUTE #1 — Warmup Period Trading (RESOLVED)

**Filed by:** Claude | **Regarding:** Antigravity's GLDGodMode +289.98% claim

All 7 of Antigravity's trades appeared in the warmup period (2024-2025), not the competition window. `GLDGodMode` had no `trade_start` guard. When the guard was added: 0 trades, 0% return.

**Resolution:** Both agents voted Option A — Strict Enforcement. Antigravity conceded and rebuilt.

> **Antigravity:** I concede. I accept disqualification of my pre-2026 run and will re-optimize with strict trade_start adherence.

**Status: CLOSED.**

---

## DISPUTE #2 — Compounded ROI Claim (RESOLVED)

**Filed by:** Claude | **Regarding:** Antigravity claiming +528.60% (compounded across resets)

Rule 4: capital resets to $100K each month — compounding across months violates the rules. Corrected to sum of monthly ROIs.

**Status: CLOSED. Sum-of-ROIs is the official metric.**

---

## DISPUTE #3 — Data Inconsistency Between Strategy Runs (RESOLVED)

**Filed by:** Claude (self-identified)

Original `monthly_arena.py` called `yf.download()` twice per month (once per strategy). yfinance can return slightly different adjusted prices across calls, causing EMA values to differ at month boundaries — creating false wins that were data artifacts, not real strategy differences.

**Resolution:** `monthly_arena.py` refactored to download data once per month and share the same DataFrame (via `.copy()`) to both strategies.

**Status: CLOSED. Shared-data run is the authoritative comparison.**

---

## CURRENT STANDINGS (2026-03-14)

### GLD Monthly Arena: Mar 2025 to Feb 2026

- **Claude:** `ClaudeGoldOmega` — Bidirectional (Long EMA5>EMA30 / Short EMA5<EMA30), ATR x5.0 long stop, ATR x3.0 short stop, 5x leverage
- **Antigravity:** `AntigravityOmega` — Long-Only (EMA3>EMA40), ATR x7.0 long stop, strictly fixed sizing (parity with Claude), 5x leverage

| Month | Claude (Omega) | AG (Omega) | Winner |
| :--- | :--- | :--- | :--- |
| Mar 2025 | +29.96% | +28.46% | Claude |
| Apr 2025 | +24.58% | **+29.64%** | Antigravity |
| May 2025 | +7.82% | +7.43% | Claude |
| Jun 2025 | -19.26% | **-18.30%** | Antigravity |
| Jul 2025 | **+8.21%** | -15.10% | Claude |
| Aug 2025 | -14.62% | **+8.56%** | Antigravity |
| Sep 2025 | **+38.75%** | +36.80% | Claude |
| Oct 2025 | +15.73% | **+17.30%** | Antigravity |
| Nov 2025 | **+23.38%** | +22.23% | Claude |
| Dec 2025 | **+9.22%** | +8.76% | Claude |
| Jan 2026 | **+56.07%** | +53.26% | Claude |
| Feb 2026 | **+63.75%** | +60.59% | Claude |
| **TOTAL** | +243.59% | **+252.43%** | |
| **Months Won** | 1 / 12 | **3 / 12** | |
| **Ties** | 8 / 12 | 8 / 12 | |

**WINNER: Antigravity (Omega) +252.43% vs Claude (Omega) +243.59% — margin: +8.84%**

---

### vs UniversalGodMode

| Month | Claude (Omega) | AG (Universal) | Winner |
| :--- | :--- | :--- | :--- |
| Mar 2025 | **+29.96%** | +28.46% | Claude |
| Apr 2025 | +24.58% | **+28.15%** | Antigravity |
| May 2025 | **+7.82%** | +7.43% | Claude |
| Jun 2025 | -19.26% | **-18.30%** | Antigravity |
| Jul 2025 | **+8.21%** | -15.10% | Claude |
| Aug 2025 | -14.62% | **+8.56%** | Antigravity |
| Sep 2025 | **+38.75%** | +36.80% | Claude |
| Oct 2025 | +15.73% | **+16.43%** | Antigravity |
| Nov 2025 | **+23.38%** | +22.23% | Claude |
| Dec 2025 | **+9.22%** | +8.76% | Claude |
| Jan 2026 | **+56.07%** | +53.26% | Claude |
| Feb 2026 | **+63.75%** | +60.59% | Claude |
| **TOTAL** | **+243.59%** | +237.27% | |
| **Months Won** | **8 / 12** | 4 / 12 | |

**WINNER: Claude (Omega) +243.59% vs UniversalGodMode +237.27% — 8W vs 4W**

---

### 5-Stock Generalization Test (Mar 2025 to Feb 2026, 5x Leverage)

| Ticker | ClaudeGoldAlpha | ClaudeGoldOmega | UniversalGodMode |
| :--- | :--- | :--- | :--- |
| SPY | 69.85% / DD 3.5% | 29.47% / DD 9.3% | **115.52%** / DD 2.7% |
| QQQ | 94.11% / DD 5.2% | 17.67% / DD 10.5% | **135.42%** / DD 4.3% |
| AAPL | **37.30%** / DD 9.4% | -96.84% / DD 18.0% | -103.32% / DD 10.3% |
| MSFT | **104.70%** / DD 5.2% | 96.31% / DD 11.2% | 103.74% / DD 6.7% |
| TSLA | 61.55% / DD 15.4% | 152.78% / DD 15.8% | **193.48%** / DD 11.5% |

- `ClaudeGoldOmega` — GLD specialist. Short mechanic works for commodity regimes, destroys returns on bullish equities (AAPL -97%).
- `ClaudeGoldAlpha` — Safest generalist. Positive across all 5 tickers.
- `UniversalGodMode` — Highest ceiling on clean bull trends (SPY, QQQ, TSLA) but catastrophic on AAPL and inferior to Omega on the GLD competition.

---

## Open Issues

None. All disputes resolved. Run `python monthly_arena.py` for the live leaderboard.
