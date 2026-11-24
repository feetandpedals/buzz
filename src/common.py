"""Shared paths and tool discovery."""
import glob
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_env_file(path):
    """Reads buzz.env (NAME=value lines) into the environment. Values already set (systemd, the shell) win."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v:
            os.environ.setdefault(k, v)


_load_env_file(ROOT / "buzz.env")


def _threads():
    try:
        n = int(os.environ.get("BUZZ_THREADS") or 0)
    except ValueError:
        n = 0
    return max(1, n if n > 0 else min(4, os.cpu_count() or 1))


THREADS = _threads()  # CPU threads one reel may use; numeric libraries read these before they load
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_v, str(THREADS))

REELS_IN = ROOT / "Reels In"
REELS_OUT = ROOT / "Reels Out"
WORK = ROOT / "Work"

HISTORY_DAYS = 15  # My reels shows reels touched within this many days


VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".mts", ".3gp"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".bmp", ".tif", ".tiff"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


def font_path(windows_file, bundled_file):
    """The Windows system font when running on Windows, otherwise a free font shipped in fonts/."""
    w = Path("C:/Windows/Fonts") / windows_file
    if sys.platform == "win32" and w.exists():
        return w
    return ROOT / "fonts" / bundled_file


def find_tool(name):
    p = shutil.which(name)
    if p:
        return p
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    hits = glob.glob(str(base / "Gyan.FFmpeg*" / "*" / "bin" / f"{name}.exe"))
    if hits:
        return hits[0]
    for d in (ROOT / "bin", Path.home() / ".local" / "bin", Path("/usr/local/bin"), Path("/opt/ffmpeg/bin")):  # Linux / server installs
        if (d / name).exists():
            return str(d / name)
    raise FileNotFoundError(f"{name} not found")


FFMPEG = find_tool("ffmpeg")
FFPROBE = find_tool("ffprobe")
