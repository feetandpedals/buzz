"""Pictures made for the topic. Claude draws a flat vector illustration (SVG) for each scene, the PC turns each one
into a 1080x1920 picture using the Edge or Chrome already installed on this PC. No image service, no extra cost.
The drawing is checked first: only plain shapes and gradients are allowed, nothing that could run code or load
anything from the internet. If anything fails, that scene simply keeps a plain coloured background."""
import concurrent.futures
import hashlib
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

import ai_plan
import progress

SVG_NS = "http://www.w3.org/2000/svg"
TAGS = {"svg", "g", "defs", "linearGradient", "radialGradient", "stop", "rect", "circle", "ellipse", "path", "polygon",
        "polyline", "line", "clipPath"}
ATTRS = {"id", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "width", "height", "d", "points", "fill",
         "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "stroke-dasharray", "opacity", "fill-opacity",
         "stroke-opacity", "transform", "offset", "stop-color", "stop-opacity", "gradientUnits", "gradientTransform",
         "fx", "fy", "viewBox", "xmlns", "clip-path", "fill-rule", "clip-rule", "preserveAspectRatio"}
MAX_BYTES = 80_000

PROMPT = """Draw one flat vector illustration for a vertical social reel scene, as an SVG.
Reel topic: %s
This scene: %s
Rules:
- Reply with ONLY the <svg> element. Canvas: viewBox="0 0 1080 1920", no width/height attributes needed.
- Use only these elements: svg, g, defs, linearGradient, radialGradient, stop, rect, circle, ellipse, path, polygon, polyline, line, clipPath.
- No text, letters, numbers, logos, images, filters, masks, styles, scripts or links.
- Style: modern flat illustration, bold simple shapes, soft gradients, friendly and clean. Fill the whole canvas with a background first.
- Colour palette (use these, plus lighter or darker tints of them): %s
- Composition: the main subject sits in the upper-middle (between y=250 and y=1050). Keep the area from y=1100 to y=1650 calm
  and low-detail (it will carry text). Leave 80px margins.
- Make it clearly relate to the scene's meaning. Keep it under 60 simple shapes."""


def _browser():
    for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"):
        if Path(p).exists():
            return p
    return shutil.which("msedge") or shutil.which("chrome")


def available():
    return bool(_browser())


def _local(tag):
    return tag.split("}")[-1]


def sanitize(text):
    """Returns clean SVG text, or None when the drawing is not acceptable."""
    m = re.search(r"<svg\b.*?</svg>", text or "", flags=re.S | re.I)
    if not m or len(m.group(0).encode()) > MAX_BYTES:
        return None
    try:
        root = ET.fromstring(m.group(0))
    except ET.ParseError:
        return None
    if _local(root.tag) != "svg":
        return None

    def clean(el):
        for child in list(el):
            if _local(child.tag) not in TAGS:
                el.remove(child)
                continue
            clean(child)
        for k in list(el.attrib):
            name = _local(k)
            v = el.attrib[k]
            bad = (k.startswith("{") and name not in ATTRS) or name not in ATTRS or name.lower().startswith("on") \
                or re.search(r"javascript|http|data:|@import", v, re.I) or ("url(" in v and not re.fullmatch(r"url\(#[\w\-]+\)", v.strip()))
            if bad:
                del el.attrib[k]
        el.tag = _local(el.tag)

    clean(root)
    for k in ("width", "height"):
        root.attrib.pop(k, None)
    root.set("viewBox", "0 0 1080 1920")
    root.set("xmlns", SVG_NS)
    root.set("preserveAspectRatio", "xMidYMid slice")
    out = ET.tostring(root, encoding="unicode")
    return out.replace("ns0:", "").replace(":ns0", "")


def _rasterise(svg, out_png):
    """SVG text -> 1080x1920 PNG through the PC's own browser. Returns True on success."""
    exe = _browser()
    if not exe:
        return False
    tmp = Path(tempfile.mkdtemp(prefix="reelart_"))
    try:
        html = tmp / "a.html"
        html.write_text('<!doctype html><html><body style="margin:0;background:#000">'
                        f'<div style="width:1080px;height:1920px;overflow:hidden">{svg.replace("<svg ", "<svg width=%s1080%s height=%s1920%s " % ((chr(34),) * 4), 1)}</div>'
                        "</body></html>", encoding="utf-8")
        shot = tmp / "a.png"
        subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
                        "--force-device-scale-factor=1", f"--user-data-dir={tmp / 'profile'}",
                        "--window-size=1080,2100", f"--screenshot={shot}", html.as_uri()],
                       capture_output=True, timeout=90)
        if not shot.exists():
            return False
        with Image.open(shot) as im:
            im = im.convert("RGB").crop((0, 0, 1080, 1920))
            if im.size != (1080, 1920):
                return False
            im.save(out_png)
        return True
    except Exception:
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _one(c, topic, scene_text, palette, out_png):
    if out_png.exists():
        return out_png
    for _ in range(2):  # one retry if the drawing is unusable
        r = c.messages.create(model=ai_plan.MODEL, max_tokens=5000, messages=[{"role": "user", "content": PROMPT % (
            topic[:300], scene_text, palette)}])
        svg = sanitize("".join(b.text for b in r.content if b.type == "text"))
        if svg and _rasterise(svg, out_png):
            return out_png
    return None


def make_art(scenes, topic, palette_hex, job_dir, lo=36, hi=46):
    """scenes: list of scene descriptions. Returns {index: Path} for the scenes that got a picture."""
    out_dir = Path(job_dir) / "art"
    out_dir.mkdir(exist_ok=True)
    if not available():
        return {}
    c = ai_plan.client()
    palette = ", ".join(palette_hex)
    result, done = {}, 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        futs = {}
        for i, s in enumerate(scenes):
            key = hashlib.md5(f"{topic}|{s}|{palette}".encode()).hexdigest()[:10]
            futs[ex.submit(_one, c, topic, s, palette, out_dir / f"scene_{i + 1}_{key}.png")] = i
        for f in concurrent.futures.as_completed(futs):
            done += 1
            progress.stage(lo, hi, done, len(scenes), f"Drawing pictures for your scenes ({done} of {len(scenes)})")
            try:
                p = f.result()
            except Exception:
                p = None
            if p:
                result[futs[f]] = p
    return result
