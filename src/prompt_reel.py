"""Prompt-only mode: no photos or clips, just an idea. Claude writes a short script (hook, scenes, call to action),
the PC draws animated text scenes, and the usual music, render and Instagram pack steps do the rest.
Optional slots (voice provider, stock footage provider) plug in later without changing this flow."""
import hashlib
import json
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import ai_plan
import music as music_mod
import progress
from common import ROOT, font_path

W, H = 1080, 1920

# looks: top colour, bottom colour, text colour, outline colour, accent colour
LOOKS = {
    "dark": ((18, 20, 38), (4, 4, 12), (255, 255, 255), (0, 0, 0), (255, 196, 61)),
    "cream": ((250, 243, 228), (233, 219, 190), (36, 28, 24), (250, 243, 228), (187, 27, 37)),
    "festive": ((122, 12, 20), (40, 4, 10), (255, 183, 77), (60, 4, 8), (255, 214, 102)),
    "bold": ((24, 119, 242), (10, 40, 110), (255, 255, 255), (6, 24, 70), (255, 214, 0)),
    "ocean": ((14, 116, 144), (8, 47, 73), (255, 255, 255), (4, 30, 50), (253, 224, 71)),
    "forest": ((21, 94, 59), (6, 37, 24), (254, 243, 199), (4, 30, 18), (190, 242, 100)),
    "sunset": ((251, 146, 60), (157, 23, 77), (255, 255, 255), (110, 15, 55), (254, 240, 138)),
    "violet": ((109, 40, 217), (30, 10, 70), (255, 255, 255), (20, 6, 50), (253, 186, 116)),
    "blush": ((254, 226, 226), (252, 165, 190), (80, 12, 40), (254, 226, 226), (190, 24, 93)),
    "clean": ((255, 255, 255), (235, 235, 238), (24, 24, 27), (255, 255, 255), (37, 99, 235)),
}
LOOK_NAMES = {"dark": "Midnight", "cream": "Cream and red", "festive": "Festive saffron", "bold": "Bold blue",
              "ocean": "Ocean teal", "forest": "Forest green", "sunset": "Sunset glow", "violet": "Violet night",
              "blush": "Blush pink", "clean": "Clean white"}


def palette_hex(look):
    top, bot, fg, edge, acc = LOOKS.get(look, LOOKS["dark"])
    return ["#%02x%02x%02x" % c for c in (top, bot, acc, fg)]


SCRIPT_PROMPT = """You write short vertical reels (Instagram Reels) from an idea. Owner's idea:
%s
Length: about %d seconds. Language: %s. Reply with JSON only:
{"title": str (<=5 words),
 "look": one of %s (the colour theme that fits the idea),
 "mood": str (one or two words for the music, e.g. calm, festive, energetic, upbeat),
 "scenes": [{"text": str (on-screen words, <=12 words, no emojis), "voiceover": str (what a narrator would say, one sentence),
             "seconds": number (2.5 to 6)%s}],
 "cta": str (<=6 words, the final call to action, e.g. a follow or comment ask)}
Rules: scene 1 is a scroll-stopping hook (<=7 words). %d to %d scenes. Each scene adds one new idea, no filler.
Use only facts from the idea or common knowledge. Never invent statistics, names, prices or claims."""


def _font(options, size):
    from render import FONTS
    f = FONTS.get(options.get("font") or "auto", FONTS["auto"])[1] or font_path("georgiab.ttf", "PT_Serif-Web-Bold.ttf")
    if not Path(f).exists():
        f = font_path("palab.ttf", "Cardo-Bold.ttf")
    return ImageFont.truetype(str(f), size)


def _card(text, look, options, idx, total, out, art=None, solid=False):
    """One 1080x1920 scene card. Background: the scene's picture (art), a flat colour (solid), or a soft gradient with
    gentle glows. Then auto-fitted text and progress dots. With a picture the text sits lower, on a soft fade."""
    top, bot, fg, edge, acc = LOOKS.get(look, LOOKS["dark"])
    from PIL import ImageChops
    if art:
        im = Image.open(art).convert("RGB").resize((W, H))
        fade = Image.new("L", (W, H), 0)
        fd = ImageDraw.Draw(fade)
        for y in range(H):  # transparent above y=950, growing to 80% by y=1450, kept below
            a = 0 if y < 950 else min(1.0, (y - 950) / 500) * 205
            fd.line([(0, y), (W, y)], fill=int(a))
        im = Image.composite(Image.new("RGB", (W, H), bot), im, fade)
    elif solid:
        im = Image.new("RGB", (W, H), top)
    else:
        im = Image.new("RGB", (W, H))
        px = ImageDraw.Draw(im)
        for y in range(H):
            t = y / (H - 1)
            px.line([(0, y), (W, y)], fill=tuple(int(top[k] + (bot[k] - top[k]) * t) for k in range(3)))
        glow = Image.new("RGB", (W, H), (0, 0, 0))
        g = ImageDraw.Draw(glow)
        rng = int(hashlib.md5(f"{text}{idx}".encode()).hexdigest()[:6], 16)
        for k in range(3):  # a few soft light blobs; position varies by scene
            cx, cy = (rng >> (4 * k)) % W, (rng >> (3 * k + 2)) % H
            r = 280 + 90 * k
            g.ellipse([cx - r, cy - r, cx + r, cy + r], fill=tuple(int(c * 0.35) for c in acc))
        glow = glow.filter(ImageFilter.GaussianBlur(160))
        im = ImageChops.add(im, glow)
    d = ImageDraw.Draw(im)
    size = (118 if art else 150) if idx == 0 else (108 if art else 132)  # smaller over a picture: more of it stays visible
    max_h = 520 if art else 1000
    while True:  # shrink until the wrapped text fits inside the safe area
        font = _font(options, size)
        per = max(8, int(900 / (size * 0.55)))
        lines = textwrap.wrap(text, per) or [text]
        lh = int(size * 1.22)
        widest = max(d.textlength(l, font=font) for l in lines)
        if (widest <= 900 and lh * len(lines) <= max_h) or size <= 48:
            break
        size -= 6
    centre = 1340 if art else H // 2 - 40
    y = centre - lh * len(lines) // 2
    for l in lines:
        w = d.textlength(l, font=font)
        d.text(((W - w) / 2, y), l, font=font, fill=fg, stroke_width=max(4, size // 14), stroke_fill=edge)
        y += lh
    d.rounded_rectangle([W // 2 - 70, y + 30, W // 2 + 70, y + 38], radius=4, fill=acc)  # accent underline
    dot_w, x0 = 22, W // 2 - (total * 22 + (total - 1) * 8) // 2  # progress dots near the bottom
    dy = H - (150 if art else 230)
    for k in range(total):
        d.ellipse([x0 + k * 30, dy, x0 + k * 30 + dot_w, dy + dot_w], fill=acc if k == idx else (fg if art else edge))
    im.save(out, "JPEG", quality=93)


def _snap(durs, beats):
    """Make each scene end on a beat, never shorter than 2.2 s."""
    out, prev, t = [], 0.0, 0.0
    for d in durs:
        t += d
        cands = [b for b in beats if b >= prev + 2.2]
        end = min(cands, key=lambda b: abs(b - t)) if cands else t
        out.append(round(end - prev, 3))
        prev = end
    return out


def build(folder, job, options, brief, silent_music):
    """Returns (catalogue_blob, plan). Resumable: the script is cached in job/script.json.
    Optional slots: voice_provider (spoken narration) and stock_provider (real footage behind the words)."""
    import stock_provider
    import voice_provider
    job = Path(job)
    seconds = int(min(90, max(15, options.get("seconds") or 30)))
    bg = options.get("background") or ("video" if options.get("stock", True) else "gradient")  # gradient|solid|art|video
    use_stock = stock_provider.available() and bg == "video"
    use_voice = voice_provider.available() and options.get("voice", False)
    sf = job / "script.json"
    if sf.exists():
        script = json.loads(sf.read_text(encoding="utf-8"))
    else:
        lang = options.get("language") or "English"
        extra = ""
        if use_stock:
            extra = (', "visual": "stock"|"text" (stock = real video footage behind the words, use it on about two '
                     'thirds of the scenes where a real scene helps; text = words only), "query": str (2-3 plain English '
                     'words to search stock video for this scene, e.g. "cyclist morning road"; empty for text scenes)')
        script = ai_plan._ask(ai_plan.client(), [{"type": "text", "text": SCRIPT_PROMPT % (
            brief, seconds, lang, " | ".join(f'"{k}"' for k in LOOKS), extra, max(4, seconds // 6),
            max(6, seconds // 4))}], max_tokens=3500)
        sf.write_text(json.dumps(script, indent=1, ensure_ascii=False), encoding="utf-8")
    scenes = list(script["scenes"])
    if script.get("cta"):
        scenes.append({"text": script["cta"], "voiceover": script["cta"], "seconds": 3.5, "visual": "text"})
    look = options.get("look") if options.get("look") in LOOKS else (script.get("look") if script.get("look") in LOOKS else "dark")
    arts = {}
    if bg == "art":  # a picture drawn for each scene
        import art_provider
        progress.report(36, "Drawing pictures for your scenes", 46)
        arts = art_provider.make_art([f"{s['text']} ({s.get('voiceover') or ''})" for s in scenes],
                                     f"{script.get('title') or ''}. {brief}", palette_hex(look), job)
    base = [max(2.5, min(6.0, float(s.get("seconds") or 3.5))) for s in scenes]
    # voiceover first (when switched on and a key exists): the scene lengths then follow the spoken lines
    voice_file, spans = None, None
    progress.report(16, "Recording the voiceover" if use_voice else "Planning the scenes", 26)
    if use_voice:
        try:
            voice_file, spans = voice_provider.narrate([s.get("voiceover") or s["text"] for s in scenes], job,
                                                       options.get("voice_name") or voice_provider.default_voice())
        except Exception as e:
            (job / "voice_error.log").write_text(str(e), encoding="utf-8")
    progress.report(26, "Composing your music", 36)
    est = sum(base) if not spans else sum(max(2.5, ln + 0.9) for _, ln in spans)
    if options.get("music") == "none":
        m = silent_music(est + 6)
    else:
        import music_provider
        wav = music_provider.make_music(job / "generated_music.wav", f"{script.get('mood', '')} {brief}", est + 6,
                                        options.get("music_keywords") or "")
        m = music_mod.analyse(wav)
        m["generated"] = True
    if spans:
        durs = [round(max(2.5, ln + 0.9), 3) for _, ln in spans]
        # keep the voice and the picture together: a scene may not start before its line does
        starts, t = [], 0.0
        for d in durs:
            starts.append(t)
            t += d
        # re-time the voice track so each line begins exactly with its scene
        voice_file = _align_voice(job, voice_file, spans, starts)
    else:
        durs = _snap(base, m["beats"])
    cards = job / "cards"
    cards.mkdir(exist_ok=True)
    items, shots, t, credits, used_stock = [], [], 0.0, [], []
    for n, (s, d) in enumerate(zip(scenes, durs)):
        progress.stage(36, 46, n, len(scenes), f"Designing scene {n + 1} of {len(scenes)}")
        clip = None
        if use_stock and s.get("visual") == "stock" and s.get("query"):
            clip = stock_provider.fetch_clip(s["query"], job / "stock", min_seconds=min(d, 3.0), used=used_stock)
        if clip:
            path, w, h, dur, page, vid = clip
            used_stock.append(vid)
            if stock_provider.CREDIT not in credits:
                credits.append(stock_provider.CREDIT)
            items.append({"id": n + 1, "path": str(path), "name": Path(path).name, "kind": "video", "width": w,
                          "height": h, "duration": round(dur, 2), "fps": 30, "has_audio": False,
                          "orientation": "portrait", "flags": [], "size": Path(path).stat().st_size, "blur": 100.0,
                          "brightness": 80.0})
            shots.append({"n": n + 1, "id": n + 1, "file": str(path), "kind": "video", "music_start": round(t, 3),
                          "duration": d, "energy": 0.6, "caption": s["text"], "fit": "fill", "transition_in": "cut",
                          "description": s["text"], "in_point": 0.0, "voiceover": s.get("voiceover")})
        else:
            p = cards / f"card_{n + 1}.jpg"
            _card(s["text"], look, options, n, len(scenes), p, art=arts.get(n), solid=(bg == "solid"))
            items.append({"id": n + 1, "path": str(p), "name": p.name, "kind": "photo", "width": W, "height": H,
                          "orientation": "portrait", "flags": [], "size": p.stat().st_size, "blur": 100.0,
                          "brightness": 80.0})
            shots.append({"n": n + 1, "id": n + 1, "file": str(p), "kind": "photo", "music_start": round(t, 3),
                          "duration": d, "energy": 0.6, "caption": None, "fit": "fill", "transition_in": "cut",
                          "description": s["text"], "motion": "ken_burns" if n % 2 == 0 else "none",
                          "voiceover": s.get("voiceover")})
        t += d
    cat = {"folder": str(folder), "brief": brief, "audio": [], "items": items, "skipped": []}
    options = dict(options)
    plan = {"concept": script.get("title") or "Prompt reel", "title": None, "closing": None,
            "theme": "festive" if look == "festive" else "neutral", "brand": None,
            "style": f"{'stock footage and ' if credits else ''}text scenes, {look} look",
            "options": options, "logo_file": None, "credits": credits,
            "params": {"target": seconds, "bias": 0, "overrides": {}, "options": options},
            "audio": {"file": m["path"], "start": 0.0, "length": round(t, 3), "tempo": m["tempo"],
                      "fade_in": 0.5, "fade_out": 2.0},
            "output": {"width": W, "height": H, "fps": 30, "crf": 19}, "shots": shots, "prompt_mode": True}
    if voice_file:
        plan["voice"] = {"file": str(voice_file), "music_gain": float(options.get("music_gain") or 0.35)}
    (job / "plan.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False), encoding="utf-8")
    return {"catalogue": cat, "music": m}, plan


def _align_voice(job, voice_file, spans, starts):
    """Rebuilds the voiceover so line n starts exactly when scene n starts (silence fills the gaps)."""
    import subprocess

    from common import FFMPEG
    out = Path(job) / "voiceover_aligned.wav"
    cmd = [FFMPEG, "-v", "error", "-y", "-i", str(voice_file)]
    parts = []
    for n, ((s0, ln), st) in enumerate(zip(spans, starts)):
        parts.append(f"[0:a]atrim=start={s0}:duration={ln},asetpts=PTS-STARTPTS,adelay={int(st * 1000)}|{int(st * 1000)}[l{n}]")
    fc = ";".join(parts) + ";" + "".join(f"[l{n}]" for n in range(len(parts))) + \
         f"amix=inputs={len(parts)}:normalize=0:duration=longest[o]"
    cmd += ["-filter_complex", fc, "-map", "[o]", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("Could not time the voice to the scenes: " + r.stderr[-200:])
    return out
