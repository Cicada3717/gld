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
# 10 closed trades: 5W / 5L  |  Net P&L: +$1,415.59

ZONE_TRADES = [
    {"date": "2026-03-18", "time": "02:00", "action": "SELL",  "dir": "SHORT",
     "shares": 9, "price": 5013.80, "stop": 5022.317, "reason": "ZONE", "pnl": "",
     "balance": 10000.00,
     "signal_details": "zone=supply htf=[4988,5022] refined=[5004.700,5017.300] rr=5.1"},
    {"date": "2026-03-18", "time": "07:00", "action": "CLOSE", "dir": "SHORT",
     "shares": 9, "price": 4970.10, "stop": 5022.317, "reason": "TARGET", "pnl": 384.31,
     "balance": 10384.31,
     "signal_details": "entry=5013.800 comm=8.99 zone=supply"},
    {"date": "2026-03-18", "time": "18:00", "action": "SELL",  "dir": "SHORT",
     "shares": 10, "price": 4837.10, "stop": 4849.845, "reason": "ZONE", "pnl": "",
     "balance": 10384.31,
     "signal_details": "zone=supply htf=[4806,4852] refined=[4830.500,4845.000] rr=3.0"},
    {"date": "2026-03-18", "time": "21:00", "action": "CLOSE", "dir": "SHORT",
     "shares": 10, "price": 4849.845, "stop": 4849.845, "reason": "STOP", "pnl": -137.14,
     "balance": 10247.18,
     "signal_details": "entry=4837.100 comm=9.69 zone=supply"},
    {"date": "2026-03-18", "time": "22:00", "action": "SELL",  "dir": "SHORT",
     "shares": 10, "price": 4859.50, "stop": 4868.263, "reason": "ZONE", "pnl": "",
     "balance": 10247.18,
     "signal_details": "zone=supply htf=[4834,4869] refined=[4842.600,4863.400] rr=5.7"},
    {"date": "2026-03-19", "time": "02:00", "action": "CLOSE", "dir": "SHORT",
     "shares": 10, "price": 4809.30, "stop": 4868.263, "reason": "TARGET", "pnl": 492.33,
     "balance": 10739.51,
     "signal_details": "entry=4859.500 comm=9.67 zone=supply"},
    {"date": "2026-03-20", "time": "02:00", "action": "BUY",   "dir": "LONG",
     "shares": 2, "price": 4670.30, "stop": 4590.805, "reason": "ZONE", "pnl": "",
     "balance": 10739.51,
     "signal_details": "zone=demand htf=[4595,4672] refined=[4595.400,4672.300] rr=4.4"},
    {"date": "2026-03-20", "time": "10:00", "action": "CLOSE", "dir": "LONG",
     "shares": 2, "price": 4590.805, "stop": 4590.805, "reason": "STOP", "pnl": -160.84,
     "balance": 10578.67,
     "signal_details": "entry=4670.300 comm=1.85 zone=demand"},
    {"date": "2026-03-20", "time": "11:00", "action": "SELL",  "dir": "SHORT",
     "shares": 11, "price": 4555.30, "stop": 4570.466, "reason": "ZONE", "pnl": "",
     "balance": 10578.67,
     "signal_details": "zone=supply htf=[4553,4566] refined=[4552.700,4565.900] rr=3.3"},
    {"date": "2026-03-20", "time": "12:00", "action": "CLOSE", "dir": "SHORT",
     "shares": 11, "price": 4570.466, "stop": 4570.466, "reason": "STOP", "pnl": -176.86,
     "balance": 10401.80,
     "signal_details": "entry=4555.300 comm=10.04 zone=supply"},
    {"date": "2026-03-20", "time": "14:00", "action": "SELL",  "dir": "SHORT",
     "shares": 4, "price": 4500.70, "stop": 4545.941, "reason": "ZONE", "pnl": "",
     "balance": 10401.80,
     "signal_details": "zone=supply htf=[4463,4541] refined=[4526.100,4541.400] rr=3.0"},
    {"date": "2026-03-22", "time": "20:00", "action": "CLOSE", "dir": "SHORT",
     "shares": 4, "price": 4364.977, "stop": 4545.941, "reason": "TARGET", "pnl": 539.35,
     "balance": 10941.15,
     "signal_details": "entry=4500.700 comm=3.55 zone=supply"},
    {"date": "2026-03-22", "time": "21:00", "action": "SELL",  "dir": "SHORT",
     "shares": 12, "price": 4390.00, "stop": 4397.994, "reason": "ZONE", "pnl": "",
     "balance": 10941.15,
     "signal_details": "zone=supply htf=[4364,4396] refined=[4370.200,4393.600] rr=3.0"},
    {"date": "2026-03-22", "time": "22:00", "action": "CLOSE", "dir": "SHORT",
     "shares": 12, "price": 4366.019, "stop": 4397.994, "reason": "TARGET", "pnl": 277.27,
     "balance": 11218.41,
     "signal_details": "entry=4390.000 comm=10.51 zone=supply"},
    {"date": "2026-03-22", "time": "23:00", "action": "SELL",  "dir": "SHORT",
     "shares": 5, "price": 4355.30, "stop": 4393.990, "reason": "ZONE", "pnl": "",
     "balance": 11218.41,
     "signal_details": "zone=supply htf=[4320,4390] refined=[4367.500,4389.600] rr=3.0"},
    {"date": "2026-03-23", "time": "02:00", "action": "CLOSE", "dir": "SHORT",
     "shares": 5, "price": 4239.230, "stop": 4393.990, "reason": "TARGET", "pnl": 576.05,
     "balance": 11794.47,
     "signal_details": "entry=4355.300 comm=4.30 zone=supply"},
    {"date": "2026-03-23", "time": "03:00", "action": "SELL",  "dir": "SHORT",
     "shares": 14, "price": 4205.70, "stop": 4217.213, "reason": "ZONE", "pnl": "",
     "balance": 11794.47,
     "signal_details": "zone=supply htf=[4176,4215] refined=[4191.300,4213.000] rr=3.0"},
    {"date": "2026-03-23", "time": "04:00", "action": "CLOSE", "dir": "SHORT",
     "shares": 14, "price": 4217.213, "stop": 4217.213, "reason": "STOP", "pnl": -172.97,
     "balance": 11621.49,
     "signal_details": "entry=4205.700 comm=11.79 zone=supply"},
    {"date": "2026-03-23", "time": "06:00", "action": "SELL",  "dir": "SHORT",
     "shares": 4, "price": 4270.00, "stop": 4320.616, "reason": "ZONE", "pnl": "",
     "balance": 11621.49,
     "signal_details": "zone=supply htf=[4258,4316] refined=[4257.700,4316.300] rr=3.0"},
    {"date": "2026-03-23", "time": "07:00", "action": "CLOSE", "dir": "SHORT",
     "shares": 4, "price": 4320.616, "stop": 4320.616, "reason": "STOP", "pnl": -205.90,
     "balance": 11415.59,
     "signal_details": "entry=4270.000 comm=3.44 zone=supply"},
    {"date": "2026-03-23", "time": "08:00", "action": "SELL",  "dir": "SHORT",
     "shares": 11, "price": 4480.60, "stop": 4501.097, "reason": "ZONE", "pnl": "",
     "balance": 11415.59,
     "signal_details": "zone=supply htf=[4454,4497] refined=[4479.500,4496.600] rr=18.6"},
]

ZONE_STATE = {
    "ticker":        "GC=F",
    "capital":       10000.0,
    "balance":       11415.59,
    "position":      None,
    "zones":         [],
    "zones_date":    None,
    "total_trades":  10,
    "total_pnl":     1415.59,
    "wins":          5,
    "losses":        5,
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
