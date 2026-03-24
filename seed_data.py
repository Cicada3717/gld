"""
seed_data.py — Inject historical replay trades (Mar 18-23 2026) into CSV/JSON
on Railway volume if files are empty or missing.
Runs once at startup before the paper traders start.

Results are from replay.py simulation on real GC=F data with $5,000 capital.
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

# ── ClaudeAPEX v12 (5m) — replay Mar 18-23 on real GC=F data ─────────────────
# 4 trades: 3 SHORTs (2 stops, 1 win), 1 LONG (stop)
# Net P&L: -$19.57

APEX_TRADES = [
    # Mar 18 — SHORT at NY open, gap -2.59%, stopped out
    {"date": "2026-03-18", "time": "10:35", "action": "SELL",  "dir": "SHORT",
     "shares": 2, "price": 4863.30, "stop": 4901.35, "reason": "SIGNAL", "pnl": "",
     "balance": 5000.00,
     "signal_details": "gap=-2.59% vwap=4875.21 vei=1.230 atr=12.68"},
    {"date": "2026-03-18", "time": "13:00", "action": "CLOSE", "dir": "SHORT",
     "shares": 2, "price": 4892.14, "stop": 4892.14, "reason": "STOP", "pnl": -59.63,
     "balance": 4940.37,
     "signal_details": "entry=4863.30 comm=1.95"},
    # Mar 19 — SHORT, gap -5.60%, stopped out
    {"date": "2026-03-19", "time": "11:30", "action": "SELL",  "dir": "SHORT",
     "shares": 1, "price": 4580.80, "stop": 4648.72, "reason": "SIGNAL", "pnl": "",
     "balance": 4940.37,
     "signal_details": "gap=-5.60% vwap=4607.84 vei=1.117 atr=22.64"},
    {"date": "2026-03-19", "time": "15:00", "action": "CLOSE", "dir": "SHORT",
     "shares": 1, "price": 4631.08, "stop": 4631.08, "reason": "STOP", "pnl": -51.20,
     "balance": 4889.17,
     "signal_details": "entry=4580.80 comm=0.92"},
    # Mar 20 — SHORT, gap -1.54%, trailing stop WIN
    {"date": "2026-03-20", "time": "09:45", "action": "SELL",  "dir": "SHORT",
     "shares": 2, "price": 4652.20, "stop": 4690.13, "reason": "SIGNAL", "pnl": "",
     "balance": 4889.17,
     "signal_details": "gap=-1.54% vwap=4653.35 vei=1.217 atr=12.64"},
    {"date": "2026-03-20", "time": "12:15", "action": "CLOSE", "dir": "SHORT",
     "shares": 2, "price": 4601.57, "stop": 4601.57, "reason": "STOP", "pnl": 99.40,
     "balance": 4988.57,
     "signal_details": "entry=4652.20 comm=1.85"},
    # Mar 23 — LONG, gap +1.81%, stopped out
    {"date": "2026-03-23", "time": "09:35", "action": "BUY",   "dir": "LONG",
     "shares": 1, "price": 4434.10, "stop": 4346.06, "reason": "SIGNAL", "pnl": "",
     "balance": 4988.57,
     "signal_details": "gap=+1.81% vwap=4424.98 vei=0.988 atr=29.35"},
    {"date": "2026-03-23", "time": "11:35", "action": "CLOSE", "dir": "LONG",
     "shares": 1, "price": 4426.84, "stop": 4426.84, "reason": "STOP", "pnl": -8.15,
     "balance": 4980.43,
     "signal_details": "entry=4434.10 comm=0.89"},
]

APEX_STATE = {
    "ticker":        "GC=F",
    "capital":       5000.0,
    "balance":       4980.43,
    "position":      None,
    "today":         None,
    "bar_count":     0,
    "prior_close":   0,
    "traded_today":  False,
    "total_trades":  4,
    "total_pnl":     -19.57,
    "wins":          1,
    "losses":        3,
}

# ── Zone Refinement (1H) — replay Mar 18-23 on real GC=F data ────────────────
# 10 closed trades: 5W / 5L, Net P&L: +$649.24
# Strategy caught gold's crash from $5,000 → $4,200 via supply zones

ZONE_TRADES = [
    # Mar 18 02:00 — SHORT from supply zone, TARGET hit
    {"date": "2026-03-18", "time": "02:00", "action": "SELL",  "dir": "SHORT",
     "shares": 4, "price": 5013.80, "stop": 5022.317, "reason": "ZONE", "pnl": "",
     "balance": 5000.00,
     "signal_details": "zone=supply htf=[4988,5022] refined=[5004.700,5017.300] rr=5.1"},
    {"date": "2026-03-18", "time": "07:00", "action": "CLOSE", "dir": "SHORT",
     "shares": 4, "price": 4970.10, "stop": 5022.317, "reason": "TARGET", "pnl": 170.81,
     "balance": 5170.81,
     "signal_details": "entry=5013.800 comm=3.99 zone=supply"},
    # Mar 18 18:00 — SHORT from supply zone, STOP
    {"date": "2026-03-18", "time": "18:00", "action": "SELL",  "dir": "SHORT",
     "shares": 5, "price": 4837.10, "stop": 4849.845, "reason": "ZONE", "pnl": "",
     "balance": 5170.81,
     "signal_details": "zone=supply htf=[4806,4852] refined=[4830.500,4845.000] rr=3.0"},
    {"date": "2026-03-18", "time": "21:00", "action": "CLOSE", "dir": "SHORT",
     "shares": 5, "price": 4849.845, "stop": 4849.845, "reason": "STOP", "pnl": -68.57,
     "balance": 5102.24,
     "signal_details": "entry=4837.100 comm=4.84 zone=supply"},
    # Mar 18 22:00 — SHORT from supply zone, TARGET hit
    {"date": "2026-03-18", "time": "22:00", "action": "SELL",  "dir": "SHORT",
     "shares": 5, "price": 4859.50, "stop": 4868.263, "reason": "ZONE", "pnl": "",
     "balance": 5102.24,
     "signal_details": "zone=supply htf=[4834,4869] refined=[4842.600,4863.400] rr=5.7"},
    {"date": "2026-03-19", "time": "02:00", "action": "CLOSE", "dir": "SHORT",
     "shares": 5, "price": 4809.30, "stop": 4868.263, "reason": "TARGET", "pnl": 246.17,
     "balance": 5348.40,
     "signal_details": "entry=4859.500 comm=4.83 zone=supply"},
    # Mar 20 02:00 — LONG from demand zone, STOP
    {"date": "2026-03-20", "time": "02:00", "action": "BUY",   "dir": "LONG",
     "shares": 1, "price": 4670.30, "stop": 4590.805, "reason": "ZONE", "pnl": "",
     "balance": 5348.40,
     "signal_details": "zone=demand htf=[4595,4672] refined=[4595.400,4672.300] rr=4.4"},
    {"date": "2026-03-20", "time": "10:00", "action": "CLOSE", "dir": "LONG",
     "shares": 1, "price": 4590.805, "stop": 4590.805, "reason": "STOP", "pnl": -80.42,
     "balance": 5267.98,
     "signal_details": "entry=4670.300 comm=0.93 zone=demand"},
    # Mar 20 11:00 — SHORT from supply zone, STOP
    {"date": "2026-03-20", "time": "11:00", "action": "SELL",  "dir": "SHORT",
     "shares": 5, "price": 4555.30, "stop": 4570.466, "reason": "ZONE", "pnl": "",
     "balance": 5267.98,
     "signal_details": "zone=supply htf=[4553,4566] refined=[4552.700,4565.900] rr=3.3"},
    {"date": "2026-03-20", "time": "12:00", "action": "CLOSE", "dir": "SHORT",
     "shares": 5, "price": 4570.466, "stop": 4570.466, "reason": "STOP", "pnl": -80.39,
     "balance": 5187.59,
     "signal_details": "entry=4555.300 comm=4.56 zone=supply"},
    # Mar 20 14:00 — SHORT from supply zone, TARGET hit Mar 22
    {"date": "2026-03-20", "time": "14:00", "action": "SELL",  "dir": "SHORT",
     "shares": 2, "price": 4500.70, "stop": 4545.941, "reason": "ZONE", "pnl": "",
     "balance": 5187.59,
     "signal_details": "zone=supply htf=[4463,4541] refined=[4526.100,4541.400] rr=3.0"},
    {"date": "2026-03-22", "time": "20:00", "action": "CLOSE", "dir": "SHORT",
     "shares": 2, "price": 4364.977, "stop": 4545.941, "reason": "TARGET", "pnl": 269.67,
     "balance": 5457.26,
     "signal_details": "entry=4500.700 comm=1.77 zone=supply"},
    # Mar 22 21:00 — SHORT from supply zone, TARGET hit
    {"date": "2026-03-22", "time": "21:00", "action": "SELL",  "dir": "SHORT",
     "shares": 6, "price": 4390.00, "stop": 4397.994, "reason": "ZONE", "pnl": "",
     "balance": 5457.26,
     "signal_details": "zone=supply htf=[4364,4396] refined=[4370.200,4393.600] rr=3.0"},
    {"date": "2026-03-22", "time": "22:00", "action": "CLOSE", "dir": "SHORT",
     "shares": 6, "price": 4366.019, "stop": 4397.994, "reason": "TARGET", "pnl": 138.63,
     "balance": 5595.90,
     "signal_details": "entry=4390.000 comm=5.25 zone=supply"},
    # Mar 22 23:00 — SHORT from supply zone, TARGET hit Mar 23
    {"date": "2026-03-22", "time": "23:00", "action": "SELL",  "dir": "SHORT",
     "shares": 2, "price": 4355.30, "stop": 4393.990, "reason": "ZONE", "pnl": "",
     "balance": 5595.90,
     "signal_details": "zone=supply htf=[4320,4390] refined=[4367.500,4389.600] rr=3.0"},
    {"date": "2026-03-23", "time": "02:00", "action": "CLOSE", "dir": "SHORT",
     "shares": 2, "price": 4239.230, "stop": 4393.990, "reason": "TARGET", "pnl": 230.42,
     "balance": 5826.32,
     "signal_details": "entry=4355.300 comm=1.72 zone=supply"},
    # Mar 23 03:00 — SHORT from supply zone, STOP
    {"date": "2026-03-23", "time": "03:00", "action": "SELL",  "dir": "SHORT",
     "shares": 6, "price": 4205.70, "stop": 4217.213, "reason": "ZONE", "pnl": "",
     "balance": 5826.32,
     "signal_details": "zone=supply htf=[4176,4215] refined=[4191.300,4213.000] rr=3.0"},
    {"date": "2026-03-23", "time": "04:00", "action": "CLOSE", "dir": "SHORT",
     "shares": 6, "price": 4217.213, "stop": 4217.213, "reason": "STOP", "pnl": -74.13,
     "balance": 5752.19,
     "signal_details": "entry=4205.700 comm=5.05 zone=supply"},
    # Mar 23 06:00 — SHORT from supply zone, STOP
    {"date": "2026-03-23", "time": "06:00", "action": "SELL",  "dir": "SHORT",
     "shares": 2, "price": 4270.00, "stop": 4320.616, "reason": "ZONE", "pnl": "",
     "balance": 5752.19,
     "signal_details": "zone=supply htf=[4258,4316] refined=[4257.700,4316.300] rr=3.0"},
    {"date": "2026-03-23", "time": "07:00", "action": "CLOSE", "dir": "SHORT",
     "shares": 2, "price": 4320.616, "stop": 4320.616, "reason": "STOP", "pnl": -102.95,
     "balance": 5649.24,
     "signal_details": "entry=4270.000 comm=1.72 zone=supply"},
]

ZONE_STATE = {
    "ticker":        "GC=F",
    "capital":       5000.0,
    "balance":       5649.24,
    "position":      None,
    "zones":         [],
    "zones_date":    None,
    "total_trades":  10,
    "total_pnl":     649.24,
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

    seed_csv(DATA_DIR / "paper_trades.csv", APEX_TRADES,  "ClaudeAPEX trades")
    seed_json(DATA_DIR / "paper_state.json", APEX_STATE,  "ClaudeAPEX state")

    seed_csv(DATA_DIR / "zone_trades.csv",  ZONE_TRADES,  "Zone Refinement trades")
    seed_json(DATA_DIR / "zone_state.json", ZONE_STATE,   "Zone Refinement state")

    print("Seed complete.")
