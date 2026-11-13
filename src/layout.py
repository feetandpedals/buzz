"""Where things go in the 1080x1920 frame: face finding, portrait crops, collage tiles, text that avoids faces."""
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from common import FFMPEG, ROOT

W, H = 1080, 1920
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


# ---------- face finding (separate process, cached) ----------
def detect_faces(paths, cache_file):
    """{path: [[x0,y0,x1,y1] as 0..1 fractions]}. Never raises: no faces found is a valid answer."""
    cache_file = Path(cache_file)
    cache = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else {}

    def key(p):
        return f"{p}|{Path(p).stat().st_mtime_ns}"

    todo = sorted({str(p) for p in paths if key(p) not in cache})
    if todo:
        tmp_in, tmp_out = cache_file.with_name("faces_in.json"), cache_file.with_name("faces_out.json")
        tmp_in.write_text(json.dumps(todo), encoding="utf-8")
        try:
            subprocess.run([sys.executable, str(ROOT / "src" / "facedetect.py"), str(tmp_in), str(tmp_out)],
                           capture_output=True, timeout=600, creationflags=NO_WINDOW)
            res = json.loads(tmp_out.read_text(encoding="utf-8"))
        except Exception:
            res = {}
        for p in todo:
            cache[key(p)] = res.get(p, [])
        cache_file.write_text(json.dumps(cache), encoding="utf-8")
    return {str(p): cache.get(key(p), []) for p in paths}


def video_frame(shot, work):
    """One 1280 px frame from the middle of a video shot, for face finding."""
    out = Path(work) / "faceframes" / f"{shot['id']}_{shot.get('in_point', 0)}_{shot['duration']}.jpg"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", str(shot.get("in_point", 0) + shot["duration"] / 2),
                        "-i", shot["file"], "-frames:v", "1", "-vf", "scale=1280:1280:force_original_aspect_ratio=decrease",
                        str(out)], capture_output=True, creationflags=NO_WINDOW)
    return out if out.exists() else None


# ---------- geometry ----------
def _union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def fit_geom(w, h):
    s = min(W / w, H / h)
    fw, fh = w * s, h * s
    return {"mode": "fit", "ox": (W - fw) / 2, "oy": (H - fh) / 2, "fw": fw, "fh": fh}


def fill_geom(w, h, faces, tw=W, th=H):
    """Cover tw x th and crop, centred on the faces (or slightly above centre when none were found)."""
    s = max(tw / w, th / h)
    sw, sh = math.ceil(w * s), math.ceil(h * s)
    if faces:
        u = _union(faces)
        cx, cy = (u[0] + u[2]) / 2 * sw, (u[1] + u[3]) / 2 * sh
    else:
        cx, cy = sw / 2, sh * 0.45
    ox = int(min(max(cx - tw / 2, 0), sw - tw))
    oy = int(min(max(cy - th / 2, 0), sh - th))
    return {"mode": "fill", "sw": sw, "sh": sh, "ox": ox, "oy": oy, "fw": sw, "fh": sh, "tw": tw, "th": th}


def faces_cropped_out(geom, faces):
    """True if the crop would cut through any face (so we should not crop this picture)."""
    for f in faces:
        x0, y0, x1, y1 = f[0] * geom["sw"] - geom["ox"], f[1] * geom["sh"] - geom["oy"], \
                         f[2] * geom["sw"] - geom["ox"], f[3] * geom["sh"] - geom["oy"]
        if x0 < -4 or y0 < -4 or x1 > geom["tw"] + 4 or y1 > geom["th"] + 4:
            return True
    return False


def to_output(geom, faces, y_shift=0):
    """Face boxes (fractions of the source) -> pixel boxes in the output frame."""
    out = []
    for f in faces:
        if geom["mode"] == "fit":
            b = [geom["ox"] + f[0] * geom["fw"], geom["oy"] + f[1] * geom["fh"],
                 geom["ox"] + f[2] * geom["fw"], geom["oy"] + f[3] * geom["fh"]]
        else:
            b = [f[0] * geom["sw"] - geom["ox"], f[1] * geom["sh"] - geom["oy"],
                 f[2] * geom["sw"] - geom["ox"], f[3] * geom["sh"] - geom["oy"]]
        b[1] += y_shift
        b[3] += y_shift
        if b[2] > 0 and b[0] < W and b[3] > 0 and b[1] < H:
            out.append(b)
    return out


def shot_geometry(shot, items, faces_by_id, options):
    """Returns (kind, geoms, out_faces). kind: 'collage' | 'fill' | 'fit'."""
    ids = shot.get("collage") or [shot["id"]]
    if len(ids) > 1:
        th = H // len(ids)
        geoms, out = [], []
        for k, i in enumerate(ids):
            it = items[i]
            g = fill_geom(it["width"], it["height"], faces_by_id.get(i, []), W, th)
            geoms.append(g)
            out += to_output(g, faces_by_id.get(i, []), y_shift=k * th)
        return "collage", geoms, out
    it = items[shot["id"]]
    w, h = it["width"], it["height"]
    fcs = faces_by_id.get(shot["id"], [])
    portrait = h > w and abs(w / h - W / H) >= 0.02
    if options.get("crop_portrait") and portrait:
        g = fill_geom(w, h, fcs)
        if not faces_cropped_out(g, fcs):
            return "fill", [g], to_output(g, fcs)
    g = fit_geom(w, h)
    return "fit", [g], to_output(g, fcs)


# ---------- text that stays off faces ----------
def measure(text, font_path, size, spacing, border):
    font = ImageFont.truetype(font_path, size)
    d = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    x0, y0, x1, y1 = d.multiline_textbbox((0, 0), text, font=font, spacing=spacing)
    return int(x1 - x0 + 2 * border), int(y1 + 2 * border)


def _overlap(box, faces, pad=0.15):
    a = 0.0
    for f in faces:
        pw, ph = (f[2] - f[0]) * pad, (f[3] - f[1]) * pad
        ix = min(box[2], f[2] + pw) - max(box[0], f[0] - pw)
        iy = min(box[3], f[3] + ph) - max(box[1], f[1] - ph)
        if ix > 0 and iy > 0:
            a += ix * iy
    return a


def place_text(tw, th, faces, prefer, centred=False, y_range=(250, H - 380), x_choices=None):
    """Pick the top-left of a tw x th text block with the least overlap with faces; prefer `prefer` on ties."""
    xs = x_choices or ([(W - tw) // 2] if centred else [64, W - 64 - tw])
    best = None
    ys = sorted({prefer[1]} | set(range(y_range[0], max(y_range[0] + 1, y_range[1] - th), 70)))
    for x in xs:
        for y in ys:
            if y + th > H - 200:
                continue
            ov = _overlap([x, y, x + tw, y + th], faces)
            score = ov + 0.002 * (abs(x - prefer[0]) + abs(y - prefer[1]))
            if best is None or score < best[0]:
                best = (score, x, y, ov)
    if best is None:
        return prefer[0], prefer[1], 0.0
    return best[1], best[2], best[3]
