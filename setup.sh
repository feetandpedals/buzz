#!/usr/bin/env bash
# One-step Buzz setup for a Linux server (shared hosting, VPS or PC). Run as the user Buzz should run as; no root needed.
#   ./setup.sh               install everything, create buzz.env, start Buzz (as systemd services when available)
#   ./setup.sh --no-start    install only
# Safe to run again (also after unpacking a new version): it only adds what is missing and restarts Buzz.
# The free voice (about 350 MB) is not downloaded here: the owner installs it from Settings when wanted.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
START=1; [ "${1:-}" = "--no-start" ] && START=0

if [ ! -f buzz.env ]; then
  cp buzz.env.example buzz.env
  chmod 600 buzz.env
  echo "Created buzz.env with shared-hosting defaults (2 threads, 3 GB for rendering, 1 GB for the page)."
fi

bash ./install_linux.sh

[ "$START" = 1 ] || { echo; echo "Installed. Start Buzz with: ./buzzctl.sh start"; exit 0; }

echo; echo "== Starting Buzz"
if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
  bash ./buzzctl.sh stop >/dev/null 2>&1 || true   # a copy started without systemd must not hold the worker lock
  bash ./deploy/install-services.sh
  bash ./buzzctl.sh start   # waits until the page answers
else
  echo "systemd user services are not available here; starting Buzz as background processes instead."
  echo "Memory caps need systemd; the thread limit in buzz.env still applies."
  bash ./buzzctl.sh restart
  echo "To start Buzz after a reboot, add this line with 'crontab -e':"
  echo "  @reboot /bin/bash $ROOT/buzzctl.sh start"
fi

. ./buzz.env
cat <<EOF

Buzz is running on http://${BUZZ_HOST:-127.0.0.1}:${BUZZ_PORT:-8501} (this server only).
Next:
  1. Point your domain at it: deploy/nginx-buzz.conf (websockets and long timeouts are already set), then certbot for HTTPS.
  2. Open the site, create the owner account, and add the Claude key on Settings.
  3. For spoken voiceovers, press "Install the free voice" on Settings.
Day to day: ./buzzctl.sh status | restart | logs.  Full guide: DEPLOY.md
EOF
