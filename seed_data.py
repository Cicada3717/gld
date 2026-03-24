"""
seed_data.py — Inject historical replay trades (Mar 18-23 2026) into CSV/JSON
on Railway volume if files are empty or missing.
Runs once at startup before the paper trader starts.

Results are from replay.py simulation on real GC=F data with $10,000 capital.
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

# -- Zone Refinement (1H) -- replay Mar 18-23 on real GC=F data ---------------
# 2 closed trades: 2W / 0L  |  Net P&L: +$1,072.15
# New params: strength_mult=2.0, bos_slope_bars=5, stop_buffer=0.003,
#   target_lookback=120, zone_age_max=3d, stop_cooldown=6h

ZONE_TRADES = [
    {"date": "2026-03-18", "time": "18:00", "action": "SELL",  "dir": "SHORT",
     "shares": 8, "price": 4837.10, "stop": 4859.535, "reason": "ZONE", "pnl": "",
     "balance": 10000.00,
     "signal_details": "zone=supply htf=[4806,4852] refined=[4830.500,4845.000] rr=3.0"},
    {"date": "2026-03-19", "time": "02:00", "action": "CLOSE", "dir": "SHORT",
     "shares": 8, "price": 4769.795, "stop": 4859.535, "reason": "TARGET", "pnl": 530.75,
     "balance": 10530.75,
     "signal_details": "entry=4837.100 comm=7.69 zone=supply"},
    {"date": "2026-03-22", "time": "18:00", "action": "SELL",  "dir": "SHORT",
     "shares": 2, "price": 4498.10, "stop": 4588.625, "reason": "ZONE", "pnl": "",
     "balance": 10530.75,
     "signal_details": "zone=supply htf=[4488,4575] refined=[4488.500,4574.900] rr=3.0"},
    {"date": "2026-03-23", "time": "02:00", "action": "CLOSE", "dir": "SHORT",
     "shares": 2, "price": 4226.527, "stop": 4588.625, "reason": "TARGET", "pnl": 541.40,
     "balance": 11072.15,
     "signal_details": "entry=4498.100 comm=1.74 zone=supply"},
    {"date": "2026-03-23", "time": "08:00", "action": "SELL",  "dir": "SHORT",
     "shares": 3, "price": 4480.60, "stop": 4550.711, "reason": "ZONE", "pnl": "",
     "balance": 11072.15,
     "signal_details": "zone=supply htf=[4453,4537] refined=[4490.000,4537.100] rr=5.4"},
]

ZONE_STATE = {
    "ticker":        "GC=F",
    "capital":       10000.0,
    "balance":       11072.15,
    "position":      None,
    "zones":         [],
    "zones_date":    None,
    "total_trades":  2,
    "total_pnl":     1072.15,
    "wins":          2,
    "losses":        0,
}


def seed_csv(path: Path, rows: list, label: str):
    """Write rows to CSV only if the file doesn't exist or is empty."""
    if path.exists() and path.stat().st_size > 10:
        print(f"  {label}: already has data -- skipping seed")
        return
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"  {label}: seeded {len(rows)} rows -> {path}")


def seed_json(path: Path, data: dict, label: str):
    """Write JSON state only if the file doesn't exist or is empty."""
    if path.exists() and path.stat().st_size > 10:
        print(f"  {label}: state already exists -- skipping seed")
        return
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  {label}: state seeded -> {path}")


if __name__ == "__main__":
    print("Seeding historical trade data (Mar 18-23 2026, real GC=F replay)...")

    seed_csv(DATA_DIR / "zone_trades.csv",  ZONE_TRADES,  "Zone Refinement trades")
    seed_json(DATA_DIR / "zone_state.json", ZONE_STATE,   "Zone Refinement state")

    print("Seed complete.")
