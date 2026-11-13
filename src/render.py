"""Phase D: render an edit plan to a 1080x1920 H.264/AAC reel (CPU only).

Each shot is rendered to its own cached segment (so revisions only re-render what changed),
segments are joined without re-encoding, then one final pass adds the audio.
Text is placed away from faces; portraits can be cropped to 9:16; landscape photos can be stacked into collages.
"""
import hashlib
import json
import subprocess
import textwrap
from pathlib import Path

import pillow_heif
from PIL import Image, ImageOps

import encoder
import layout
import progress
from common import FFMPEG, FFPROBE, ROOT, font_path

pillow_heif.register_heif_opener()

W, H, FPS = 1080, 1920, 30
PROJECT = ROOT.as_posix().replace(":", "\\:")


def _ff(path):
    """Path in the form ffmpeg filters want (forward slashes, escaped drive colon)."""
    return Path(path).as_posix().replace(":", "\\:")


THEMES = {
    # festive: Diwali and celebrations (Yatra One, saffron with deep red outline, warm grade, golden glow flashes)
    "festive": {"font": f"{PROJECT}/fonts/YatraOne.ttf", "fill": "0xFF9933", "outline": "0x7A0C14",
                "glow": "0xFFB347", "flash": True,
                "grade": ("colorbalance=rs=0.05:gs=0.01:bs=-0.08:rm=0.06:gm=0.01:bm=-0.07:rh=0.03:bh=-0.04,"
                          "eq=saturation=1.12:contrast=1.04")},
    # neutral: everything else (Palatino Bold, white with black outline, light grade, no flashes)
    "neutral": {"font": _ff(font_path("palab.ttf", "Cardo-Bold.ttf")), "fill": "white", "outline": "black",
                "glow": "0xFFFFFF", "flash": False, "grade": "eq=saturation=1.06:contrast=1.03"},
}
# Font choices offered when uploading (key -> label, file). "auto" keeps the style's own font.
FONTS = {
    "auto": ("Automatic (matches the style)", None),
    "yatra": ("Yatra One: festive, Indian", ROOT / "fonts" / "YatraOne.ttf"),
    "palatino": ("Palatino Bold: classic book", font_path("palab.ttf", "Cardo-Bold.ttf")),
    "playfair": ("Playfair Display: elegant magazine", ROOT / "fonts" / "PlayfairDisplay.ttf"),
    "cinzel": ("Cinzel: cinematic capitals", ROOT / "fonts" / "Cinzel.ttf"),
    "georgia": ("Georgia Bold: friendly serif", font_path("georgiab.ttf", "PT_Serif-Web-Bold.ttf")),
    "segoe": ("Segoe UI Black: modern clean", font_path("seguibl.ttf", "Poppins-Black.ttf")),
    "impact": ("Impact: bold and punchy", font_path("impact.ttf", "Anton-Regular.ttf")),
}
CUR = dict(THEMES["festive"], name="festive", font_raw=str(ROOT / "fonts" / "YatraOne.ttf"))
STYLE_VERSION = "v8"
LOGO = None  # a logo is used only when the user uploads one with the reel (used as-is, never recreated)


def _lkey():
    return f"{LOGO}{LOGO.stat().st_mtime}" if LOGO else "nologo"


def _write_text(path, text):
    """Write with plain LF line ends: Windows CRLF shows up as a blank line in drawtext."""
    Path(path).write_bytes(text.encode("utf-8"))


def _run(cmd, cwd=None, crf=19):
    """Runs ffmpeg. cmd holds the marker "@VENC@" where the video encoder goes; a failed graphics-card render is redone on the CPU."""
    if "@VENC@" not in cmd:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd)
        if r.returncode != 0:
            raise RuntimeError("ffmpeg failed: " + r.stderr[-1500:])
        return

    def build(cpu_only):
        i = cmd.index("@VENC@")
        return cmd[:i] + encoder.args(crf, cpu_only) + cmd[i + 1:]
    r = subprocess.run(build(False), capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd)
    if r.returncode != 0 and encoder.uses_gpu():
        r = subprocess.run(build(True), capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + r.stderr[-1500:])


def _fit_filter(shot, src_w, src_h, dur, kind="fit", geom=None):
    """Fit (never crop wide shots; blurred copy behind) or, for portraits when asked, a face-centred 9:16 crop."""
    near_916 = abs(src_w / src_h - W / H) < 0.02
    if kind == "fill":
        base = f"scale={geom['sw']}:{geom['sh']},crop={W}:{H}:{geom['ox']}:{geom['oy']},setsar=1"
    elif near_916:
        base = f"scale={W}:{H},setsar=1"
    else:
        base = (f"split[a][b];[a]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,"
                f"boxblur=12:3,scale={W}:{H},eq=brightness=-0.12[bg];"
                f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1")
    if shot["kind"] == "photo" and shot.get("motion") == "ken_burns":
        base += (f",scale=w='trunc({W}*(1+0.06*t/{dur})/2)*2':h='trunc({H}*(1+0.06*t/{dur})/2)*2':eval=frame,"
                 f"crop={W}:{H}")
    return base


def _prep_photo(shot, seg_dir):
    """Work copy as upright JPEG (handles HEIC + EXIF rotation); the original is never touched."""
    out = Path(seg_dir).parent / "photos" / f"{shot['id']}.jpg"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(shot["file"]) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((2160, 2160))
            im.save(out, "JPEG", quality=92)
    return out.resolve()


def _overlays(plan, work, faces_by_shot):
    """Per-shot extra filters (glow flashes, title, closing) so unchanged shots are never re-encoded.
    Title and closing sit where no face is (checked over every shot they appear on)."""
    shots = plan["shots"]
    total = sum(s["duration"] for s in shots if s["kind"] != "logo_card")  # closing text ends before the card
    t0s, t = [], 0.0
    for s in shots:
        t0s.append(t)
        t += s["duration"]
    flash = [i for i, s in enumerate(shots)
             if i > 0 and (s.get("transition_in", "cut") != "cut" or (s.get("energy", 0) >= 0.7 and i % 6 == 0))][:10]
    ttl = plan.get("title") or ""
    if ttl and "\n" not in ttl:
        ttl = textwrap.fill(ttl, 14)
    clo = textwrap.fill(plan["closing"], 16) if plan.get("closing") else ""
    _write_text(work / "title.txt", ttl)
    _write_text(work / "closing.txt", clo)
    tsize = 92 if ttl and max(len(x) for x in ttl.split("\n")) <= 14 else 84  # keep inside the frame
    # safe vertical positions
    ty = cy = None
    if ttl:
        win = [faces_by_shot.get(s["n"], []) for i, s in enumerate(shots) if t0s[i] < 2.8 and t0s[i] + s["duration"] > 0.2]
        tw, th = layout.measure(ttl, CUR["font_raw"], tsize, 10, 6)
        _, ty, _ = layout.place_text(tw, th, [f for fs in win for f in fs], (0, int(H * 0.16)), centred=True,
                                     y_range=(160, 1150))
    if clo:
        win = [faces_by_shot.get(s["n"], []) for i, s in enumerate(shots)
               if t0s[i] + s["duration"] > total - 3.0 and t0s[i] < total - 0.3]
        tw, th = layout.measure(clo, CUR["font_raw"], 72, 10, 5)
        _, cy, _ = layout.place_text(tw, th, [f for fs in win for f in fs], (0, int(H * 0.255)), centred=True,
                                     y_range=(430, 1250))
    out = []
    for i, s in enumerate(shots):
        a, b, f = t0s[i], t0s[i] + s["duration"], []
        if CUR["flash"] and i in flash:
            for dt, al in ((0.0, 0.32), (0.07, 0.18), (0.14, 0.08)):
                f.append(f"drawbox=x=0:y=0:w=iw:h=ih:color={CUR['glow']}@{al}:t=fill:"
                         f"enable='between(t,{dt:.2f},{dt + 0.07:.2f})'")
        if ttl and a < 2.8 and b > 0.2:
            f.append(f"drawtext=fontfile='{CUR['font']}':textfile='title.txt':fontcolor={CUR['fill']}:fontsize={tsize}:"
                     f"borderw=6:bordercolor={CUR['outline']}:shadowcolor=black@0.5:shadowx=3:shadowy=4:"
                     f"text_align=center:line_spacing=10:x=(w-text_w)/2:y={ty}:"
                     f"enable='between(t+{a:.3f},0.2,2.8)':alpha='min(1,(t+{a:.3f})/0.3)'")
        if clo and b > total - 3.0 and a < total - 0.3:
            f.append(f"drawtext=fontfile='{CUR['font']}':textfile='closing.txt':fontcolor={CUR['fill']}:fontsize=72:"
                     f"borderw=5:bordercolor={CUR['outline']}:shadowcolor=black@0.5:shadowx=3:shadowy=4:"
                     f"text_align=center:line_spacing=10:x=(w-text_w)/2:y={cy}:"
                     f"enable='between(t+{a:.3f},{total - 2.8:.2f},{total - 0.3:.2f})'")
        key = "|".join(f) + (ttl if any("title.txt" in x for x in f) else "") + \
              (clo if any("closing.txt" in x for x in f) else "")
        out.append((f, key))
    return out


def render_logo_card(shot, seg_dir):
    """Black end card: the logo eases out from large to normal size while fading in."""
    seg_dir = Path(seg_dir)
    seg_dir.mkdir(parents=True, exist_ok=True)
    dur = shot["duration"]
    key = hashlib.sha1((STYLE_VERSION + CUR["name"] + "logo" + json.dumps(shot, sort_keys=True) +
                        _lkey()).encode()).hexdigest()[:12]
    out = seg_dir / f"seg_{shot['n']:03d}_{key}.mp4"
    if out.exists():
        return out
    for old in seg_dir.glob(f"seg_{shot['n']:03d}_*.mp4"):
        old.unlink()
    zoom_t = max(dur - 0.4, 1.0)
    fc = (f"[1:v]format=rgba,fade=in:st=0:d=0.5:alpha=1,"
          f"scale=w='trunc(880*(1+0.35*pow(1-min(t/{zoom_t:.2f},1),2))/2)*2':h=-2:eval=frame[l];"
          f"[0:v][l]overlay=x=(W-w)/2:y=(H-h)/2-60:eval=frame,fps={FPS},format=yuv420p")
    cmd = [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r={FPS}:d={dur}",
           "-loop", "1", "-framerate", str(FPS), "-t", str(dur), "-i", str(LOGO),
           "-filter_complex", fc, "-an", "@VENC@",
           "-r", str(FPS), "-t", str(dur), str(out.resolve())]
    _run(cmd, cwd=seg_dir, crf=17)
    return out


def render_segment(shot, cat_items, seg_dir, extras=(), extras_key="", geo=None):
    """Final-quality segment: fit/crop/collage + warm grade + glow + captions + title text. Cached per shot.
    geo = (kind, geoms, face boxes in output pixels)."""
    if shot["kind"] == "logo_card":
        return render_logo_card(shot, seg_dir)
    seg_dir = Path(seg_dir)
    seg_dir.mkdir(parents=True, exist_ok=True)
    kind, geoms, out_faces = geo or ("fit", [None], [])
    it = cat_items[shot["id"]]
    dur = shot["duration"]
    cap_xy, cap_txt = None, None
    if shot.get("caption"):
        cap_txt = textwrap.fill(shot["caption"], 22)
        tw, th = layout.measure(cap_txt, CUR["font_raw"], 50, 8, 4)
        cx, cy, _ = layout.place_text(tw, th, out_faces, (64, H - th - 440), y_range=(260, H - 380))
        cap_xy = (cx, cy)
    styled = STYLE_VERSION + CUR["name"] + CUR["font"] if (shot.get("caption") or any("drawtext" in x for x in extras)) \
        else "grade-" + CUR["name"]
    key = hashlib.sha1((styled + "logo-v3" + _lkey() + extras_key + kind +
                        json.dumps(geoms, sort_keys=True) + str(cap_xy) +
                        json.dumps(shot, sort_keys=True)).encode()).hexdigest()[:12]
    out = seg_dir / f"seg_{shot['n']:03d}_{key}.mp4"
    if out.exists():
        return out
    for old in seg_dir.glob(f"seg_{shot['n']:03d}_*.mp4"):
        old.unlink()
    ids = shot.get("collage") or [shot["id"]]
    if kind == "collage":
        n_in, th_t = len(ids), H // len(ids)
        pre = "".join(f"[{k}:v]scale={g['sw']}:{g['sh']},crop={W}:{g['th']}:{g['ox']}:{g['oy']},setsar=1[t{k}];"
                      for k, g in enumerate(geoms))
        pre += "".join(f"[t{k}]" for k in range(n_in)) + f"vstack=inputs={n_in}[st];"
        src = "[st]"
        vf = ",".join(f"drawbox=x=0:y={th_t * k - 6}:w=iw:h=12:color=black@0.9:t=fill" for k in range(1, n_in))
        vf += "," + CUR["grade"]
    else:
        n_in, pre, src = 1, "", "[0:v]"
        if shot["kind"] == "video":  # clip shorter than its slot: hold the last frame instead of cutting short
            pre, src = "[0:v]tpad=stop_mode=clone:stop_duration=12[pv];", "[pv]"
        vf = _fit_filter(shot, it["width"], it["height"], dur, kind, geoms[0]) + "," + CUR["grade"]
    vf += "".join("," + x for x in extras if "drawbox" in x)
    if cap_txt:
        txt = seg_dir / f"cap_{shot['n']:03d}.txt"
        _write_text(txt, cap_txt)
        # small caption, moved away from faces (default bottom-left, above the phone-app buttons)
        vf += (f",drawtext=fontfile='{CUR['font']}':textfile='{txt.name}':fontcolor={CUR['fill']}:fontsize=50:"
               f"borderw=4:bordercolor={CUR['outline']}:shadowcolor=black@0.5:shadowx=2:shadowy=3:"
               f"text_align=left:line_spacing=8:x={cap_xy[0]}:y={cap_xy[1]}:alpha='min(1,t/0.25)'")
    # Logo (only when the shot asks for it): corner mark, or the big reveal that fades in and eases out
    mode = shot.get("logo")
    tail = "".join("," + x for x in extras if "drawtext" in x) + f",fps={FPS},format=yuv420p"
    if mode == "reveal":
        fc = (pre + f"[{n_in}:v]format=rgba,fade=in:st=0.5:d=0.5:alpha=1,"
              "scale=w='trunc(500*(1+0.15*pow(1-min(max(t-0.5,0)/1.4,1),2))/2)*2':h=-2:eval=frame[lg];"
              f"{src}{vf}[v0];[v0][lg]overlay=x=(W-w)/2:y=50:eval=frame[v1];[v1]{tail.lstrip(',')}[vout]")
    elif mode == "corner":
        fc = (pre + f"[{n_in}:v]format=rgba,scale=190:-2,colorchannelmixer=aa=0.92[lg];"
              f"{src}{vf}[v0];[v0][lg]overlay=x=40:y=130[v1];[v1]{tail.lstrip(',')}[vout]")
    else:
        fc = pre + f"{src}{vf}{tail}[vout]"
    cmd = [FFMPEG, "-v", "error", "-y"]
    if shot["kind"] == "video":
        cmd += ["-ss", str(shot.get("in_point", 0)), "-t", str(dur), "-i", shot["file"]]
    else:
        for i in ids:
            cmd += ["-loop", "1", "-framerate", str(FPS), "-t", str(dur), "-i",
                    str(_prep_photo({"id": i, "file": cat_items[i]["path"]}, seg_dir))]
    if mode:
        cmd += ["-loop", "1", "-framerate", str(FPS), "-t", str(dur), "-i", str(LOGO)]
    cmd += ["-filter_complex", fc, "-map", "[vout]", "-an", "@VENC@",
            "-r", str(FPS), "-t", str(dur), str(out.resolve())]
    _run(cmd, cwd=seg_dir)
    return out


def _face_geometry(plan, items, seg_dir, work, options):
    """Finds faces once per picture, then works out for every shot where its faces end up in the frame."""
    paths, owner = [], {}
    for s in plan["shots"]:
        if s["kind"] == "logo_card":
            continue
        for i in s.get("collage") or [s["id"]]:
            if items[i]["kind"] == "photo":
                p = _prep_photo({"id": i, "file": items[i]["path"]}, seg_dir)
            else:
                p = layout.video_frame(s, work)
            if p:
                paths.append(str(p))
                owner[i] = str(p)
    found = layout.detect_faces(paths, Path(work) / "faces.json")
    by_id = {i: found.get(p, []) for i, p in owner.items()}
    geo = {}
    for s in plan["shots"]:
        if s["kind"] != "logo_card":
            geo[s["n"]] = layout.shot_geometry(s, items, by_id, options)
    return geo


def render(plan_path, cat_path, out_path, work_dir):
    global LOGO
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    name = plan.get("theme") if plan.get("theme") in THEMES else "festive"
    CUR.clear()
    CUR.update(THEMES[name], name=name)
    CUR["font_raw"] = CUR["font"].replace("\\:", ":")
    options = plan.get("options") or {}
    chosen = FONTS.get(options.get("font") or "auto", FONTS["auto"])[1]
    if chosen and Path(chosen).exists():
        CUR["font"], CUR["font_raw"] = _ff(chosen), str(chosen)
    lf = plan.get("logo_file")
    LOGO = Path(lf) if lf and Path(lf).exists() else None
    if LOGO is None:  # no logo supplied: drop any logo marks left in an older plan
        plan["shots"] = [dict((k, v) for k, v in s.items() if k != "logo") for s in plan["shots"] if s.get("kind") != "logo_card"]
    cat = json.loads(Path(cat_path).read_text(encoding="utf-8"))["catalogue"]
    items = {i["id"]: i for i in cat["items"]}
    work = Path(work_dir)
    seg_dir = work / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)
    progress.report(56, "Checking faces so the text stays clear", 60)
    geo = _face_geometry(plan, items, seg_dir, work, options)
    ov = _overlays(plan, seg_dir, {n: g[2] for n, g in geo.items()})
    segs = []
    n_shots = len(plan["shots"])
    for k, (s, (extras, ekey)) in enumerate(zip(plan["shots"], ov)):
        progress.stage(60, 92, k, n_shots, f"Making scene {k + 1} of {n_shots}")
        segs.append(render_segment(s, items, seg_dir, extras, ekey, geo.get(s["n"])))
        print(f"segment {s['n']}/{len(plan['shots'])}", flush=True)
    progress.report(92, "Mixing the sound", 96)
    lst = work / "concat.txt"
    lst.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in segs), encoding="utf-8")

    total = sum(s["duration"] for s in plan["shots"])
    a = plan["audio"]
    fade_out = a.get("fade_out", 2.0)
    af = (f"afade=t=in:st=0:d={a.get('fade_in', 0.5)},afade=t=out:st={total - fade_out:.2f}:d={fade_out},"
          f"loudnorm=I=-14:TP=-1.5:LRA=11")
    cmd = [FFMPEG, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst)]
    if not a.get("file"):  # music-free render: the platform sound is added at posting time
        cmd += ["-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        af = "anull"
    else:
        cmd += ["-ss", str(a["start"]), "-t", f"{total:.3f}", "-i", a["file"]]
    voice = plan.get("voice")
    if voice and voice.get("file") and Path(voice["file"]).exists():
        # voiceover: music sits softly underneath and ducks whenever the voice speaks
        cmd += ["-i", voice["file"]]
        g = voice.get("music_gain", 0.35)
        fc = (f"[1:a]volume={g}[m];[2:a]apad,asplit=2[v1][v2];"
              f"[m][v1]sidechaincompress=threshold=0.02:ratio=6:attack=15:release=350[md];"
              f"[md][v2]amix=inputs=2:duration=first:normalize=0,{af}[aout]")
        cmd += ["-filter_complex", fc, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                "-movflags", "+faststart", "-map", "0:v", "-map", "[aout]", "-t", f"{total:.3f}",
                str(Path(out_path).resolve())]
    else:
        # video is copied, not re-encoded: only the audio is processed in this last step
        cmd += ["-af", af, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                "-movflags", "+faststart", "-map", "0:v", "-map", "1:a", "-t", f"{total:.3f}",
                str(Path(out_path).resolve())]
    _run(cmd, cwd=work)
    return Path(out_path)


def verify(path, expect_len):
    r = subprocess.run([FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
                        str(path)], capture_output=True, text=True)
    j = json.loads(r.stdout)
    v = next(s for s in j["streams"] if s["codec_type"] == "video")
    a = next(s for s in j["streams"] if s["codec_type"] == "audio")
    return {"w": v["width"], "h": v["height"], "vcodec": v["codec_name"], "acodec": a["codec_name"],
            "duration": float(j["format"]["duration"]), "expected": round(expect_len, 2),
            "fps": v["avg_frame_rate"]}
