"""Real-time progress for the page. The worker calls report() as it goes; the page reads Work/jobs/<name>/progress.json.
'ceil' is the highest the bar may creep to before the next report arrives, so it moves smoothly but never lies."""
import json
import time
from pathlib import Path

_JOB = None
_T0 = 0.0


def start(job_dir):
    global _JOB, _T0
    _JOB = Path(job_dir)
    _T0 = time.time()
    report(1, "Starting", 3)


def report(pct, text, ceil=None):
    if _JOB is None:
        return
    try:
        (_JOB / "progress.json").write_text(json.dumps({
            "pct": round(float(pct), 1), "text": text,
            "ceil": round(float(ceil if ceil is not None else min(pct + 5, 99)), 1), "t": time.time(), "t0": _T0}), encoding="utf-8")
    except OSError:
        pass


def stage(lo, hi, i, n, text):
    """Item i of n inside the stretch lo..hi of the whole job."""
    n = max(n, 1)
    report(lo + (hi - lo) * i / n, text, lo + (hi - lo) * (i + 1) / n)
