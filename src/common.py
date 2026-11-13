"""Shared paths and tool discovery."""
import glob
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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
