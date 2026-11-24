"""End-to-end check for a server install: queues a 30-second idea reel with the free voice and music, waits for the
running worker to finish it, and checks the result (length, size, picture, voice). Run from the Buzz folder after
./setup.sh and after installing the free voice on Settings:
    .venv/bin/python tests/smoke_reel.py            (uses the studio's Claude key; costs a few cents)
For a key-free test, run tests/fake_claude.py and set BUZZ_CLAUDE_URL and BUZZ_ANTHROPIC for the worker first."""
import json
import subprocess
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / "src"))
from common import FFPROBE, REELS_IN, REELS_OUT, WORK  # noqa: E402
import voice_provider  # noqa: E402

assert voice_provider.kokoro_ready(), "Install the free voice on Settings first."
name = f"smoke test {time.strftime('%Y%m%d-%H%M%S')}"
folder = REELS_IN / name
folder.mkdir(parents=True)
(folder / "idea.txt").write_text("Why an early morning bike ride is the best start to a weekend.", encoding="utf-8")
(folder / "options.json").write_text(json.dumps({"mode": "prompt", "seconds": 30, "language": "English", "music": "create",
                                                 "voice": True, "voice_name": "kokoro:af_heart", "background": "gradient",
                                                 "owner": ""}), encoding="utf-8")
print(f"Queued '{name}'. The worker picks it up after 90 quiet seconds, then renders.")
job = WORK / "jobs" / name / "job.json"
t0 = time.time()
while time.time() - t0 < 1800:
    st = json.loads(job.read_text(encoding="utf-8")) if job.exists() else {}
    if st.get("status") in ("done", "failed"):
        break
    time.sleep(10)
print(f"Finished in {time.time() - t0:.0f} s with status {st.get('status')}: {st.get('error', '')}")
assert st.get("status") == "done", (WORK / "jobs" / name / "error.log").read_text() if (WORK / "jobs" / name / "error.log").exists() else st
assert not (WORK / "jobs" / name / "voice_error.log").exists(), (WORK / "jobs" / name / "voice_error.log").read_text()
reel = next((REELS_OUT / name).glob("*.mp4"))
probe = json.loads(subprocess.run([FFPROBE, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(reel)],
                                  capture_output=True, text=True).stdout)
v = next(s for s in probe["streams"] if s["codec_type"] == "video")
a = next(s for s in probe["streams"] if s["codec_type"] == "audio")
dur = float(probe["format"]["duration"])
plan = json.loads((WORK / "jobs" / name / "plan.json").read_text(encoding="utf-8"))
print(f"Reel: {reel} | {dur:.1f} s | {v['width']}x{v['height']} | audio {a['codec_name']} | "
      f"{reel.stat().st_size / 1e6:.1f} MB | voice track: {bool(plan.get('voice'))}")
assert (v["width"], v["height"]) == (1080, 1920)
assert 25 <= dur <= 45, dur
assert plan.get("voice"), "the reel has no voiceover"
print("PASS")
