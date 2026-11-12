"""Music analysis: tempo, beats, downbeats, bars, energy curve, sections."""
import subprocess
import tempfile
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

from common import FFMPEG

SR = 22050


def _load(path):
    # decode via ffmpeg so any format/Unicode path works
    with tempfile.TemporaryDirectory() as d:
        wav = Path(d) / "a.wav"
        subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(path), "-ac", "1", "-ar", str(SR),
                        str(wav)], check=True)
        y, _ = sf.read(str(wav), dtype="float32")  # ffmpeg already resampled; avoids soxr
    return y


def analyse(path):
    y = _load(path)
    dur = len(y) / SR
    tempo, beats = librosa.beat.beat_track(y=y, sr=SR, units="time")
    tempo = float(np.atleast_1d(tempo)[0])
    beats = np.asarray(beats, dtype=float)
    hop = 512
    rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    t = librosa.frames_to_time(np.arange(len(rms)), sr=SR, hop_length=hop)
    # 1-second energy curve, normalised 0..1
    secs = int(np.ceil(dur))
    energy = np.array([rms[(t >= s) & (t < s + 1)].mean() if ((t >= s) & (t < s + 1)).any() else 0
                       for s in range(secs)])
    energy = energy / (energy.max() or 1)
    # downbeat guess: choose phase (of 4) whose beats have the most onset strength
    onset = librosa.onset.onset_strength(y=y, sr=SR, hop_length=hop)
    if len(beats) >= 8:
        fr = np.clip(librosa.time_to_frames(beats, sr=SR, hop_length=hop), 0, len(onset) - 1)
        phase = int(np.argmax([onset[fr[p::4]].mean() for p in range(4)]))
    else:
        phase = 0
    downbeats = beats[phase::4]
    # sections from energy: split into thirds-ish by smoothed energy level
    sm = np.convolve(energy, np.ones(5) / 5, mode="same") if secs >= 5 else energy
    sections, start = [], 0
    def label(v, i, n):
        if i == 0 and v < 0.6:
            return "intro"
        if i == n - 1 and v < 0.6:
            return "outro"
        return "high" if v >= 0.7 else ("build" if v >= 0.45 else "low")
    seg = max(4, int(round(secs / 8))) if secs else 1
    n = int(np.ceil(secs / seg)) if secs else 0
    for i in range(n):
        a, b = i * seg, min(secs, (i + 1) * seg)
        v = float(sm[a:b].mean())
        sections.append({"start": float(a), "end": float(b), "energy": round(v, 2),
                         "label": label(v, i, n)})
    return {"path": str(path), "duration": round(dur, 2), "tempo": round(tempo, 1),
            "beats": [round(float(b), 3) for b in beats],
            "downbeats": [round(float(b), 3) for b in downbeats],
            "energy": [round(float(e), 2) for e in energy], "sections": sections}


def best_window(m, length):
    """Pick the start (on a downbeat) of the `length`-second window with the most energy."""
    if m["duration"] <= length:
        return 0.0
    e = np.array(m["energy"])
    best, bs = -1, 0.0
    for s in m["downbeats"] or [0.0]:
        if s + length > m["duration"]:
            break
        v = e[int(s):int(s + length)].mean()
        if v > best:
            best, bs = v, s
    return float(bs)
