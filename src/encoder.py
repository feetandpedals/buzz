"""Picks the video encoder. Uses a graphics-card encoder (NVIDIA, Intel or AMD) when one works AND its picture quality
is at least as good as the CPU encoder on a test clip; otherwise the CPU encoder (libx264). The choice is remembered in
Work/encoder.json and checked again when FFmpeg changes. A failed graphics-card render is redone on the CPU by render.py."""
import json
import re
import subprocess
from pathlib import Path

from common import FFMPEG, WORK

CACHE = WORK / "encoder.json"
CPU = {"name": "CPU (software)", "codec": "libx264"}
# quality targets from best to still-excellent; the first that is at least as good as the CPU encoder wins
CANDIDATES = [
    ("NVIDIA graphics card", "h264_nvenc", lambda q: ["-preset", "p7", "-tune", "hq", "-rc", "vbr", "-cq", str(q), "-b:v", "0",
                                                       "-spatial-aq", "1", "-temporal-aq", "1", "-bf", "2"], (15, 13, 11)),
    ("Intel graphics", "h264_qsv", lambda q: ["-preset", "veryslow", "-global_quality", str(q), "-look_ahead", "1"], (15, 13, 11)),
    ("AMD graphics card", "h264_amf", lambda q: ["-quality", "quality", "-rc", "cqp", "-qp_i", str(q), "-qp_p", str(q + 1), "-qp_b", str(q + 2)],
     (15, 13, 11)),
]
_cur = None


def _ffmpeg_version():
    r = subprocess.run([FFMPEG, "-version"], capture_output=True, text=True)
    return (r.stdout.splitlines() or [""])[0]


def _listed():
    r = subprocess.run([FFMPEG, "-hide_banner", "-encoders"], capture_output=True, text=True)
    return r.stdout


def _ssim(encoded, source):
    r = subprocess.run([FFMPEG, "-hide_banner", "-i", str(encoded), "-i", str(source), "-lavfi", "ssim", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"All:([0-9.]+)", r.stderr)
    return float(m.group(1)) if m else 0.0


def _detect():
    tmp = WORK / "_enc_test"
    tmp.mkdir(parents=True, exist_ok=True)
    src = tmp / "src.mkv"
    gen = ["-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=30:d=2", "-vf", "noise=alls=10:allf=t,format=yuv420p", "-c:v", "ffv1", str(src)]
    if subprocess.run([FFMPEG, "-v", "error", "-y"] + gen, capture_output=True).returncode:
        return dict(CPU)
    ref = tmp / "cpu.mp4"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(src), "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", str(ref)],
                   capture_output=True)
    base = _ssim(ref, src)
    listed = _listed()
    best = dict(CPU)
    for label, codec, args, quals in CANDIDATES:
        if codec not in listed:
            continue
        for q in quals:
            out = tmp / f"{codec}.mp4"
            r = subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(src), "-c:v", codec] + args(q) + ["-pix_fmt", "yuv420p", str(out)],
                               capture_output=True, timeout=120)
            if r.returncode or not out.exists():
                break  # this card is not usable here
            if _ssim(out, src) >= base:
                best = {"name": label, "codec": codec, "quality": q}
                break
        if best["codec"] != "libx264":
            break
    for f in tmp.glob("*"):
        f.unlink(missing_ok=True)
    tmp.rmdir()
    best["ffmpeg"] = _ffmpeg_version()
    return best


def current():
    """The encoder in use (remembered; found once per FFmpeg version)."""
    global _cur
    if _cur is not None:
        return _cur
    try:
        data = json.loads(CACHE.read_text(encoding="utf-8"))
        if data.get("ffmpeg") == _ffmpeg_version():
            _cur = data
            return _cur
    except Exception:
        pass
    try:
        _cur = _detect()
    except Exception:
        _cur = dict(CPU, ffmpeg=_ffmpeg_version())
    try:
        CACHE.write_text(json.dumps(_cur), encoding="utf-8")
    except Exception:
        pass
    return _cur


def label():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8")).get("name") or CPU["name"]
    except Exception:
        return "not checked yet (found on the first reel)"


def args(crf, cpu_only=False):
    """ffmpeg video-encoder arguments for the chosen encoder; crf is the CPU quality setting."""
    e = dict(CPU) if cpu_only else current()
    if e["codec"] == "libx264":
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf)]
    for _, codec, build, _q in CANDIDATES:
        if codec == e["codec"]:
            return ["-c:v", codec] + build(e["quality"])
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf)]


def uses_gpu():
    return current()["codec"] != "libx264"
