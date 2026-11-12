"""Safe uploads. Only known photo, video and audio types are accepted, and each file's first bytes must match its
extension, so a program renamed to .jpg is refused. Names are cleaned, counts and sizes are capped."""
import re
from pathlib import Path

PHOTO = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".bmp", ".tif", ".tiff"}
VIDEO = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".mts", ".3gp"}
AUDIO = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
LOGO = {".png", ".jpg", ".jpeg", ".webp"}
MAX_FILES = 300
MAX_TOTAL = 3 * 1024 ** 3  # 3 GB for one reel


def types(*groups):
    """Extension list in the form st.file_uploader wants (no dots)."""
    return sorted(e.lstrip(".") for g in groups for e in g)


def _ftyp(h):
    return h[4:8] == b"ftyp"


def _riff(h, kind):
    return h[:4] == b"RIFF" and h[8:12] == kind


def looks_right(ext, h):
    """True when the first bytes of the file fit its extension."""
    if ext in (".jpg", ".jpeg"):
        return h[:3] == b"\xff\xd8\xff"
    if ext == ".png":
        return h[:8] == b"\x89PNG\r\n\x1a\n"
    if ext == ".webp":
        return _riff(h, b"WEBP")
    if ext == ".bmp":
        return h[:2] == b"BM"
    if ext in (".tif", ".tiff"):
        return h[:4] in (b"II*\x00", b"MM\x00*")
    if ext == ".heic":
        return _ftyp(h)
    if ext in (".mp4", ".m4v", ".mov", ".3gp", ".m4a"):
        return _ftyp(h) or h[4:8] in (b"moov", b"mdat", b"free", b"wide", b"skip")
    if ext in (".webm", ".mkv"):
        return h[:4] == b"\x1a\x45\xdf\xa3"
    if ext == ".avi":
        return _riff(h, b"AVI ")
    if ext == ".mts":
        return h[0:1] == b"\x47" or h[4:5] == b"\x47"
    if ext == ".mp3":
        return h[:3] == b"ID3" or (h[0:1] == b"\xff" and (h[1] & 0xE0) == 0xE0)
    if ext == ".wav":
        return _riff(h, b"WAVE")
    if ext == ".aac":
        return h[0:1] == b"\xff" and (h[1] & 0xF6) == 0xF0
    if ext == ".flac":
        return h[:4] == b"fLaC"
    if ext == ".ogg":
        return h[:4] == b"OggS"
    return False


def clean_name(name):
    p = Path(name)
    stem = re.sub(r"[^\w .()\-]", "_", p.stem).strip(" ._") or "file"
    return stem[:80] + p.suffix.lower()


def save(dest, uploaded, allowed, reserved_prefix="_", mapping=None):
    """Writes the acceptable files into dest. Returns (saved_names, [(original_name, reason)]).
    If mapping is a dict it receives {original upload name: name it was saved as}."""
    dest = Path(dest)
    saved, refused, total = [], [], 0
    for f in uploaded or []:
        ext = Path(f.name).suffix.lower()
        if len(saved) >= MAX_FILES:
            refused.append((f.name, f"more than {MAX_FILES} files"))
            continue
        if ext not in allowed:
            refused.append((f.name, "this file type is not allowed"))
            continue
        data = f.getbuffer()
        if not looks_right(ext, bytes(data[:16])):
            refused.append((f.name, "the file does not match its type"))
            continue
        total += len(data)
        if total > MAX_TOTAL:
            refused.append((f.name, "too much data in one reel"))
            continue
        name = clean_name(f.name)
        if name.lower().startswith(reserved_prefix):
            name = "f" + name
        target, k = dest / name, 2
        while target.exists():
            target = dest / f"{Path(name).stem} ({k}){Path(name).suffix}"
            k += 1
        target.write_bytes(data)
        saved.append(target.name)
        if mapping is not None:
            mapping.setdefault(f.name, target.name)
    return saved, refused
