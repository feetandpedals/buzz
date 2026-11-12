"""One job = one folder in Reels In -> finished reel in Reels Out. Resumable: every stage caches."""
import json
import shutil
import subprocess
import time
import traceback
from pathlib import Path

import ai_plan
import ingest
import music
import progress
import render
from common import FFMPEG, REELS_OUT, WORK


def _state(job_dir):
    f = job_dir / "job.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def _save(job_dir, **kw):
    s = _state(job_dir)
    s.update(kw, updated=time.strftime("%Y-%m-%d %H:%M:%S"))
    (job_dir / "job.json").write_text(json.dumps(s, indent=1, ensure_ascii=False), encoding="utf-8")


def _silent_music(length=60.0, bpm=110.0):
    step = 60.0 / bpm
    beats = [round(i * step, 3) for i in range(int(length / step) + 1)]
    return {"path": None, "duration": length, "tempo": bpm, "beats": beats, "downbeats": beats[::4],
            "energy": [0.6] * int(length + 1), "sections": []}


def read_options(folder):
    """Choices made on the upload form (options.json) plus an uploaded logo (_logo.*), if any."""
    folder = Path(folder)
    opt = {}
    f = folder / "options.json"
    if f.exists():
        try:
            opt = json.loads(f.read_text(encoding="utf-8-sig"))
        except ValueError:
            opt = {}
    logo = next((p for p in sorted(folder.glob("_logo.*")) if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")), None)
    if logo:
        opt["logo_file"] = str(logo)
    return opt


def run_job(folder):
    folder = Path(folder)
    name = folder.name
    job = WORK / "jobs" / name
    job.mkdir(parents=True, exist_ok=True)
    out_dir = REELS_OUT / name
    try:
        progress.start(job)
        _save(job, status="running", stage="catalogue", folder=str(folder))
        cat_file = job / "catalogue.json"
        if cat_file.exists():
            blob = json.loads(cat_file.read_text(encoding="utf-8"))
        elif read_options(folder).get("mode") == "prompt":  # idea only: no photos or clips needed
            import prompt_reel
            progress.report(3, "Writing your script", 14)
            brief = (ingest.catalogue(folder).get("brief") or "").strip()
            if not brief:
                raise RuntimeError("Write the idea for the reel first.")
            blob, pplan = prompt_reel.build(folder, job, read_options(folder), brief, _silent_music)
            cat_file.write_text(json.dumps(blob, ensure_ascii=False, indent=1), encoding="utf-8")
        else:
            cat = ingest.catalogue(folder)
            if not cat["items"]:
                raise RuntimeError("No usable photos or videos found in the folder.")
            progress.report(10, "Preparing the music", 14)
            if cat["audio"]:
                m = music.analyse(cat["audio"][0]["path"])
            elif read_options(folder).get("music") == "none":  # "Create music" box unticked: silent reel
                m = _silent_music()
            else:  # no song supplied: compose an original track on this PC (music_provider slot)
                try:
                    import music_provider
                    opt = read_options(folder)
                    est = float(opt.get("seconds") or ai_plan.auto_length(cat, opt))
                    wav = music_provider.make_music(job / "generated_music.wav", cat.get("brief") or "",
                                                    max(62.0, est + 4), opt.get("music_keywords") or "")
                    m = music.analyse(wav)
                    m["generated"] = True
                except Exception:
                    (job / "music_error.log").write_text(traceback.format_exc(), encoding="utf-8")
                    m = _silent_music()
            blob = {"catalogue": cat, "music": m}
            cat_file.write_text(json.dumps(blob, ensure_ascii=False, indent=1), encoding="utf-8")
        cat, m = blob["catalogue"], blob["music"]
        silent = m["path"] is None
        if read_options(folder).get("mode") == "prompt":
            _save(job, stage="planning", silent=silent)
            plan = json.loads((job / "plan.json").read_text(encoding="utf-8"))
        else:
            _save(job, stage="ai_analysis", silent=silent)
            analysis = ai_plan.analyse_items(cat, job)
            _save(job, stage="planning")
            progress.report(47, "Choosing the best shots and planning the story", 53)
            plan = ai_plan.build_plan(cat, analysis, m, job, target=float(read_options(folder).get("seconds") or ai_plan.auto_length(cat, read_options(folder))),
                                      options=read_options(folder))
            import narration  # optional spoken voiceover (needs the Google voice key)
            progress.report(53, "Writing the voiceover" if read_options(folder).get("voice") else "Planning the edit", 56)
            plan = narration.add_voice(plan, cat.get("brief"), job, read_options(folder))
            (job / "plan.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False), encoding="utf-8")
        _save(job, stage="rendering")
        out_dir.mkdir(parents=True, exist_ok=True)
        reel = render.render(job / "plan.json", cat_file, out_dir / f"{name} reel.mp4", job)
        total = sum(s["duration"] for s in plan["shots"])
        progress.report(96, "Checking the finished video", 97)
        info = render.verify(reel, total)
        if abs(info["duration"] - total) > 1.0 or (info["w"], info["h"]) != (1080, 1920):
            raise RuntimeError(f"Verification failed: {info}")
        subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", "4", "-i", str(reel), "-frames:v", "1",
                        str(out_dir / "thumbnail.jpg")])
        shutil.copy(job / "plan.json", out_dir / "edit plan.json")
        import social
        progress.report(97, "Writing your Instagram post", 99)
        social.make_pack(plan, cat.get("brief"), out_dir)
        progress.report(99, "Finishing", 100)
        (out_dir / "summary.txt").write_text(
            f"Concept: {plan['concept']}\n"
            f"Length: {info['duration']:.1f} s, {len(plan['shots'])} shots, "
            f"{'no music (silent)' if silent else ('original music made for this reel, cut to its beat' if m.get('generated') or Path(m['path']).stem == 'generated_music' else 'cut to the beat of ' + Path(m['path']).stem)}.\n"
            + ("Made from your idea: scenes drawn on this PC"
               + (", with real stock footage" if plan.get("credits") else "")
               + (", spoken by a voiceover" if plan.get("voice") else "") + ".\n"
               + "".join(f"Credit: {c}\n" for c in plan.get("credits", []))
               if plan.get("prompt_mode") else
               f"Used {ai_plan.assets_used(plan)} of {len(cat['items'])} photos and clips"
               + ("; the rest were left out (weaker, repeated or near-duplicate).\n"
                  if ai_plan.assets_used(plan) < len(cat['items']) else ".\n")
               + (plan.get("note", "") + "\n" if plan.get("note") else "")), encoding="utf-8")
        _save(job, status="done", stage="finished", output=str(reel), seconds=info["duration"])
        return True
    except Exception as e:
        (job / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        _save(job, status="failed", error=str(e)[:300])
        return False
