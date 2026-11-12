"""Voiceover for photo and video reels. Claude writes a few short lines that fit the reel, each tied to a shot;
the voice provider speaks them; each line starts with its shot and the music ducks under it (render.py).
Idea reels (prompt_reel.py) do their own narration. Any failure leaves the reel without a voice, never broken."""
import hashlib
import subprocess
from pathlib import Path

import ai_plan
import voice_provider
from common import FFMPEG

PROMPT = """You write a short spoken voiceover for a vertical social reel made from the owner's own photos and clips.
Reel concept: %s
Title: %r
Owner's brief: %s
Shots (number, start second, seconds available until the next line could start, what it shows, caption):
%s
Choose %d to %d shots to speak on, spread across the reel, never the last shot. For each write ONE short, warm
sentence in plain English. A line may have at most the given number of words (about 2.3 words per second).
Only describe what is visible or stated by the owner. Never invent names, places, dates or claims.
Reply with JSON only: {"lines": [{"shot": number, "text": str}]}"""


def _lines(plan, brief):
    shots, t = [], 0.0
    for s in plan["shots"]:
        shots.append((s["n"], t, s["duration"], s.get("description", ""), s.get("caption")))
        t += s["duration"]
    total = t
    k = max(2, min(6, int(total // 9)))
    rows = []
    for i, (n, st, dur, desc, cap) in enumerate(shots[:-1]):
        rows.append(f"{n} | {st:.1f}s | {max(3, int(2.3 * min(dur * 1.5, 6)))} words | {desc[:90]} | {cap or '-'}")
    res = ai_plan._ask(ai_plan.client(), [{"type": "text", "text": PROMPT % (
        plan.get("concept"), plan.get("title"), brief or "none", "\n".join(rows), max(2, k - 1), k)}], max_tokens=1500)
    starts = {n: st for n, st, *_ in shots}
    out = []
    for ln in res.get("lines", []):
        n = int(ln.get("shot", 0))
        if n in starts and ln.get("text"):
            out.append((starts[n] + 0.3, ln["text"].strip()))
    return sorted(out), total


def build_track(timed, job_dir, voice, total):
    """timed: [(start_second, text)]. Speaks each, nudges later lines so none overlap, drops those that run past the end."""
    job_dir = Path(job_dir)
    vdir = job_dir / "voice"
    vdir.mkdir(exist_ok=True)
    parts, t_free = [], 0.0
    for n, (start, text) in enumerate(timed):
        mp3 = vdir / f"shot_{n + 1}_{hashlib.md5((text + voice).encode()).hexdigest()[:8]}.mp3"
        if not mp3.exists():
            voice_provider.synth(text, mp3, voice)
        ln = voice_provider._length(mp3)
        start = max(start, t_free)
        if start + ln > total - 0.4:
            continue
        parts.append((mp3, start))
        t_free = start + ln + 0.35
    if not parts:
        return None
    out = job_dir / "voiceover.wav"
    cmd = [FFMPEG, "-v", "error", "-y"]
    for p, _ in parts:
        cmd += ["-i", str(p)]
    fc = "".join(f"[{i}:a]aresample=44100,adelay={int(s * 1000)}|{int(s * 1000)}[a{i}];" for i, (_, s) in enumerate(parts))
    fc += "".join(f"[a{i}]" for i in range(len(parts))) + f"amix=inputs={len(parts)}:normalize=0:duration=longest[o]"
    cmd += ["-filter_complex", fc, "-map", "[o]", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("Could not build the voiceover: " + r.stderr[-200:])
    return out


def add_voice(plan, brief, job_dir, options):
    """Adds plan['voice'] (or removes it). Returns the plan. Never raises."""
    plan.pop("voice", None)
    if plan.get("prompt_mode") or not options.get("voice") or not voice_provider.available():
        return plan
    try:
        timed, total = _lines(plan, brief)
        track = build_track(timed, job_dir, options.get("voice_name") or voice_provider.default_voice(), total)
        if track:
            plan["voice"] = {"file": str(track), "music_gain": float(options.get("music_gain") or 0.35)}
    except Exception as e:
        (Path(job_dir) / "voice_error.log").write_text(str(e), encoding="utf-8")
    return plan
