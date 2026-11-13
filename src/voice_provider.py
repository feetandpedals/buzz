"""Voice providers (optional), English voices only.
1. Kokoro: free, open source, runs on this PC, no key. Voice names start with "kokoro:".
2. Google Cloud Text-to-Speech: needs a key kept in Windows Credential Manager (entry google_tts), never in a file.
Without either, the app works as before, just without a voiceover. To use another service, add a function in synth()."""
import base64
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import secrets_store as vault

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
        return bool(vault.get_password(SERVICE, ENTRY))
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


_helper = None
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
HELPER_TIMEOUT = 600  # seconds for one line, including loading the model the first time


def _start_helper():
    global _helper
    if _helper is None or _helper.poll() is not None:
        _helper = subprocess.Popen([sys.executable, str(Path(__file__).with_name("voice_worker.py"))], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1,
                                   creationflags=_NO_WINDOW)
    return _helper


def release():
    """Ends the voice helper process after a reel. The free voice lives in its own process, so ALL of its memory
    (about 1 GB) returns to the system instead of staying with a long-running worker."""
    global _helper
    h, _helper = _helper, None
    if h is None:
        return
    try:
        h.stdin.close()
        h.wait(timeout=15)
    except Exception:
        h.kill()


def _synth_kokoro(text, out_mp3, voice, rate=1.0):
    import queue
    import threading
    for attempt in (1, 2):  # one automatic restart if the helper died
        h = _start_helper()
        try:
            h.stdin.write(json.dumps({"text": text, "voice": voice, "rate": rate, "out": str(out_mp3)}) + "\n")
            h.stdin.flush()
            q = queue.Queue()
            threading.Thread(target=lambda: q.put(h.stdout.readline()), daemon=True).start()
            line = q.get(timeout=HELPER_TIMEOUT)
            if not line:
                raise BrokenPipeError("voice helper ended")
            ans = json.loads(line)
        except (BrokenPipeError, OSError, queue.Empty, ValueError):
            try:
                h.kill()
            except Exception:
                pass
            if attempt == 2:
                raise RuntimeError("The free voice stopped unexpectedly. Please try again.")
            continue
        if not ans.get("ok"):
            raise RuntimeError(ans.get("error") or "The free voice could not speak this line.")
        return Path(out_mp3)


def save_key(value):
    vault.set_password(SERVICE, ENTRY, value.strip())


def synth(text, out_mp3, voice=DEFAULT_VOICE, rate=1.0):
    """One line of text -> mp3 file. Raises with a plain message if the service refuses."""
    if voice.startswith("kokoro:") or (not google_ready() and kokoro_ready()):
        return _synth_kokoro(text, out_mp3, voice if voice.startswith("kokoro:") else KOKORO_DEFAULT, rate)
    key = vault.get_password(SERVICE, ENTRY)
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
