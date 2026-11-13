#!/usr/bin/env bash
# Buzz installer for Linux / servers (Ubuntu 22.04/24.04 tested target). Runs as a normal user, no root needed except for the
# optional system packages mentioned below. Safe to run again: it only adds what is missing.
#   ./install_linux.sh            install into the folder this script is in
#   BUZZ_SKIP_FFMPEG=1 ...        use the ffmpeg already on the machine
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
step() { printf '\n== %s\n' "$1"; }

step "1/7  Python 3.12"
PY=""
for c in python3.12 python3.13 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] <= (3,13) else 1)' 2>/dev/null; then PY="$(command -v "$c")"; break; fi
done
if [ -z "$PY" ]; then
  echo "No suitable Python found; fetching a private Python 3.12 with uv (into $ROOT/bin and ~/.local/share/uv)."
  mkdir -p bin
  curl -fsSL https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-unknown-linux-gnu.tar.gz | tar -xz -C bin --strip-components=1
  ./bin/uv python install 3.12
  PY="$(./bin/uv python find 3.12)"
fi
echo "Using $PY ($("$PY" --version))"

step "2/7  FFmpeg (needs the drawtext filter for titles and captions)"
mkdir -p bin
have_ok() { local f="$1"; [ -x "$f" ] && "$f" -hide_banner -filters 2>/dev/null | grep -q drawtext; }
if [ "${BUZZ_SKIP_FFMPEG:-0}" = "1" ] || have_ok bin/ffmpeg || { command -v ffmpeg >/dev/null 2>&1 && have_ok "$(command -v ffmpeg)"; }; then
  echo "A suitable FFmpeg is already available."
else
  echo "Downloading a full static FFmpeg build (about 150 MB)."
  tmp="$(mktemp -d)"
  curl -fsSL https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz | tar -xJ -C "$tmp"
  cp "$tmp"/ffmpeg-*/bin/ffmpeg "$tmp"/ffmpeg-*/bin/ffprobe bin/
  rm -rf "$tmp"
fi

step "3/7  Picture renderer"
echo "Installed with the Python packages (resvg-py); no browser needed."

step "4/7  Python environment (several minutes)"
if [ ! -x .venv/bin/python ]; then
  if ! "$PY" -m venv .venv 2>/dev/null; then
    echo "python3-venv is missing; using uv to create the environment."
    [ -x bin/uv ] || { curl -fsSL https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-unknown-linux-gnu.tar.gz | tar -xz -C bin --strip-components=1; }
    rm -rf .venv; ./bin/uv venv --python "$PY" .venv
    ./bin/uv pip install --python .venv/bin/python -r requirements-linux.txt
  fi
fi
if [ -x .venv/bin/pip ] || .venv/bin/python -m pip --version >/dev/null 2>&1; then
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements-linux.txt
fi

step "5/7  Face detector (OpenCV 4 in its own folder)"
if [ ! -d assets/cv4/cv2 ]; then
  if .venv/bin/python -m pip --version >/dev/null 2>&1; then
    .venv/bin/python -m pip install --target assets/cv4 --no-deps -r requirements-cv4.txt
  else
    ./bin/uv pip install --python .venv/bin/python --target assets/cv4 --no-deps -r requirements-cv4.txt
  fi
fi

step "6/7  Folders"
mkdir -p "Reels In" "Reels Out" Work
touch .installed

step "7/7  Background services"
cat <<EOF
Installed in: $ROOT
Next: run the web page and the worker as services. Ready-made files are in deploy/:
  deploy/buzz-worker.service, deploy/buzz-web.service  (systemd user services, with CPU and memory caps)
  deploy/nginx-buzz.conf                               (reverse proxy with websocket support)
See README_LINUX.md. Quick try without services:
  .venv/bin/python src/worker.py &      .venv/bin/python -m streamlit run src/app.py --server.address 127.0.0.1 --server.port 8501
Add your Claude key on the Settings tab after signing in (it is stored encrypted, outside this folder).
EOF
