"""Change notes: turn a plain-language note into plan edits, then re-render only what changed."""
import json
import shutil
import subprocess
import time
import traceback
from pathlib import Path

import ai_plan
import progress
import render
from common import FFMPEG, REELS_OUT, WORK

NOTE_PROMPT = """You edit a short vertical music reel. The owner sent a plain-language change note.
Turn it into JSON edits using ONLY these fields (use null when the note does not ask for that):
{"title": str|null, "closing": str|null,
 "captions": {"<shot number>": str|null} (set text, or null to remove that shot's caption; {} if none),
 "drop_shots": [shot numbers to remove] ,
 "opening_shot": number|null  (make this shot number the first shot),
 "closing_shot": number|null  (make this shot number the last shot),
 "target_seconds": number|null  ("shorter"/"longer": current is %s s; shorter = about 25%% less, longer = about 25%% more, min 15, max 75),
 "pace": "faster"|"slower"|null  ("more energetic" = faster, "calmer" = slower),
 "silent": true|false|null  (true if the owner wants no music),
 "font": one of auto|yatra|palatino|playfair|cinzel|georgia|segoe|impact|null  (a different text font),
 "crop_portrait": true|false|null  (crop and centre portrait pictures to fill the screen, or stop doing that),
 "collage": true|false|null  (stack landscape pictures in collages, or stop doing that),
 "reply": str (one plain sentence telling the owner what you changed, or why you could not)}
Never invent facts in captions. Titles: use the owner's exact words when given.
Current reel: title=%r closing=%r pace=%s
Shots (number, item id, kind, caption, what it shows):
%s
Owner's note: %s"""


def _job_files(name):
    job = WORK / "jobs" / name
    return job, job / "catalogue.json", job / "analysis.json", job / "plan.json"


def _revise_prompt(name, note, job):
    """Idea-only reels have no photos to re-plan: add the change to the idea and write the whole reel again."""
    import pipeline
    from common import REELS_IN
    folder = REELS_IN / name
    out_dir = REELS_OUT / name
    reel = out_dir / f"{name} reel.mp4"
    if reel.exists():
        shutil.copy(reel, out_dir / f"{name} reel (previous).mp4")
    idea = folder / "prompt.txt"
    idea.write_text(idea.read_text(encoding="utf-8-sig").rstrip() + f"\n\nChange request from the owner: {note}\n",
                    encoding="utf-8")
    for pattern in ("script.json", "catalogue.json", "plan.json", "segments/seg_*.mp4", "photos/*.jpg", "cards/*.jpg"):
        for p in job.glob(pattern):
            p.unlink()
    ok = pipeline.run_job(folder)
    hist = json.loads((job / "revisions.json").read_text(encoding="utf-8")) if (job / "revisions.json").exists() else []
    reply = "I rewrote the reel with your change." if ok else "Could not apply the change."
    hist.append({"when": time.strftime("%Y-%m-%d %H:%M:%S"), "note": note, "reply": reply})
    (job / "revisions.json").write_text(json.dumps(hist, indent=1, ensure_ascii=False), encoding="utf-8")
    return {"ok": ok, "reply": reply}


def revise(name, note):
    job, cat_file, ana_file, plan_file = _job_files(name)
    try:
        import usage
        usage.set_context(usage.owner_of(name), name)
        progress.start(job)
        progress.report(4, "Understanding your change", 14)
        if plan_file.exists() and json.loads(plan_file.read_text(encoding="utf-8")).get("prompt_mode"):
            return _revise_prompt(name, note, job)
        blob = json.loads(cat_file.read_text(encoding="utf-8"))
        cat, m = blob["catalogue"], blob["music"]
        analysis = json.loads(ana_file.read_text(encoding="utf-8"))
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
        prm = plan.get("params", {"target": plan["audio"]["length"], "bias": 0, "overrides": {}})
        shots = "\n".join(f"{s['n']} | id {s['id']} | {s['kind']} | caption={s.get('caption')!r} | "
                          f"{s['description'][:80]}" for s in plan["shots"])
        total = sum(s["duration"] for s in plan["shots"])
        ops = ai_plan._ask(ai_plan.client(), [{"type": "text", "text": NOTE_PROMPT % (
            round(total), plan.get("title"), plan.get("closing"), {-1: "faster", 0: "normal", 1: "slower"}[prm["bias"]],
            shots, note)}], max_tokens=3000)
        ov = dict(prm.get("overrides", {}))
        if ops.get("title"):
            ov["title"] = ops["title"].replace("|", "\n")
        if ops.get("closing"):
            ov["closing"] = ops["closing"]
        by_n = {str(s["n"]): s for s in plan["shots"]}
        for key, field in (("opening_shot", "opening_id"), ("closing_shot", "closing_id")):
            if ops.get(key) and str(ops[key]) in by_n:
                ov[field] = by_n[str(ops[key])]["id"]
        caps = {str(s["id"]): s.get("caption") for s in plan["shots"]}
        for n, text in (ops.get("captions") or {}).items():
            if n in by_n:
                caps[str(by_n[n]["id"])] = text
        ov["captions"] = caps
        opts = dict(prm.get("options") or plan.get("options") or {})
        if ops.get("font") in render.FONTS:
            opts["font"] = ops["font"]
        for k in ("crop_portrait", "collage"):
            if isinstance(ops.get(k), bool):
                opts[k] = ops[k]
        layout_changed = any(opts.get(k) != (prm.get("options") or {}).get(k) for k in ("crop_portrait", "collage"))
        needs_replan = bool(ops.get("opening_shot") or ops.get("closing_shot") or ops.get("drop_shots") or ops.get("target_seconds") or ops.get("pace") or layout_changed)
        target, bias = prm["target"], prm["bias"]
        if ops.get("drop_shots"):
            ov["exclude"] = sorted(set(ov.get("exclude", [])) | {by_n[str(n)]["id"] for n in ops["drop_shots"]
                                                                 if str(n) in by_n})
        if ops.get("target_seconds"):
            target = float(min(90, max(15, ops["target_seconds"])))
            opts["seconds"] = int(target)  # remembered, so an Auto length does not undo it
        if ops.get("pace"):
            bias = -1 if ops["pace"] == "faster" else 1
        progress.report(16, "Re-planning the reel" if needs_replan else "Updating the text", 40)
        if needs_replan:
            plan = ai_plan.build_plan(cat, analysis, m, job, target=target, bias=bias, overrides=ov,
                                      options=opts)
            import narration  # a new shot order needs the voice lines placed again
            plan = narration.add_voice(plan, cat.get("brief"), job, opts)
        else:  # text-only change: edit the plan directly, nothing is re-planned
            if "title" in ov:
                plan["title"] = ov["title"]
            if "closing" in ov:
                plan["closing"] = ov["closing"]
            for s in plan["shots"]:
                if s.get("logo") != "reveal":
                    s["caption"] = caps.get(str(s["id"]), s.get("caption"))
            plan["options"] = opts  # a font change needs no re-plan: only text shots re-render
            plan["params"] = {"target": target, "bias": bias, "overrides": ov, "options": opts}
        if ops.get("silent") is not None:
            plan["audio"]["file"] = None if ops["silent"] else m["path"]
        plan_file.write_text(json.dumps(plan, indent=1, ensure_ascii=False), encoding="utf-8")

        progress.report(44, "Getting ready to render", 56)
        out_dir = REELS_OUT / name
        reel = out_dir / f"{name} reel.mp4"
        if reel.exists():  # keep the previous version
            shutil.copy(reel, out_dir / f"{name} reel (previous).mp4")
        render.render(plan_file, cat_file, reel, job)
        total = sum(s["duration"] for s in plan["shots"])
        progress.report(96, "Checking the finished video", 97)
        info = render.verify(reel, total)
        subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", "4", "-i", str(reel), "-frames:v", "1",
                        str(out_dir / "thumbnail.jpg")])
        shutil.copy(plan_file, out_dir / "edit plan.json")
        import social
        progress.report(97, "Refreshing your Instagram post", 99)
        social.make_pack(plan, cat.get("brief"), out_dir)
        hist = json.loads((job / "revisions.json").read_text(encoding="utf-8")) if (job / "revisions.json").exists() else []
        hist.append({"when": time.strftime("%Y-%m-%d %H:%M:%S"), "note": note, "reply": ops.get("reply")})
        (job / "revisions.json").write_text(json.dumps(hist, indent=1, ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "reply": ops.get("reply"), "seconds": info["duration"]}
    except Exception as e:
        (job / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        return {"ok": False, "reply": f"Could not apply the change: {str(e)[:200]}"}
