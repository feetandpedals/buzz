"""Face finder, run as a separate process (it needs OpenCV 4, kept in assets/cv4 so the main OpenCV is untouched).

Usage: python facedetect.py in.json out.json   (in: list of image paths; out: {path: [[x0,y0,x1,y1], ...]} as 0..1 fractions)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "assets" / "cv4"))
import cv2  # noqa: E402

CASC = [cv2.CascadeClassifier(str(ROOT / "assets" / "haar" / n)) for n in
        ("haarcascade_frontalface_alt2.xml", "haarcascade_profileface.xml")]
BODY = cv2.CascadeClassifier(str(ROOT / "assets" / "haar" / "haarcascade_upperbody.xml"))


def _iou_merge(boxes):
    out = []
    for b in sorted(boxes, key=lambda r: -(r[2] - r[0]) * (r[3] - r[1])):
        if not any(min(b[2], o[2]) - max(b[0], o[0]) > 0.5 * (b[2] - b[0]) and
                   min(b[3], o[3]) - max(b[1], o[1]) > 0.5 * (b[3] - b[1]) for o in out):
            out.append(b)
    return out


def detect(path):
    im = cv2.imread(path)
    if im is None:
        return []
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    h, w = g.shape
    s = 1280 / max(h, w)
    if s < 1:
        g = cv2.resize(g, None, fx=s, fy=s)
    g = cv2.equalizeHist(g)
    gh, gw = g.shape
    boxes = []
    for c in CASC[:1]:
        for x, y, bw, bh in c.detectMultiScale(g, 1.08, 3, minSize=(18, 18)):
            boxes.append([x / gw, y / gh, (x + bw) / gw, (y + bh) / gh])
    prof = CASC[1]
    for flip in (False, True):
        gg = cv2.flip(g, 1) if flip else g
        for x, y, bw, bh in prof.detectMultiScale(gg, 1.1, 4, minSize=(24, 24)):
            x0 = (gw - x - bw) if flip else x
            boxes.append([x0 / gw, y / gh, (x0 + bw) / gw, (y + bh) / gh])
    boxes = _iou_merge(boxes)
    if not boxes:  # helmets, masks, backs: fall back to upper bodies so text still avoids the people
        for x, y, bw, bh in BODY.detectMultiScale(g, 1.1, 3, minSize=(40, 40)):
            boxes.append([x / gw, y / gh, (x + bw) / gw, (y + bh * 0.6) / gh])
        boxes = _iou_merge(boxes)
    return [[round(v, 4) for v in b] for b in boxes]


if __name__ == "__main__":
    paths = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    Path(sys.argv[2]).write_text(json.dumps({p: detect(p) for p in paths}), encoding="utf-8")
