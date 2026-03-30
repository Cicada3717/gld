"""
seed_data.py — Initialise fresh state files on Railway if missing/empty.
Runs once at startup before the paper trader starts.
"""

import json
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", Path(__file__).parent))

ZONE_STATE = {
    "ticker":        "GC=F",
    "capital":       10000.0,
    "balance":       10000.0,
    "position":      None,
    "zones":         [],
    "zones_date":    None,
    "total_trades":  0,
    "total_pnl":     0.0,
    "wins":          0,
    "losses":        0,
}


def seed_json(path: Path, data: dict, label: str):
    """Write JSON state only if the file doesn't exist or is empty."""
    if path.exists() and path.stat().st_size > 10:
        print(f"  {label}: state already exists -- skipping seed")
        return
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  {label}: state seeded -> {path}")


if __name__ == "__main__":
    print("Initialising state files...")
    seed_json(DATA_DIR / "zone_state.json", ZONE_STATE, "Zone Refinement state")
    print("Init complete.")
