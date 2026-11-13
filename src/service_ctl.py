"""Start and stop the background worker on any platform.
Windows: the "Buzz Worker" scheduled task. Linux: the systemd user service named in BUZZ_WORKER_UNIT (default buzz-worker),
or, when systemd is not available, a plain background process of worker.py."""
import os
import signal
import subprocess
import sys
from pathlib import Path

WINDOWS = sys.platform == "win32"
SRC = Path(__file__).resolve().parent
UNIT = os.environ.get("BUZZ_WORKER_UNIT", "buzz-worker")


def _systemctl(*args):
    try:
        return subprocess.run(["systemctl", "--user", *args], capture_output=True, timeout=20).returncode == 0
    except Exception:
        return False


def start_worker(task_name):
    if WINDOWS:
        subprocess.run(["schtasks", "/Change", "/TN", task_name, "/ENABLE"], capture_output=True)
        subprocess.run(["schtasks", "/Run", "/TN", task_name], capture_output=True)
        return
    if _systemctl("start", UNIT):
        return
    subprocess.Popen([sys.executable, str(SRC / "worker.py")], cwd=str(SRC.parent), start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)


def stop_worker(task_name, lock):
    lock = Path(lock)
    if WINDOWS:
        subprocess.run(["schtasks", "/Change", "/TN", task_name, "/DISABLE"], capture_output=True)
        if lock.exists():
            subprocess.run(["taskkill", "/PID", lock.read_text().strip(), "/F"], capture_output=True)
            lock.unlink(missing_ok=True)
        return
    _systemctl("stop", UNIT)
    if lock.exists():
        try:
            os.kill(int(lock.read_text().strip()), signal.SIGTERM)
        except (OSError, ValueError):
            pass
        lock.unlink(missing_ok=True)
