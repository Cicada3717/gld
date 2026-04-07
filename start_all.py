"""
start_all.py - process supervisor for Railway deploys (GLD only).

Starts the Streamlit dashboard immediately so Railway health check passes,
then runs replay.py to bootstrap state from Mar 18, then starts the live
GC=F zone paper trader.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path


ROOT   = Path(__file__).resolve().parent
PYTHON = sys.executable
PORT   = os.environ.get("PORT", "8501")

children: list[subprocess.Popen] = []
shutdown_requested = False


def _spawn(name: str, args: list[str]) -> subprocess.Popen:
    proc = subprocess.Popen(args, cwd=ROOT)
    children.append(proc)
    print(f"[supervisor] started {name} (pid={proc.pid})", flush=True)
    return proc


def _terminate_children() -> None:
    global shutdown_requested
    if shutdown_requested:
        return
    shutdown_requested = True
    print("[supervisor] shutting down child processes", flush=True)
    for proc in children:
        if proc.poll() is None:
            proc.terminate()
    deadline = time.time() + 10
    for proc in children:
        if proc.poll() is None:
            remaining = max(0.0, deadline - time.time())
            try:
                proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                proc.kill()


def _handle_signal(signum, _frame) -> None:
    print(f"[supervisor] received signal {signum}", flush=True)
    _terminate_children()
    raise SystemExit(0)


def _run_gld_lane() -> None:
    """Run replay first to bootstrap state, then start the live trader."""
    replay = _spawn("replay.py", [PYTHON, "replay.py"])
    replay.wait()
    if shutdown_requested:
        return
    _spawn("zone_paper_trader.py",
           [PYTHON, "zone_paper_trader.py", "--ticker", "GC=F", "--capital", "10000"])


def main() -> int:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # Start dashboard first — Railway health check needs it up immediately
    streamlit = _spawn(
        "lfv_dashboard.py",
        [PYTHON, "-m", "streamlit", "run", "lfv_dashboard.py",
         "--server.port", PORT, "--server.address", "0.0.0.0"],
    )

    # GLD lane runs in background thread
    gld_thread = threading.Thread(target=_run_gld_lane, name="gld-lane", daemon=True)
    gld_thread.start()

    try:
        while True:
            code = streamlit.poll()
            if code is not None:
                print(f"[supervisor] streamlit exited with code {code}", flush=True)
                return code
            for proc in list(children):
                if proc is streamlit:
                    continue
                code = proc.poll()
                if code not in (None, 0):
                    print(f"[supervisor] child pid={proc.pid} exited with code {code}", flush=True)
            time.sleep(1)
    finally:
        _terminate_children()


if __name__ == "__main__":
    raise SystemExit(main())
