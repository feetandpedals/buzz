"""Music provider slot. Used only when a folder has no audio file.

Provider "synth": composes an original instrumental on this PC (no download, no service, no cost).
To use another source later (a licensed library, an AI music service), add a function here and
change PROVIDER. It must return the path of a wav file.
"""
import re
import wave
from pathlib import Path

import numpy as np

PROVIDER = "synth"
SR = 44100


# (words that select it, settings). The first style whose words appear wins. Keywords typed by the owner are
# checked before the brief, so "calm acoustic sunrise" beats a brief that mentions a ride.
STYLES = [
    (r"devotion|bhajan|spiritual|temple|aarti|prayer|shiv|ganesh|mantra",
     dict(bpm=82, root=57, scale=[0, 1, 4, 5, 7, 8, 11], prog=[0, 3, 0, 4], perc="tabla", name="devotional")),
    (r"diwali|festiv|celebrat|wedding|dhoom|bollywood|dhol|bhangra|indian|desi|party",
     dict(bpm=104, root=62, scale=[0, 1, 4, 5, 7, 8, 10], prog=[0, 5, 3, 4], perc="tabla", name="festive")),
    (r"lofi|lo-fi|chill|jazz|coffee|study|mellow|cozy|cosy",
     dict(bpm=78, root=57, scale=[0, 3, 5, 7, 10, 12, 15], prog=[0, 5, 3, 4], perc="soft", name="chill")),
    (r"calm|peace|serene|sunrise|yoga|relax|gentle|nature|ambient|acoustic|soft|meditat",
     dict(bpm=84, root=57, scale=[0, 2, 4, 7, 9, 11, 12], prog=[0, 3, 4, 3], perc="soft", name="calm")),
    (r"epic|cinematic|dramatic|trailer|heroic|powerful|intense",
     dict(bpm=96, root=55, scale=[0, 2, 3, 5, 7, 8, 10], prog=[0, 5, 3, 6], perc="kick", name="epic")),
    (r"romantic|love|emotional|sad|nostalgi|tender|sentimental",
     dict(bpm=72, root=57, scale=[0, 2, 3, 5, 7, 8, 10], prog=[0, 5, 2, 6], perc="soft", name="emotional")),
    (r"edm|dance|club|electro|disco|house|techno",
     dict(bpm=126, root=59, scale=[0, 2, 3, 5, 7, 8, 10], prog=[0, 5, 2, 6], perc="kick", name="dance")),
    (r"energ|ride|cycl|race|adventure|sport|fast|rock|workout|gym|run",
     dict(bpm=122, root=57, scale=[0, 2, 3, 5, 7, 8, 10], prog=[0, 5, 2, 6], perc="kick", name="energetic")),
    (r"happy|bright|fun|cheerful|pop|upbeat|joy|playful|summer",
     dict(bpm=116, root=60, scale=[0, 2, 4, 5, 7, 9, 11], prog=[0, 4, 5, 3], perc="kick", name="happy")),
]


def clean_keywords(text):
    """Up to three short words from what the owner typed (letters, numbers and hyphens only)."""
    words = re.findall(r"[A-Za-z0-9\-]{2,20}", text or "")
    return " ".join(words[:3])


def _mood(brief, keywords=""):
    for text in (clean_keywords(keywords).lower(), (brief or "").lower()):
        for pattern, mood in STYLES:
            if text and re.search(pattern, text):
                return dict(mood)
    return dict(bpm=108, root=60, scale=[0, 2, 4, 5, 7, 9, 11], prog=[0, 4, 5, 3], perc="kick", name="upbeat")


def _hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def _note(freq, dur, kind="pluck"):
    t = np.arange(int(dur * SR)) / SR
    if kind == "pad":
        w = sum(np.sin(2 * np.pi * freq * k * t + k) / k for k in (1, 2, 3)) * 0.5
        env = np.minimum(t / 0.25, 1) * np.exp(-t * 0.6)
    elif kind == "bass":
        # strong 2nd and 3rd harmonics: phone and laptop speakers cannot play the low fundamental, they play these
        w = (np.sin(2 * np.pi * freq * t) + 0.9 * np.sin(2 * np.pi * freq * 2 * t)
             + 0.6 * np.sin(2 * np.pi * freq * 3 * t))
        env = np.minimum(t / 0.01, 1) * np.exp(-t * 4)
    else:  # pluck
        w = sum(np.sin(2 * np.pi * freq * k * t) / k ** 1.5 for k in (1, 2, 3, 4))
        env = np.minimum(t / 0.004, 1) * np.exp(-t * 7)
    return w * env


def _drum(kind, n):
    t = np.arange(n) / SR
    if kind == "kick":
        f = 120 * np.exp(-t * 30) + 55
        click = np.random.default_rng(3).standard_normal(n) * np.exp(-t * 220) * 0.5  # audible attack on small speakers
        return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9) + click
    if kind == "hat":
        return np.random.default_rng(1).standard_normal(n) * np.exp(-t * 90) * 0.35
    if kind == "clap":
        return np.random.default_rng(2).standard_normal(n) * np.exp(-t * 28) * 0.5
    if kind == "tabla":  # tuned skin hit
        return np.sin(2 * np.pi * (180 * np.exp(-t * 6) + 110) * t) * np.exp(-t * 14)
    return np.zeros(n)


def compose(out_wav, brief="", length=62.0, keywords=""):
    mood = _mood(brief, keywords)
    rng = np.random.default_rng(7)
    beat = 60.0 / mood["bpm"]
    n = int((length + 2) * SR)
    mix = np.zeros((n, 2))

    def put(sig, at, gain=1.0, pan=0.0):
        i = int(at * SR)
        if i >= n:
            return
        sig = sig[: n - i] * gain
        mix[i:i + len(sig), 0] += sig * (1 - max(pan, 0))
        mix[i:i + len(sig), 1] += sig * (1 + min(pan, 0))

    sc = mood["scale"]
    bars = int(length / (beat * 4)) + 2
    for bar in range(bars):
        t0 = bar * 4 * beat
        deg = mood["prog"][bar % 4]
        base = mood["root"] + sc[deg % len(sc)] - 12
        triad = [mood["root"] + sc[(deg + k) % len(sc)] + 12 * ((deg + k) // len(sc)) for k in (0, 2, 4)]
        intro, lift = bar < 2, 4 <= bar < bars - 2
        for m_ in triad:
            put(_note(_hz(m_ + 12), beat * 4, "pad"), t0, 0.07, rng.uniform(-0.4, 0.4))
        for s in range(8):  # eighth-note bass
            if not intro or s % 2 == 0:
                put(_note(_hz(base if s % 4 != 3 else base + 7), beat * 0.5, "bass"), t0 + s * beat / 2, 0.15)
        for s in range(16 if lift else 8):  # arpeggio melody (also in the intro, so there is a tune from the first second)
            step = beat / (4 if lift else 2)
            m_ = triad[[0, 1, 2, 1][s % 4]] + (12 if s % 8 >= 4 else 0)
            put(_note(_hz(m_ + 12), step * 1.8, "pluck"), t0 + s * step, 0.30, (-1) ** s * 0.3)
            if bar >= 2 and s % 2 == 0:  # a bright octave on top
                put(_note(_hz(m_ + 24), step * 1.2, "pluck"), t0 + s * step, 0.12, (-1) ** s * -0.4)
        for b_ in range(4):  # percussion
            tt = t0 + b_ * beat
            if mood["perc"] in ("kick", "tabla") and (not intro or b_ % 2 == 0):
                put(_drum("kick" if mood["perc"] == "kick" else "tabla", int(0.4 * SR)), tt, 0.32)
            if mood["perc"] == "soft":
                put(_drum("tabla", int(0.3 * SR)), tt, 0.22)
            if b_ in (1, 3) and not intro:
                put(_drum("clap", int(0.2 * SR)), tt, 0.55)
            put(_drum("hat", int(0.1 * SR)), tt + beat / 2, 0.5 if not intro else 0.3)
    mix = mix[: int(length * SR)]
    mix[1:] = mix[1:] - 0.55 * mix[:-1]  # gentle tilt towards the highs: small speakers then carry the tune
    fade = int(2.0 * SR)
    mix[-fade:] *= np.linspace(1, 0, fade)[:, None]
    mix[:int(0.05 * SR)] *= np.linspace(0, 1, int(0.05 * SR))[:, None]
    mix /= max(np.abs(mix).max(), 1e-6) / 0.89
    pcm = (mix * 32767).astype("<i2")
    Path(out_wav).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(2), w.setsampwidth(2), w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return str(out_wav)


def make_music(out_wav, brief="", length=62.0, keywords=""):
    if PROVIDER == "synth":
        return compose(out_wav, brief, length, keywords)
    raise RuntimeError(f"Unknown music provider: {PROVIDER}")
