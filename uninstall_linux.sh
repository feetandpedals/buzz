#!/usr/bin/env bash
# Buzz uninstaller for Linux / servers. Stops and removes the Buzz services and the Python environment.
# Your reels, accounts and settings stay unless you choose otherwise. It asks before every destructive step.
#   ./uninstall_linux.sh --dry-run   shows what would happen and changes nothing
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1
act() { if [ "$DRY" = 1 ]; then echo "[dry run] $1"; else echo "$1"; shift; "$@"; fi; }
ask() { if [ "$DRY" = 1 ]; then return 1; fi; read -r -p "$1 " a; [ "${a:-}" = "y" ] || [ "${a:-}" = "Y" ]; }
echo "Buzz uninstaller for: $ROOT"

if [ "$DRY" = 0 ]; then
  read -r -p "Remove Buzz's services and Python environment? Your reels and settings stay. [Y/n] " go
  [ "${go:-Y}" = "n" ] || [ "${go:-Y}" = "N" ] && { echo "Nothing changed."; exit 0; }
fi

UNITS_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
for u in buzz-worker buzz-web; do
  if command -v systemctl >/dev/null 2>&1 && [ -f "$UNITS_DIR/$u.service" ]; then
    act "Stopping and disabling $u" systemctl --user disable --now "$u"
    act "Removing $UNITS_DIR/$u.service" rm -f "$UNITS_DIR/$u.service"
    [ -d "$UNITS_DIR/$u.service.d" ] && act "Removing the resource-limit overrides in $UNITS_DIR/$u.service.d" rm -rf "$UNITS_DIR/$u.service.d" || true
  fi
done
command -v systemctl >/dev/null 2>&1 && act "Reloading systemd" systemctl --user daemon-reload || true

# a worker started without systemd
if [ -f "$ROOT/Work/worker.lock" ]; then
  act "Stopping the worker process" bash -c "kill \$(cat '$ROOT/Work/worker.lock') 2>/dev/null || true; rm -f '$ROOT/Work/worker.lock'"
fi
act "Removing the Python environment (.venv)" rm -rf "$ROOT/.venv"
act "Removing the install marker" rm -f "$ROOT/.installed"

SECRETS="${BUZZ_SECRETS_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/buzz}"
if [ -d "$SECRETS" ] && ask "Also delete the encrypted keys and master key in $SECRETS? [y/N]"; then
  act "Deleting $SECRETS" rm -rf "$SECRETS"
fi
if ask "Also delete the whole Buzz folder $ROOT, INCLUDING all reels and accounts? Type y to confirm [y/N]"; then
  act "Deleting $ROOT" bash -c "cd / && rm -rf '$ROOT'"
  echo "Done. Buzz and its data are gone."
  exit 0
fi
if [ "$DRY" = 1 ]; then echo; echo "Dry run finished. Nothing was changed."; exit 0; fi
echo; echo "Done. Buzz is uninstalled. Your reels, accounts and settings are still in $ROOT."
echo "(Python, FFmpeg and any system packages were left installed.)"
