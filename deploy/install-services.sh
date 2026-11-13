#!/usr/bin/env bash
# Installs Buzz's two services (worker and web page) as systemd USER services for the user running this script,
# pointing at this Buzz folder, and starts them. Run after install_linux.sh. Safe to run again.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$DEST"
for u in buzz-worker buzz-web; do
  sed "s#%h/buzz#$ROOT#g" "$ROOT/deploy/$u.service" > "$DEST/$u.service"
  echo "Installed $DEST/$u.service"
done
systemctl --user daemon-reload
systemctl --user enable --now buzz-worker buzz-web
echo
systemctl --user --no-pager --lines=0 status buzz-worker buzz-web | grep -E "Loaded|Active" || true
if command -v loginctl >/dev/null 2>&1 && [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]; then
  echo
  echo "Services stop when you log out unless lingering is on. Ask an administrator to run once:  sudo loginctl enable-linger $USER"
fi
echo "The web page listens on 127.0.0.1:8501 only. Put nginx in front of it (deploy/nginx-buzz.conf) for outside access."
