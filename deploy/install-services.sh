#!/usr/bin/env bash
# Installs Buzz's two services (worker and web page) as systemd USER services for the user running this script,
# pointing at this Buzz folder with the limits from buzz.env, and starts them. Run by setup.sh. Safe to run again.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$ROOT/buzz.env" ] && { set -a; . "$ROOT/buzz.env"; set +a; }
DEST="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$DEST"
# MemoryHigh (gentle slow-down) at 85% of the hard cap
to_mb() { local v="$1" n u; n="${v%[KMGTkmgt]}"; u="$(echo "${v#"$n"}" | tr a-z A-Z)"; case "$u" in G) echo $((n*1024));; M) echo "$n";; K) echo $((n/1024));; *) echo $((n/1048576));; esac; }
WM="${BUZZ_WORKER_MEMORY:-3G}"; BM="${BUZZ_WEB_MEMORY:-1G}"
for u in buzz-worker buzz-web; do
  sed -e "s#@ROOT@#$ROOT#g" -e "s#@CPU_QUOTA@#${BUZZ_CPU_QUOTA:-200%}#" \
      -e "s#@WORKER_MEMORY@#$WM#" -e "s#@WORKER_MEMORY_HIGH@#$(( $(to_mb "$WM") * 85 / 100 ))M#" \
      -e "s#@WEB_MEMORY@#$BM#" -e "s#@WEB_MEMORY_HIGH@#$(( $(to_mb "$BM") * 85 / 100 ))M#" \
      "$ROOT/deploy/$u.service" > "$DEST/$u.service"
  echo "Installed $DEST/$u.service"
done
systemctl --user daemon-reload
systemctl --user enable buzz-worker buzz-web >/dev/null
systemctl --user restart buzz-worker buzz-web
echo
systemctl --user --no-pager --lines=0 status buzz-worker buzz-web | grep -E "Loaded|Active" || true
if command -v loginctl >/dev/null 2>&1 && [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]; then
  echo
  echo "Services stop when you log out unless lingering is on. Ask an administrator to run once:  sudo loginctl enable-linger $USER"
fi
