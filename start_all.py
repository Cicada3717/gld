"""
start_all.py - lightweight process supervisor for Railway deploys.

Starts the Streamlit dashboard immediately so the web service can become
healthy, while replay/bootstrap tasks and live traders run in the background.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable
PORT = os.environ.get("PORT", "8501")

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
    replay = _spawn("replay.py", [PYTHON, "replay.py"])
    replay.wait()
    if shutdown_requested:
        return
    _spawn("zone_paper_trader.py", [PYTHON, "zone_paper_trader.py", "--ticker", "GC=F", "--capital", "10000"])


def _run_btc_lane() -> None:
    replay = _spawn("btc_replay.py", [PYTHON, "btc_replay.py"])
    replay.wait()
    if shutdown_requested:
        return
    _spawn("lfv_paper_trader.py", [PYTHON, "lfv_paper_trader.py", "--capital", "10000"])


def main() -> int:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    streamlit = _spawn(
        "lfv_dashboard.py",
        [
            PYTHON,
            "-m",
            "streamlit",
            "run",
            "lfv_dashboard.py",
            "--server.port",
            PORT,
            "--server.address",
            "0.0.0.0",
        ],
    )

    gld_thread = threading.Thread(target=_run_gld_lane, name="gld-lane", daemon=True)
    btc_thread = threading.Thread(target=_run_btc_lane, name="btc-lane", daemon=True)
    gld_thread.start()
    btc_thread.start()

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
