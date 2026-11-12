"""Stock footage provider slot (optional). Provider "pexels": free portrait video clips for idea reels.
Key: Windows Credential Manager (service ai-reel-studio, entry pexels). Pexels asks for a visible credit, so the
Instagram pack and summary say "Video: Pexels". Without a key, idea reels use animated text scenes only."""
import json
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

import keyring

from common import FFPROBE

PROVIDER = "pexels"
SERVICE, ENTRY = "ai-reel-studio", "pexels"
CREDIT = "Video footage: Pexels (pexels.com)"


def available():
    try:
        return bool(keyring.get_password(SERVICE, ENTRY))
    except Exception:
        return False


def save_key(value):
    keyring.set_password(SERVICE, ENTRY, value.strip())


def _get(url, key):
    req = urllib.request.Request(url, headers={"Authorization": key, "User-Agent": "AIReelStudio/1.0"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


def fetch_clip(query, dest_dir, min_seconds=3.0, used=()):
    """Downloads one portrait clip for the query. Returns (path, width, height, duration, page_url) or None."""
    key = keyring.get_password(SERVICE, ENTRY)
    if not key or not query:
        return None
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    url = ("https://api.pexels.com/videos/search?" +
           urllib.parse.urlencode({"query": query, "orientation": "portrait", "size": "medium", "per_page": 15}))
    try:
        res = _get(url, key)
    except Exception:
        return None
    for v in res.get("videos", []):
        if v["id"] in used or v.get("duration", 0) < min_seconds:
            continue
        files = [f for f in v["video_files"] if f.get("file_type") == "video/mp4" and f.get("width") and f.get("height")
                 and f["height"] > f["width"]]
        files.sort(key=lambda f: abs(f["height"] - 1920))  # closest to 1080x1920 without being huge
        if not files:
            continue
        f = files[0]
        out = dest_dir / f"pexels_{v['id']}.mp4"
        if not out.exists():
            try:
                req = urllib.request.Request(f["link"], headers={"User-Agent": "AIReelStudio/1.0"})
                with urllib.request.urlopen(req, timeout=120) as r, open(out, "wb") as fh:
                    fh.write(r.read())
            except Exception:
                continue
        return out, f["width"], f["height"], float(v["duration"]), v.get("url"), v["id"]
    return None
