"""Background worker: watches `Reels In`, runs one job at a time, survives restarts. No UI dependency."""
import json
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import REELS_IN, WORK  # noqa: E402

LOG = WORK / "logs"
LOG.mkdir(parents=True, exist_ok=True)
logging.basicConfig(filename=LOG / "worker.log", level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
STABLE_SECS = 90  # a folder is "ready" when nothing in it changed for this long (copy finished)


def _lock():
    f = WORK / "worker.lock"
    if f.exists():
        try:
            pid = int(f.read_text())
            os.kill(pid, 0)  # raises if not running
            return False
        except (OSError, ValueError):
            pass
    f.write_text(str(os.getpid()))
    return True


def _ready(folder):
    files = [p for p in folder.rglob("*") if p.is_file()]
    return bool(files) and time.time() - max(p.stat().st_mtime for p in files) > STABLE_SECS


def _status(folder):
    f = WORK / "jobs" / folder.name / "job.json"
    return json.loads(f.read_text(encoding="utf-8")).get("status") if f.exists() else None


def main():
    if not _lock():
        print("Worker already running.")
        return
    import pipeline  # heavy imports after the lock check
    import notify
    REELS_IN.mkdir(exist_ok=True)
    logging.info("worker started pid=%s", os.getpid())
    while True:
        try:
            (WORK / "heartbeat.txt").write_text(time.strftime("%Y-%m-%d %H:%M:%S"))
            for folder in sorted(p for p in REELS_IN.iterdir() if p.is_dir()):
                st = _status(folder)
                if st == "done" or st == "failed" or not _ready(folder):
                    continue  # failed jobs wait for a retry flag
                logging.info("job start: %s (was %s)", folder.name, st)
                ok = pipeline.run_job(folder)
                logging.info("job %s: %s", "finished" if ok else "FAILED", folder.name)
                notify.send("Reel ready" if ok else "Reel failed", f"{folder.name}: " + (
                    "finished. Open the status page to watch it." if ok else "something went wrong. "
                    "Open the status page and click Try again."), "tada" if ok else "warning",
                    "default" if ok else "high")
            import revise  # change notes written by the web page: one job queue, one render at a time
            for jd in sorted((WORK / "jobs").glob("*")):
                req = jd / "revision_request.txt"
                if req.exists():
                    note = req.read_text(encoding="utf-8-sig").strip()
                    req.unlink()
                    logging.info("revision start: %s | %s", jd.name, note[:120])
                    (jd / "revision_result.json").write_text(json.dumps({"state": "working", "note": note}), encoding="utf-8")
                    res = revise.revise(jd.name, note)
                    res.update(state="done" if res["ok"] else "failed", note=note)
                    (jd / "revision_result.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
                    logging.info("revision %s: %s", res["state"], jd.name)
                    notify.send("Change done" if res["ok"] else "Change failed", f"{jd.name}: " + (
                        "new version ready." if res["ok"] else "could not apply the change."),
                        "pencil2" if res["ok"] else "warning")
            import cleanup  # nightly tidy-up of reels older than the history window
            if cleanup.due_tonight():
                res = cleanup.run()
                logging.info("cleanup: moved %s reel(s) to trash (%s), purged %s", len(res["moved"]), cleanup.mb(res["bytes"]),
                             cleanup.mb(res["purged_bytes"]))
            for folder in REELS_IN.iterdir():  # retry flag: put a file named retry.flag in a failed folder
                flag = folder / "retry.flag"
                if folder.is_dir() and flag.exists():
                    flag.unlink()
                    jf = WORK / "jobs" / folder.name / "job.json"
                    if jf.exists():
                        jf.unlink()
        except Exception:
            logging.exception("worker loop error")
        time.sleep(15)


if __name__ == "__main__":
    main()
