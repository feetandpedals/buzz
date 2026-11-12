"""Nightly tidy-up. Reels older than HISTORY_DAYS are moved to Work\\_trash, then deleted for good after TRASH_DAYS.
Never touches: running reels, reels marked Keep, folders you dropped into Reels In yourself, accounts or keys."""
import json
import shutil
import time
from pathlib import Path

from common import HISTORY_DAYS, REELS_IN, REELS_OUT, WORK

TRASH = WORK / "_trash"
TRASH_DAYS = 3
STATE = WORK / "cleanup_state.json"
RUN_HOUR = 3  # the worker runs it once a night after this hour


def last_touched(jd):
    times = [(jd / n).stat().st_mtime for n in ("job.json", "revision_result.json") if (jd / n).exists()]
    reel = REELS_OUT / jd.name / f"{jd.name} reel.mp4"
    if reel.exists():
        times.append(reel.stat().st_mtime)
    return max(times) if times else 0


def size_of(p):
    p = Path(p)
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0


def is_kept(jd):
    return (jd / "keep.flag").exists()


def set_kept(name, kept):
    f = WORK / "jobs" / name / "keep.flag"
    if kept:
        f.write_text("kept", encoding="utf-8")
    elif f.exists():
        f.unlink()


def _busy(jd):
    try:
        st = json.loads((jd / "job.json").read_text(encoding="utf-8")).get("status")
    except Exception:
        st = None
    return st == "running" or (jd / "revision_request.txt").exists() or (jd / "revision_result.json").exists() and \
        '"working"' in (jd / "revision_result.json").read_text(encoding="utf-8", errors="ignore")


def candidates():
    """Reels that are due for removal: [{name, parts: [(label, path)], bytes}]."""
    cutoff = time.time() - HISTORY_DAYS * 86400
    out = []
    for jd in sorted((WORK / "jobs").glob("*")):
        if not (jd / "job.json").exists() or jd.name.startswith("_") or is_kept(jd) or _busy(jd):
            continue
        if last_touched(jd) >= cutoff:
            continue
        parts = [("jobs", jd)]
        if (REELS_OUT / jd.name).exists():
            parts.append(("out", REELS_OUT / jd.name))
        src = REELS_IN / jd.name
        if src.exists() and (src / "options.json").exists():  # made through the page; hand-dropped folders are left alone
            parts.append(("in", src))
        out.append({"name": jd.name, "parts": parts, "bytes": sum(size_of(p) for _, p in parts)})
    return out


def any_running():
    for jd in (WORK / "jobs").glob("*"):
        if (jd / "job.json").exists() and _busy(jd):
            return True
    return False


def _read_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def purge_trash():
    freed = 0
    if TRASH.exists():
        for d in TRASH.iterdir():
            if d.is_dir() and time.time() - d.stat().st_mtime > TRASH_DAYS * 86400:
                freed += size_of(d)
                shutil.rmtree(d, ignore_errors=True)
    return freed


def run(dry=False):
    """Move due reels to the trash and empty old trash. Returns a summary dict."""
    items = candidates()
    summary = {"when": time.strftime("%Y-%m-%d %H:%M"), "dry": dry, "moved": [i["name"] for i in items],
               "bytes": sum(i["bytes"] for i in items), "purged_bytes": 0}
    if dry:
        return summary
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for i in items:
        for label, p in i["parts"]:
            dest = TRASH / stamp / i["name"] / label
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(p), str(dest))
            except Exception:
                pass
    (TRASH / stamp).mkdir(parents=True, exist_ok=True) if items else None
    summary["purged_bytes"] = purge_trash()
    state = _read_state()
    state.update(last=summary, last_day=time.strftime("%Y-%m-%d"))
    STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    return summary


def due_tonight():
    """True once per day, after RUN_HOUR, when no reel is being made."""
    now = time.localtime()
    return now.tm_hour >= RUN_HOUR and _read_state().get("last_day") != time.strftime("%Y-%m-%d") and not any_running()


def trashed():
    """Items waiting in the trash: [{stamp, name, bytes}]."""
    out = []
    if TRASH.exists():
        for d in sorted(TRASH.iterdir(), reverse=True):
            for r in d.iterdir() if d.is_dir() else []:
                out.append({"stamp": d.name, "name": r.name, "bytes": size_of(r)})
    return out


def restore(stamp, name):
    """Put a trashed reel back where it was and refresh its date so it is not removed again straight away."""
    base = TRASH / stamp / name
    homes = {"jobs": WORK / "jobs" / name, "out": REELS_OUT / name, "in": REELS_IN / name}
    for label, home in homes.items():
        p = base / label
        if p.exists() and not home.exists():
            shutil.move(str(p), str(home))
    jf = WORK / "jobs" / name / "job.json"
    if jf.exists():
        jf.touch()
    shutil.rmtree(base, ignore_errors=True)
    return True


def mb(n):
    return f"{n / 1e6:.0f} MB" if n >= 1e6 else f"{n / 1e3:.0f} KB"
