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
# 4 closed trades: 2W / 2L  |  Net P&L: +$645.30
# Params: strength_mult=1.7, bos_slope_bars=5, stop_buffer=0.003,
#   target_lookback=120, zone_age_max=7d (live), stop_cooldown=3h
# Win avg: +$508  |  Loss avg: -$186  |  W/L ratio: 2.73x

ZONE_TRADES = [
    {"date": "2026-03-18", "time": "18:00", "action": "SELL",  "dir": "SHORT",
     "shares": 8, "price": 4837.10, "stop": 4859.535, "reason": "ZONE", "pnl": "",
     "balance": 10000.00,
     "signal_details": "zone=supply htf=[4806,4852] refined=[4830.500,4845.000] rr=3.0"},
    {"date": "2026-03-19", "time": "02:00", "action": "CLOSE", "dir": "SHORT",
     "shares": 8, "price": 4769.795, "stop": 4859.535, "reason": "TARGET", "pnl": 530.75,
     "balance": 10530.75,
     "signal_details": "entry=4837.100 comm=7.69 zone=supply"},
    {"date": "2026-03-20", "time": "02:00", "action": "BUY",   "dir": "LONG",
     "shares": 2, "price": 4670.30, "stop": 4581.614, "reason": "ZONE", "pnl": "",
     "balance": 10530.75,
     "signal_details": "zone=demand htf=[4595,4672] refined=[4595.400,4672.300] rr=5.2"},
    {"date": "2026-03-20", "time": "10:00", "action": "CLOSE", "dir": "LONG",
     "shares": 2, "price": 4581.614, "stop": 4581.614, "reason": "STOP", "pnl": -179.22,
     "balance": 10351.53,
     "signal_details": "entry=4670.300 comm=1.85 zone=demand"},
    {"date": "2026-03-20", "time": "14:00", "action": "SELL",  "dir": "SHORT",
     "shares": 3, "price": 4500.70, "stop": 4555.024, "reason": "ZONE", "pnl": "",
     "balance": 10351.53,
     "signal_details": "zone=supply htf=[4463,4541] refined=[4526.100,4541.400] rr=3.0"},
    {"date": "2026-03-23", "time": "01:00", "action": "CLOSE", "dir": "SHORT",
     "shares": 3, "price": 4337.728, "stop": 4555.024, "reason": "TARGET", "pnl": 486.26,
     "balance": 10837.79,
     "signal_details": "entry=4500.700 comm=2.65 zone=supply"},
    {"date": "2026-03-23", "time": "02:00", "action": "SELL",  "dir": "SHORT",
     "shares": 5, "price": 4225.10, "stop": 4262.750, "reason": "ZONE", "pnl": "",
     "balance": 10837.79,
     "signal_details": "zone=supply htf=[4224,4250] refined=[4234.200,4250.000] rr=3.0"},
    {"date": "2026-03-23", "time": "06:00", "action": "CLOSE", "dir": "SHORT",
     "shares": 5, "price": 4262.750, "stop": 4262.750, "reason": "STOP", "pnl": -192.49,
     "balance": 10645.30,
     "signal_details": "entry=4225.100 comm=4.24 zone=supply"},
    {"date": "2026-03-23", "time": "09:00", "action": "SELL",  "dir": "SHORT",
     "shares": 4, "price": 4457.60, "stop": 4510.090, "reason": "ZONE", "pnl": "",
     "balance": 10645.30,
     "signal_details": "zone=supply htf=[4454,4497] refined=[4479.500,4496.600] rr=6.8"},
]

ZONE_STATE = {
    "ticker":        "GC=F",
    "capital":       10000.0,
    "balance":       10645.30,
    "position":      None,
    "zones":         [],
    "zones_date":    None,
    "total_trades":  4,
    "total_pnl":     645.30,
    "wins":          2,
    "losses":        2,
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
