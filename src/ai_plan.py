"""Phase C: sample frames, AI visual understanding, beat-based edit plan JSON."""
import base64
import io
import json
import re
from pathlib import Path

import cv2
import keyring
import numpy as np
from PIL import Image, ImageOps

import pillow_heif

import music as music_mod
import progress

pillow_heif.register_heif_opener()

MODEL = "claude-sonnet-5-5"
SERVICE = "ai-reel-studio"
MAXSIDE = 512


def client():
    import anthropic
    key = keyring.get_password(SERVICE, "anthropic")
    if not key:
        raise RuntimeError("No AI key saved. Run the one-time setup page.")
    return anthropic.Anthropic(api_key=key)


def _jpeg(img_rgb):
    im = Image.fromarray(img_rgb)
    im.thumbnail((MAXSIDE, MAXSIDE))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=70)
    return buf.getvalue()


def sample_frames(item, cache_dir):
    """Return list of (label, jpeg_bytes). Photos: 1 frame. Videos: 3 frames (20/50/80%)."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = []
    if item["kind"] == "photo":
        f = cache_dir / f"{item['id']}_0.jpg"
        if not f.exists():
            with Image.open(item["path"]) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                f.write_bytes(_jpeg(np.asarray(im)))
        out.append(("photo", f.read_bytes()))
    else:
        for k, frac in enumerate((0.2, 0.5, 0.8)):
            f = cache_dir / f"{item['id']}_{k}.jpg"
            if not f.exists():
                cap = cv2.VideoCapture(item["path"])
                cap.set(cv2.CAP_PROP_POS_MSEC, item["duration"] * frac * 1000)
                ok, fr = cap.read()
                cap.release()
                if not ok:
                    continue
                f.write_bytes(_jpeg(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)))
            out.append((f"frame{k}@{int(frac * 100)}%", f.read_bytes()))
    return out


def _json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    first = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
    if first < 0:
        raise ValueError("no JSON")
    obj, _ = json.JSONDecoder().raw_decode(text[first:])
    return obj


def _ask(c, content, max_tokens=4000):
    for _ in range(3):
        r = c.messages.create(model=MODEL, max_tokens=max_tokens,
                              messages=[{"role": "user", "content": content}])
        text = "".join(b.text for b in r.content if b.type == "text")  # skip thinking blocks
        try:
            return _json(text)
        except Exception:
            Path(__file__).resolve().parent.parent.joinpath("Work", "last_bad_reply.txt").write_text(
                f"stop_reason={r.stop_reason}\n{text}", encoding="utf-8")
            continue
    raise RuntimeError("AI reply was not valid JSON after 3 tries")


ANALYSE_PROMPT = """You are helping edit a short vertical social video from personal photos and clips.
For each numbered item below (images follow its label; videos show 3 sampled frames) return JSON only:
a list of objects {"id": int, "description": str (<=18 words, only what is visible), "subjects": [str],
"mood": str, "shot": "wide"|"medium"|"close", "quality": 1-5 (sharp, well lit, well framed),
"hero": bool (a standout, striking shot), "best_frame": 0|1|2 (videos only: sampled frame that is the best moment, else 0),
"text_visible": str|null}.
Describe only what you can see. Never name people or guess events beyond what is visible.
Context from the owner (may be empty): %s"""


def analyse_items(cat, work_dir, batch=8):
    work_dir = Path(work_dir)
    cache = work_dir / "analysis.json"
    done = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    c = client()
    todo = [i for i in cat["items"] if str(i["id"]) not in done]
    for s in range(0, len(todo), batch):
        progress.stage(14, 46, s // batch, -(-len(todo) // batch),
                       f"Looking at your pictures and clips ({s + 1} to {min(s + batch, len(todo))} of {len(todo)})")
        group = todo[s:s + batch]
        content = [{"type": "text", "text": ANALYSE_PROMPT % (cat.get("brief") or "none")}]
        for it in group:
            content.append({"type": "text", "text": f"Item {it['id']} ({it['kind']}, {it['orientation']}):"})
            for label, jpg in sample_frames(it, work_dir / "frames"):
                content.append({"type": "text", "text": label})
                content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                            "data": base64.b64encode(jpg).decode()}})
        res = _ask(c, content)
        for r in res:
            done[str(r["id"])] = r
        cache.write_text(json.dumps(done, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"analysed {min(s + batch, len(todo))}/{len(todo)}", flush=True)
    return done


def make_slots(m, length, start, bias=0):
    """Cut slots on the beat grid: fast cuts in high-energy parts, longer holds in slow parts.
    bias -1 = faster cutting (more energetic), +1 = slower, calmer cutting."""
    beats = [b for b in m["beats"] if start <= b <= start + length + 0.01]
    if not beats:
        return []
    e = m["energy"]
    slots, i = [], 0
    while i < len(beats) - 1:
        t = beats[i]
        en = e[min(int(t), len(e) - 1)]
        n = 2 if en >= 0.7 else 4
        if bias < 0:
            n = 2
        elif bias > 0:
            n = 4 if en >= 0.7 else 6
        n = 2 if (i == 0) else n  # quick hook
        j = min(i + n, len(beats) - 1)
        if j - i < 2 and j == len(beats) - 1 and slots:
            slots[-1]["end"] = round(beats[j], 3)  # absorb a tiny tail
            break
        slots.append({"start": round(t, 3), "end": round(beats[j], 3), "beats": j - i, "energy": round(en, 2)})
        i = j
    return slots


PLAN_PROMPT = """You are the editor of a vertical music reel. Choose and order EXACTLY %d items (one per slot) from the
catalogue, using each at most once. Rules: open with a striking hook shot; build a story or visual rhythm (vary
wide/medium/close, alternate people and details); put the strongest shots on the high-energy slots; end with a clear,
warm closing shot, ideally a portrait group photo of people with clear faces if the catalogue has one; skip low quality, near-duplicates and flagged items unless nothing else works; prefer videos for
high-energy slots and photos for calmer ones. Slot energies (0-1) in order: %s.
Captions: only from what is visible plus the owner's text; none or very short (<=5 words) on a few slots only.
Owner text: %s
If the owner text gives a title, use it exactly. "theme" is "festive" for Diwali, festivals, weddings and
celebrations, otherwise "neutral".
Return JSON only: {"concept": str, "title": str (<=4 words, shown at the start) , "closing": str (<=5 words),
"theme": "festive"|"neutral", "style": str, "order": [{"id": int, "caption": str|null}]}.
Catalogue:
%s"""


def _is_dup(it):
    return any(f.startswith("duplicate") for f in it["flags"])


def auto_length(cat, options, overrides=None):
    """Reel length in seconds when the owner chose a number of assets but left the length on Auto:
    about 2.8 s per picture and up to 4.5 s per clip, between 15 and 90 s. Without a number: the usual 60 s."""
    mode = (options or {}).get("assets")
    if mode in (None, "auto"):
        return 60.0
    excl = (overrides or {}).get("exclude", [])
    items = [it for it in cat["items"] if it["id"] not in excl and (mode == "all" or not _is_dup(it))]
    if mode != "all":
        items = items[:int(mode)]
    est = sum(2.8 if it["kind"] == "photo" else min(4.5, max(2.5, it.get("duration") or 3.0)) for it in items)
    return float(min(90, max(15, round(est))))


def assets_used(plan):
    """How many of the owner's pictures and clips ended up in the reel (a collage holds several)."""
    return sum(len(s.get("collage") or [1]) for s in plan["shots"] if s.get("kind") != "logo_card")


def fit_slots(slots, n):
    """Make exactly n slots (or as near as the beat grid allows) by joining the shortest neighbours or splitting the
    longest ones on a beat. Every cut stays on the beat."""
    slots = [dict(s) for s in slots]
    while len(slots) > n and len(slots) > 1:
        i = min(range(len(slots) - 1), key=lambda k: slots[k + 1]["end"] - slots[k]["start"])
        a, b = slots[i], slots[i + 1]
        a.update(end=b["end"], beats=a["beats"] + b["beats"], energy=round((a["energy"] + b["energy"]) / 2, 2))
        del slots[i + 1]
    while len(slots) < n:
        i = max(range(len(slots)), key=lambda k: slots[k]["end"] - slots[k]["start"])
        s = slots[i]
        d = s["end"] - s["start"]
        if s["beats"] < 2 or d < 2.0:
            break
        half = s["beats"] // 2
        mid = round(s["start"] + half * d / s["beats"], 3)
        slots[i:i + 1] = [dict(s, end=mid, beats=half), dict(s, start=mid, beats=s["beats"] - half)]
    return slots


def build_plan(cat, analysis, m, work_dir, target=60.0, bias=0, overrides=None, options=None):
    """overrides (from change notes): title, closing, captions {item id: text|None}, exclude [item ids].
    options (from the upload form): font, crop_portrait, collage, logo_file."""
    work_dir = Path(work_dir)
    overrides = overrides or {}
    options = options or {}
    length = min(target, m["duration"])
    start = music_mod.best_window(m, length)
    slots = make_slots(m, length, start, bias)
    flags = {i["id"]: i for i in cat["items"]}
    def _by_name(n):
        return next((it["id"] for it in cat["items"] if n and it["name"] == n), None)

    open_id = overrides.get("opening_id") or _by_name(options.get("opening"))  # the owner's chosen first and last shot
    close_id = overrides.get("closing_id") or _by_name(options.get("closing"))
    if close_id == open_id:
        close_id = None
    mode = options.get("assets")  # None/"auto" = best picks | "all" | a number
    explicit = mode not in (None, "auto")
    note = None
    elig = [it for it in cat["items"] if it["id"] not in overrides.get("exclude", []) and (mode == "all" or not _is_dup(it))]
    n_use = sum(1 for it in cat["items"] if it["id"] not in overrides.get("exclude", [])
                and not any(f.startswith("duplicate") for f in it["flags"]))
    if explicit:  # the owner chose how many pictures and clips to use: exactly that many slots on the beat grid
        want_n = len(elig) if mode == "all" else min(int(mode), len(elig))
        max_fit = max(1, int(length // 1.2))
        if want_n > max_fit:
            note = (f"You asked for {want_n} pictures and clips, but a {int(length)}-second reel only fits {max_fit} "
                    f"of them. Pick a longer reel to use more.")
            want_n = max_fit
        n_slots = want_n
        if options.get("collage") and elig:
            share = sum(1 for it in elig if it["kind"] == "photo" and it["orientation"] == "landscape") / len(elig)
            n_land = round(want_n * share)
            n_slots = max(1, want_n - n_land + (n_land + 1) // 2)
        slots = fit_slots(slots, n_slots)
        if len(slots) < n_slots:
            note = (note + " " if note else "") + f"Only {len(slots)} cuts fit this music and length."
        n_use = len(slots)
    elif options.get("collage"):  # landscape photos pair up, so they need about half as many slots
        n_land = sum(1 for it in cat["items"] if it["kind"] == "photo" and it["orientation"] == "landscape"
                     and it["id"] not in overrides.get("exclude", []) and not any(f.startswith("duplicate") for f in it["flags"]))
        n_use = n_use - n_land + (n_land + 1) // 2
    if not explicit and 0 < n_use < len(slots):  # few items: hold each shot longer (2.5 to 4 s) instead of a 9 s reel
        min_dur, merged = min(4.0, max(2.5, length / n_use)), []
        for s in slots:
            if merged and merged[-1]["end"] - merged[-1]["start"] < min_dur:
                merged[-1].update(end=s["end"], beats=merged[-1]["beats"] + s["beats"],
                                  energy=round((merged[-1]["energy"] + s["energy"]) / 2, 2))
            else:
                merged.append(dict(s))
        slots = merged[:n_use]
    lines = []
    for k, a in analysis.items():
        it = flags[int(k)]
        if it["id"] in overrides.get("exclude", []):
            continue
        lines.append({"id": it["id"], "kind": it["kind"], "dur": it.get("duration"), "o": it["orientation"][0],
                      "d": a["description"], "mood": a["mood"], "shot": a["shot"], "q": a["quality"],
                      "hero": a["hero"], "flags": it["flags"]})
    res = _ask(client(), [{"type": "text", "text": PLAN_PROMPT % (
        len(slots), [s["energy"] for s in slots],
        (cat.get("brief") or "none") + ("\n[The owner wants EVERY item in the catalogue used exactly once, so order them "
                                         "well and do not skip any.]" if mode == "all" else "")
        + (f"\n[Item {open_id} is fixed as the OPENING shot (first). Build the rest of the story from it.]" if open_id else "")
        + (f"\n[Item {close_id} is fixed as the CLOSING shot (last). Lead the story towards it.]" if close_id else ""),
        json.dumps(lines, ensure_ascii=False))}], max_tokens=6000)
    hashes = {}

    def _h(i):
        if i not in hashes:
            f = work_dir / "frames" / f"{i}_{1 if flags[i]['kind'] == 'video' else 0}.jpg"
            if not f.exists():
                f = work_dir / "frames" / f"{i}_0.jpg"
            with Image.open(f) as im:
                g = np.asarray(im.convert("L").resize((17, 16)), dtype=np.int16)
            hashes[i] = (g[:, 1:] > g[:, :-1]).flatten()
        return hashes[i]

    def near_dup(i):
        """True if item i looks like one already chosen (perceptual hash of a sampled frame)."""
        if mode == "all":  # the owner wants everything, look-alikes included
            return False
        h = _h(i)
        return any(int((h != _h(j)).sum()) < 40 for j in order_ids)

    used, order, order_ids = set(), [], []
    for o in res["order"]:
        if o["id"] in flags and o["id"] not in used and not near_dup(o["id"]):
            used.add(o["id"])
            order.append(o)
            order_ids.append(o["id"])
    # fill if the AI returned too few, or we dropped near-duplicates
    for it in sorted(cat["items"], key=lambda x: -analysis.get(str(x["id"]), {}).get("quality", 0)):
        if len(order) >= len(slots):
            break
        if it["id"] in overrides.get("exclude", []):
            continue
        if it["id"] not in used and (mode == "all" or not _is_dup(it)) and not near_dup(it["id"]):
            used.add(it["id"])
            order.append({"id": it["id"], "caption": None})
            order_ids.append(it["id"])
    order = order[:len(slots)]
    if open_id or close_id:  # the owner's choices always win: first and last shot are exactly what was picked
        keep = {i for i in (open_id, close_id) if i}
        cap_of = {o["id"]: o.get("caption") for o in order}
        first = [{"id": open_id, "caption": cap_of.get(open_id), "locked": "opening"}] if open_id else []
        last = [{"id": close_id, "caption": cap_of.get(close_id), "locked": "closing"}] if close_id else []
        middle = [o for o in order if o["id"] not in keep]
        if len(first) + len(last) + len(middle) < len(slots):  # the picks displaced nothing: top up from unused items
            for it in sorted(cat["items"], key=lambda x: -analysis.get(str(x["id"]), {}).get("quality", 0)):
                if len(first) + len(last) + len(middle) >= len(slots):
                    break
                if it["id"] not in keep and it["id"] not in {o["id"] for o in middle} and it["id"] not in overrides.get("exclude", []) \
                        and (mode == "all" or not _is_dup(it)):
                    middle.append({"id": it["id"], "caption": None})
        middle = middle[:max(0, len(slots) - len(first) - len(last))]
        order = first + middle + last
        used |= keep
        order_ids = [o["id"] for o in order]
    if options.get("collage"):  # stack 2 (or 3 on long shots) landscape photos in one 9:16 frame: no blurred bars
        pool = [it for it in sorted(cat["items"], key=lambda x: -analysis.get(str(x["id"]), {}).get("quality", 0))
                if not explicit and it["kind"] == "photo" and it["orientation"] == "landscape" and it["id"] not in used
                and it["id"] not in overrides.get("exclude", []) and not any(f.startswith("duplicate") for f in it["flags"])]
        n = 0
        while n < len(order) - 1:  # the closing shot stays a single picture
            o, slot = order[n], slots[n]
            n += 1
            it0 = flags[o["id"]]
            if o.get("locked") or it0["kind"] != "photo" or it0["orientation"] != "landscape":
                continue  # a picture the owner placed first or last stays on its own
            want = 3 if slot["end"] - slot["start"] >= 3.5 else 2
            group = [o["id"]]
            # first pull in later landscape photos the AI already chose (their slots are dropped) ...
            for j in range(len(order) - 2, n - 1, -1):
                oj = order[j]
                if len(group) >= want:
                    break
                if flags[oj["id"]]["kind"] == "photo" and flags[oj["id"]]["orientation"] == "landscape" \
                        and not oj.get("collage"):
                    group.append(oj["id"])
                    del order[j]
            # ... then unused ones
            for cand in list(pool):
                if len(group) >= want:
                    break
                if not near_dup(cand["id"]):
                    group.append(cand["id"])
                    pool.remove(cand)
                    used.add(cand["id"])
                    order_ids.append(cand["id"])
            if len(group) > 1:
                o["collage"] = group
    shots = []
    for n, (slot, o) in enumerate(zip(slots, order)):
        it, a = flags[o["id"]], analysis[str(o["id"])]
        dur = round(slot["end"] - slot["start"], 3)
        shot = {"n": n + 1, "id": it["id"], "file": it["path"], "kind": it["kind"],
                "music_start": slot["start"] - start, "duration": dur, "energy": slot["energy"], "caption": o.get("caption"),
                "fit": "full-frame, blurred background fill" if it["orientation"] != "portrait" else "fill",
                "transition_in": "cut", "description": a["description"]}
        if it["kind"] == "video":
            t_best = it["duration"] * (0.2, 0.5, 0.8)[int(a.get("best_frame", 1))]
            shot["in_point"] = round(max(0.0, min(t_best - dur / 2, max(it["duration"] - dur, 0.0))), 2)
        else:
            shot["motion"] = "ken_burns" if n % 2 == 0 else "none"
        if o.get("locked"):
            shot["locked"] = o["locked"]
        if o.get("collage"):
            shot["collage"] = o["collage"]
            shot["motion"] = "none"
            shot["description"] += " (collage with " + ", ".join(flags[i]["name"] for i in o["collage"][1:]) + ")"
        shots.append(shot)
    for n in range(1, len(shots)):  # music change = marked; the festive theme shows it as a golden glow
        if abs(slots[n]["energy"] - slots[n - 1]["energy"]) > 0.25:
            shots[n]["transition_in"] = "glow"
    for s in shots:
        cap = overrides.get("captions", {}).get(str(s["id"]), "keep")
        if cap != "keep":
            s["caption"] = cap
    brand = None
    logo_file = options.get("logo_file")  # branding appears only when a logo is uploaded with the reel
    if logo_file and Path(logo_file).exists():
        brand = "custom"
    else:
        logo_file = None
    if brand and shots:
        for s in shots:
            s["logo"] = "corner"
        last = shots[-1]  # closing shot: big logo reveal, held long enough to read
        last.update(logo="reveal", duration=max(last["duration"], 3.4), caption=None)
        if last["kind"] == "photo":
            last["motion"] = "ken_burns"
    plan = {"concept": res.get("concept"), "title": overrides.get("title") or res.get("title"),
            "closing": overrides.get("closing") or res.get("closing"),
            "theme": res.get("theme") if res.get("theme") in ("festive", "neutral") else "neutral",
            "brand": brand, "style": res.get("style"), "options": options, "logo_file": logo_file, "note": note,
            "params": {"target": target, "bias": bias, "overrides": overrides, "options": options},
            "audio": {"file": m["path"], "start": start, "length": length,
                      "tempo": m["tempo"], "fade_in": 0.5, "fade_out": 2.0},
            "output": {"width": 1080, "height": 1920, "fps": 30, "crf": 19}, "shots": shots}
    (work_dir / "plan.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False), encoding="utf-8")
    return plan
