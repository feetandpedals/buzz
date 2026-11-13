"""Helper process for the free voice (Kokoro). Started by voice_provider, reads one JSON request per line on stdin and
answers one JSON line on stdout. Running the model in its own process means ALL its memory goes back to the system when
the reel is done and the helper ends, which keeps a long-running server healthy."""
import json
import os
import subprocess
import sys
from pathlib import Path

PROTO = sys.stdout          # the answers go here
sys.stdout = sys.stderr     # anything a library prints must not corrupt the answers

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import FFMPEG, ROOT  # noqa: E402

MODELS = ROOT / "Work" / "models"
_model = None
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def load():
    global _model
    if _model is None:
        import onnxruntime as rt
        from kokoro_onnx import Kokoro
        so = rt.SessionOptions()
        so.enable_cpu_mem_arena = False
        so.enable_mem_pattern = False
        so.intra_op_num_threads = max(1, min(4, os.cpu_count() or 1))
        sess = rt.InferenceSession(str(MODELS / "kokoro-v1.0.onnx"), sess_options=so, providers=["CPUExecutionProvider"])
        _model = Kokoro.from_session(sess, str(MODELS / "voices-v1.0.bin"))
    return _model


def synth(req):
    import soundfile as sf
    name = req["voice"].split(":", 1)[1]
    samples, sr = load().create(req["text"], voice=name, speed=float(req.get("rate", 1.0)),
                                lang="en-gb" if name.startswith("b") else "en-us")
    out = Path(req["out"])
    wav = out.with_suffix(".wav")
    sf.write(str(wav), samples, sr)
    r = subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(wav), "-codec:a", "libmp3lame", "-q:a", "3", str(out)],
                       capture_output=True, text=True, creationflags=_NO_WINDOW)
    wav.unlink(missing_ok=True)
    if r.returncode:
        raise RuntimeError("Could not save the free voice: " + r.stderr[-200:])


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            synth(json.loads(line))
            ans = {"ok": True}
        except Exception as e:  # report, keep running
            ans = {"ok": False, "error": str(e)[:300]}
        PROTO.write(json.dumps(ans) + "\n")
        PROTO.flush()


if __name__ == "__main__":
    main()
