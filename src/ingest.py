"""Catalogue media in a reel folder (read-only on originals)."""
import json
import subprocess
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps
import pillow_heif

pillow_heif.register_heif_opener()

import progress
from common import FFPROBE, VIDEO_EXT, IMAGE_EXT, AUDIO_EXT


def _probe(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-print_format", "json", "-show_format",
                        "-show_streams", str(path)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return None
    return json.loads(r.stdout)


def _fps(s):
    try:
        a, b = s.split("/")
        return float(a) / float(b) if float(b) else 0.0
    except Exception:
        return 0.0


def _quality(frame_bgr):
    g = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, (320, int(320 * g.shape[0] / g.shape[1]))) if g.shape[1] > 320 else g
    return {"blur": round(float(cv2.Laplacian(g, cv2.CV_64F).var()), 1),
            "brightness": round(float(g.mean()), 1)}


def _dhash(frame_bgr):
    g = cv2.cvtColor(cv2.resize(frame_bgr, (9, 8)), cv2.COLOR_BGR2GRAY)
    return "".join("1" if x else "0" for x in (g[:, 1:] > g[:, :-1]).flatten())


def _read_frame(path, t):
    cap = cv2.VideoCapture(str(path))
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, f = cap.read()
    cap.release()
    return f if ok else None


def _imread(path):
    # PIL handles HEIC, Unicode paths and EXIF rotation; shrink for speed
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((640, 640))
        return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)


def catalogue(folder):
    folder = Path(folder)
    items, audio, brief, skipped = [], [], None, []
    files = [p for p in sorted(folder.rglob("*")) if p.is_file()]
    for k, p in enumerate(files):
        progress.stage(2, 10, k, len(files), f"Reading your files ({k + 1} of {len(files)})")
        ext = p.suffix.lower()
        if p.name.lower().startswith("_logo"):  # the uploaded logo is not a photo for the reel
            continue
        if ext == ".txt" and brief is None:
            brief = p.read_text(encoding="utf-8", errors="replace").strip()
            continue
        if ext in AUDIO_EXT:
            info = _probe(p)
            if info:
                audio.append({"path": str(p), "duration": float(info["format"].get("duration", 0))})
            continue
        if ext not in VIDEO_EXT | IMAGE_EXT:
            continue
        ctime = datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")
        rec = {"id": len(items) + 1, "path": str(p), "name": p.name, "size": p.stat().st_size,
               "modified": ctime}
        try:
            if ext in VIDEO_EXT:
                info = _probe(p)
                vs = next((s for s in (info or {}).get("streams", []) if s["codec_type"] == "video"), None)
                if not vs:
                    raise ValueError("no video stream")
                w, h = int(vs["width"]), int(vs["height"])
                rot = 0
                for sd in vs.get("side_data_list", []):
                    if "rotation" in sd:
                        rot = int(sd["rotation"])
                if abs(rot) in (90, 270):
                    w, h = h, w
                dur = float(info["format"].get("duration") or vs.get("duration") or 0)
                rec.update(kind="video", duration=round(dur, 2), width=w, height=h,
                           fps=round(_fps(vs.get("avg_frame_rate", "0/1")), 2),
                           codec=vs.get("codec_name"), has_audio=any(
                               s["codec_type"] == "audio" for s in info["streams"]),
                           hdr="smpte2084" in str(vs.get("color_transfer", "")) or
                               "arib" in str(vs.get("color_transfer", "")))
                ct = info["format"].get("tags", {}).get("creation_time")
                if ct:
                    rec["created"] = ct
                frame = _read_frame(p, min(dur / 2, max(dur - 0.1, 0)))
            else:
                with Image.open(p) as im:
                    w, h = im.size
                    exif = im.getexif()
                    ori = exif.get(274, 1)
                    if ori in (5, 6, 7, 8):
                        w, h = h, w
                    dt = exif.get(306)
                    if dt:
                        rec["created"] = dt
                rec.update(kind="photo", width=w, height=h)
                frame = _imread(p)
            if frame is None:
                raise ValueError("cannot decode a frame")
            rec["orientation"] = "portrait" if rec["height"] > rec["width"] else (
                "landscape" if rec["width"] > rec["height"] else "square")
            q = _quality(frame)
            rec.update(q)
            rec["flags"] = (["blurry"] if q["blur"] < 30 else []) + (["dark"] if q["brightness"] < 40 else [])
            rec["_hash"] = _dhash(frame)
            items.append(rec)
        except Exception as e:  # corrupt or unsupported: record and move on
            skipped.append({"path": str(p), "reason": str(e)})
    # duplicates by perceptual hash
    for i, a in enumerate(items):
        for b in items[:i]:
            if sum(x != y for x, y in zip(a["_hash"], b["_hash"])) <= 4:
                a["flags"].append(f"duplicate_of_{b['id']}")
                break
    for a in items:
        a.pop("_hash")
    return {"folder": str(folder), "brief": brief, "audio": audio, "items": items, "skipped": skipped}
