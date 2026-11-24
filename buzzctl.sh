#!/usr/bin/env bash
# Start, stop and check Buzz on a Linux server. Uses the systemd user services when they are installed
# (deploy/install-services.sh); otherwise runs the two programs in the background itself.
#   ./buzzctl.sh start | stop | restart | status | logs
#   ./buzzctl.sh run-web | run-worker      (used by the systemd services; runs in the foreground)
# Settings come from buzz.env in this folder.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
if [ -f buzz.env ]; then set -a; . ./buzz.env; set +a; fi
HOST="${BUZZ_HOST:-127.0.0.1}"
PORT="${BUZZ_PORT:-8501}"
UPLOAD="${BUZZ_MAX_UPLOAD_MB:-1500}"
PY="$ROOT/.venv/bin/python"
RUN="$ROOT/Work/run"
mkdir -p "$RUN" "$ROOT/Work/logs"

units() { command -v systemctl >/dev/null 2>&1 && systemctl --user cat buzz-web >/dev/null 2>&1; }
alive() { [ -f "$RUN/$1.pid" ] && kill -0 "$(cat "$RUN/$1.pid")" 2>/dev/null; }

run_web() {
  exec "$PY" -m streamlit run "$ROOT/src/app.py" --server.address "$HOST" --server.port "$PORT" --server.headless true \
    --browser.gatherUsageStats false --server.maxUploadSize "$UPLOAD" --server.fileWatcherType none
}
run_worker() { exec "$PY" "$ROOT/src/worker.py"; }

bg() {  # name, nice level, command
  local name="$1" lvl="$2"; shift 2
  if alive "$name"; then echo "$name already running (pid $(cat "$RUN/$name.pid"))"; return; fi
  nohup nice -n "$lvl" "$@" >>"$ROOT/Work/logs/$name.out" 2>&1 </dev/null &
  echo $! >"$RUN/$name.pid"
  echo "$name started (pid $!)"
}

health() {
  for _ in $(seq 1 45); do
    if curl -fsS "http://$HOST:$PORT/_stcore/health" >/dev/null 2>&1; then echo "Web page is answering on http://$HOST:$PORT"; return 0; fi
    sleep 1
  done
  echo "The web page did not answer on http://$HOST:$PORT. See: ./buzzctl.sh logs"; return 1
}

case "${1:-status}" in
  run-web) run_web ;;
  run-worker) run_worker ;;
  start)
    if units; then systemctl --user start buzz-worker buzz-web
    else
      bg worker 10 bash "$0" run-worker
      bg web 5 bash "$0" run-web
    fi
    health ;;
  stop)
    if units; then systemctl --user stop buzz-web buzz-worker || true; fi
    for n in web worker; do
      if alive "$n"; then kill "$(cat "$RUN/$n.pid")" && echo "$n stopped"; fi
      rm -f "$RUN/$n.pid"
    done
    if [ -f Work/worker.lock ]; then kill "$(cat Work/worker.lock)" 2>/dev/null || true; rm -f Work/worker.lock; fi ;;
  restart) bash "$0" stop; sleep 2; bash "$0" start ;;
  status)
    if units; then systemctl --user --no-pager --lines=0 status buzz-worker buzz-web | grep -E "●|Active|Memory|CPU" || true
    else for n in worker web; do alive "$n" && echo "$n: running (pid $(cat "$RUN/$n.pid"))" || echo "$n: stopped"; done; fi
    [ -f Work/heartbeat.txt ] && echo "Worker last checked in: $(cat Work/heartbeat.txt)"
    curl -fsS "http://$HOST:$PORT/_stcore/health" >/dev/null 2>&1 && echo "Web page: answering on http://$HOST:$PORT" || echo "Web page: not answering" ;;
  logs)
    if units; then journalctl --user -u buzz-web -u buzz-worker -n 60 --no-pager || true; fi
    tail -n 40 Work/logs/worker.log Work/logs/*.out 2>/dev/null || true ;;
  *) echo "Usage: $0 start|stop|restart|status|logs"; exit 2 ;;
esac
