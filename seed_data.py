"""
seed_data.py — Inject historical replay trades (Mar 18-23 2026) into CSV/JSON
on Railway volume if files are empty or missing.
Runs once at startup before the paper traders start.
"""

import csv
import json
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", Path(__file__).parent))

TRADE_FIELDS = [
    "date", "time", "action", "dir", "shares", "price",
    "stop", "reason", "pnl", "balance", "signal_details"
]

# ── Historical replay data from March 18-23 2026 ──────────────────────────────

# ClaudeAPEX (5m) — one trade on Mar 20  (GC=F real prices)
APEX_TRADES = [
    {
        "date": "2026-03-20", "time": "09:40", "action": "BUY", "dir": "LONG",
        "shares": 1, "price": 4662.90, "stop": 4621.60, "reason": "SIGNAL", "pnl": "",
        "balance": 500.00,
        "signal_details": "gap=+0.35% vwap=4655.20 vei=0.971 atr=13.8 [REPLAY]",
    },
    {
        "date": "2026-03-20", "time": "09:50", "action": "CLOSE", "dir": "LONG",
        "shares": 1, "price": 4621.60, "stop": 4621.60, "reason": "STOP", "pnl": -41.37,
        "balance": 458.63,
        "signal_details": "entry=4662.90 comm=0.93 [REPLAY]",
    },
]

APEX_STATE = {
    "ticker":        "GC=F",
    "capital":       500.0,
    "balance":       458.63,
    "position":      None,
    "today":         None,
    "bar_count":     0,
    "prior_close":   0,
    "traded_today":  False,
    "total_trades":  1,
    "total_pnl":     -41.37,
    "wins":          0,
    "losses":        1,
}

# Zone Refinement (1H) — one trade on Mar 20  (GC=F real prices)
ZONE_TRADES = [
    {
        "date": "2026-03-20", "time": "13:00", "action": "SELL", "dir": "SHORT",
        "shares": 1, "price": 4585.60, "stop": 4607.20, "reason": "ZONE", "pnl": "",
        "balance": 500.00,
        "signal_details": "zone=supply htf=[4556,4602] refined=[4585,4602] rr=3.2 [REPLAY]",
    },
    {
        "date": "2026-03-20", "time": "14:00", "action": "CLOSE", "dir": "SHORT",
        "shares": 1, "price": 4500.70, "stop": 4607.20, "reason": "TARGET", "pnl": 84.44,
        "balance": 584.44,
        "signal_details": "entry=4585.60 comm=0.91 zone=supply [REPLAY]",
    },
]

ZONE_STATE = {
    "ticker":        "GC=F",
    "capital":       500.0,
    "balance":       584.44,
    "position":      None,
    "zones":         [],
    "zones_date":    None,
    "total_trades":  1,
    "total_pnl":     84.44,
    "wins":          1,
    "losses":        0,
}


def seed_csv(path: Path, rows: list, label: str):
    """Write rows to CSV only if the file doesn't exist or is empty."""
    if path.exists() and path.stat().st_size > 10:
        print(f"  {label}: already has data — skipping seed")
        return
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"  {label}: seeded {len(rows)} rows -> {path}")


def seed_json(path: Path, data: dict, label: str):
    """Write JSON state only if the file doesn't exist."""
    if path.exists() and path.stat().st_size > 10:
        print(f"  {label}: state already exists — skipping seed")
        return
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  {label}: state seeded -> {path}")


if __name__ == "__main__":
    print("Seeding historical trade data (Mar 18-23 2026)...")

    seed_csv(DATA_DIR / "paper_trades.csv", APEX_TRADES,  "ClaudeAPEX trades")
    seed_json(DATA_DIR / "paper_state.json", APEX_STATE,  "ClaudeAPEX state")

    seed_csv(DATA_DIR / "zone_trades.csv",  ZONE_TRADES,  "Zone Refinement trades")
    seed_json(DATA_DIR / "zone_state.json", ZONE_STATE,   "Zone Refinement state")

    print("Seed complete.")
