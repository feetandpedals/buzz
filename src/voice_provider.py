"""Voice providers (optional), English voices only.
1. Kokoro: free, open source, runs on this PC, no key. Voice names start with "kokoro:".
2. Google Cloud Text-to-Speech: needs a key kept in Windows Credential Manager (entry google_tts), never in a file.
Without either, the app works as before, just without a voiceover. To use another service, add a function in synth()."""
import base64
import hashlib
import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import keyring

from common import FFMPEG, FFPROBE

PROVIDER = "google"
MODELS = Path(__file__).resolve().parent.parent / "Work" / "models"
KOKORO_FILES = {"kokoro-v1.0.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
                "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"}
KOKORO_VOICES = {
    "kokoro:af_heart": "Free voice: US, woman (warm)",
    "kokoro:af_bella": "Free voice: US, woman (bright)",
    "kokoro:am_michael": "Free voice: US, man (calm)",
    "kokoro:am_fenrir": "Free voice: US, man (deep)",
    "kokoro:bf_emma": "Free voice: UK, woman",
    "kokoro:bm_george": "Free voice: UK, man",
}
KOKORO_DEFAULT = "kokoro:af_heart"
_kokoro = None
SERVICE, ENTRY = "ai-reel-studio", "google_tts"

# label -> Google voice name (English only)
VOICES = {
    "en-IN-Neural2-A": "India, woman (warm)",
    "en-IN-Neural2-B": "India, man (calm)",
    "en-IN-Neural2-C": "India, man (energetic)",
    "en-IN-Neural2-D": "India, woman (bright)",
    "en-GB-Neural2-A": "UK, woman",
    "en-GB-Neural2-B": "UK, man",
    "en-US-Neural2-F": "US, woman",
    "en-US-Neural2-D": "US, man",
}
DEFAULT_VOICE = "en-IN-Neural2-A"


def google_ready():
    try:
        return bool(keyring.get_password(SERVICE, ENTRY))
    except Exception:
        return False


def kokoro_ready():
    try:
        import kokoro_onnx  # noqa: F401
    except Exception:
        return False
    return all((MODELS / n).exists() and (MODELS / n).stat().st_size > 1_000_000 for n in KOKORO_FILES)


def available():
    return google_ready() or kokoro_ready()


def voices():
    """Voices the user can pick right now: label by name."""
    out = {}
    if google_ready():
        out.update(VOICES)
    if kokoro_ready():
        out.update(KOKORO_VOICES)
    return out


def default_voice():
    return DEFAULT_VOICE if google_ready() else KOKORO_DEFAULT


def install_kokoro():
    """Downloads the two free-voice model files (about 330 MB) next to the app. Safe to run again."""
    MODELS.mkdir(parents=True, exist_ok=True)
    for name, url in KOKORO_FILES.items():
        dest = MODELS / name
        if dest.exists() and dest.stat().st_size > 1_000_000:
            continue
        tmp = dest.with_suffix(".part")
        with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
        tmp.replace(dest)
    return kokoro_ready()


def _synth_kokoro(text, out_mp3, voice, rate=1.0):
    global _kokoro
    import soundfile as sf
    if _kokoro is None:
        from kokoro_onnx import Kokoro
        _kokoro = Kokoro(str(MODELS / "kokoro-v1.0.onnx"), str(MODELS / "voices-v1.0.bin"))
    name = voice.split(":", 1)[1]
    samples, sr = _kokoro.create(text, voice=name, speed=rate, lang="en-gb" if name.startswith("b") else "en-us")
    wav = Path(out_mp3).with_suffix(".wav")
    sf.write(str(wav), samples, sr)
    r = subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(wav), "-codec:a", "libmp3lame", "-q:a", "3", str(out_mp3)],
                       capture_output=True, text=True)
    wav.unlink(missing_ok=True)
    if r.returncode:
        raise RuntimeError("Could not save the free voice: " + r.stderr[-200:])
    return Path(out_mp3)


def save_key(value):
    keyring.set_password(SERVICE, ENTRY, value.strip())


def synth(text, out_mp3, voice=DEFAULT_VOICE, rate=1.0):
    """One line of text -> mp3 file. Raises with a plain message if the service refuses."""
    if voice.startswith("kokoro:") or (not google_ready() and kokoro_ready()):
        return _synth_kokoro(text, out_mp3, voice if voice.startswith("kokoro:") else KOKORO_DEFAULT, rate)
    key = keyring.get_password(SERVICE, ENTRY)
    if not key:
        raise RuntimeError("No Google voice key saved.")
    body = json.dumps({"input": {"text": text}, "voice": {"languageCode": voice[:5], "name": voice},
                       "audioConfig": {"audioEncoding": "MP3", "speakingRate": rate}}).encode()
    req = urllib.request.Request("https://texttospeech.googleapis.com/v1/text:synthesize",
                                 data=body, headers={"Content-Type": "application/json", "X-Goog-Api-Key": key})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            audio = base64.b64decode(json.load(r)["audioContent"])
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Google voice refused the request ({e.code}). Check the key and that the Text-to-Speech "
                           f"service is enabled.") from None
    Path(out_mp3).write_bytes(audio)
    return Path(out_mp3)


def _length(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


def narrate(lines, job_dir, voice=DEFAULT_VOICE):
    """lines: list of sentences. Returns (voice_wav_path, [(start, length) per line]).
    Each line is spoken, then 0.45 s of air; the lines are joined into one track."""
    job_dir = Path(job_dir)
    vdir = job_dir / "voice"
    vdir.mkdir(exist_ok=True)
    parts, spans, t = [], [], 0.0
    for n, text in enumerate(lines):
        mp3 = vdir / f"line_{n + 1}_{hashlib.md5((text + voice).encode()).hexdigest()[:8]}.mp3"
        if not mp3.exists():
            for old in vdir.glob(f"line_{n + 1}_*.mp3"):
                old.unlink()
            synth(text, mp3, voice)
        ln = _length(mp3)
        parts.append(mp3)
        spans.append((round(t, 3), round(ln, 3)))
        t += ln + 0.45
    out = job_dir / "voiceover.wav"
    cmd = [FFMPEG, "-v", "error", "-y"]
    for p in parts:
        cmd += ["-i", str(p)]
    fc = "".join(f"[{i}:a]aresample=44100,apad=pad_dur=0.45[a{i}];" for i in range(len(parts)))
    fc += "".join(f"[a{i}]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=0:a=1[o]"
    cmd += ["-filter_complex", fc, "-map", "[o]", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("Could not join the voice lines: " + r.stderr[-200:])
    return out, spans
