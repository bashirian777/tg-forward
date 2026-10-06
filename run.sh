#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf '%s\n' 'Usage: bash run.sh {start|stop|restart|status}' \
        '  start    Start in the background (leave an existing instance running)' \
        '  stop     Stop and wait for workers to exit' \
        '  restart  Check configuration, then stop and start' \
        '  status   Show whether the process is running'
}

ACTION="${1:-help}"
if (($# > 1)); then
    usage >&2
    exit 2
fi
case "$ACTION" in
    start|stop|restart|status) ;;
    help|-h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
esac

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$ROOT_DIR/.venv/bin/python"
RUN_DIR="$ROOT_DIR/data/run"
LOG_FILE="$ROOT_DIR/data/logs/forwarder.log"
PID_FILE="$RUN_DIR/forwarder.pid"
cd "$ROOT_DIR"
export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

if [[ ! -x "$PYTHON" ]]; then
    printf '%s\n' 'Python environment missing. Run: uv venv --python 3.12' >&2
    exit 1
fi

# Serialize changes so concurrent start/restart calls cannot create two instances.
if [[ "$ACTION" != status ]]; then
    mkdir -p "$RUN_DIR"
    exec 9>"$RUN_DIR/control.lock"
    if ! flock -n 9; then
        printf '%s\n' 'Another start/stop/restart operation is in progress; try again shortly.' >&2
        exit 1
    fi
fi

is_running() {
    local state
    state="$(ps -o stat= -p "$1" 2>/dev/null || true)"
    [[ -n "$state" && "$state" != Z* ]]
}

find_processes() {
    local output pid
    ACTIVE_PIDS=()
    output="$("$PYTHON" -B - <<'PY'
from tg_forwarder.telegram.session_guard import project_processes
for pid in project_processes({'bot', 'serve'}):
    print(pid)
PY
)"
    while read -r pid; do
        if [[ -n "$pid" ]] && is_running "$pid"; then
            ACTIVE_PIDS+=("$pid")
        fi
    done <<< "$output"
}

show_status() {
    if ((${#ACTIVE_PIDS[@]})); then
        printf 'Running. PID: %s\nLog: %s\n' "${ACTIVE_PIDS[*]}" "$LOG_FILE"
    else
        printf '%s\n' 'Stopped.'
    fi
}

validate_startup() {
    # Check before stopping a healthy process when restarting.
    FORWARDER_DB="$("$PYTHON" -B - <<'PY'
import json
import sqlite3
from tg_forwarder.config.migration import DEPLOYMENT_KEYS, prepare_env
from tg_forwarder.config.models import RuntimeConfig
from tg_forwarder.config.startup import StartupConfig
from tg_forwarder.config.validation import validate_runtime_config
config = StartupConfig.load()
if not config.db_path.is_file():
    raise SystemExit("Run 'python main.py init' before starting")
with sqlite3.connect(config.db_path.as_uri() + '?mode=ro', uri=True) as db:
    row = db.execute('SELECT data FROM app_settings WHERE id=1').fetchone()
    if not row:
        raise SystemExit("Run 'python main.py init' before starting")
    data = json.loads(row[0])
    validate_runtime_config(RuntimeConfig.from_dict(data))
if DEPLOYMENT_KEYS & data.keys():
    prepare_env(config.db_path, config.env_file)
print(config.db_path)
PY
)"
}

stop_processes() {
    if ((${#ACTIVE_PIDS[@]} == 0)); then
        rm -f "$PID_FILE"
        printf '%s\n' 'Already stopped.'
        return
    fi
    printf '%s\n' 'Stopping and waiting for workers...'
    # Identify project processes instead of trusting a stale or reused PID file.
    kill -TERM "${ACTIVE_PIDS[@]}" 2>/dev/null || true
    local attempt pid
    local -a running
    for attempt in {1..30}; do
        running=()
        for pid in "${ACTIVE_PIDS[@]}"; do
            if is_running "$pid"; then
                running+=("$pid")
            fi
        done
        if ((${#running[@]} == 0)); then
            rm -f "$PID_FILE"
            printf '%s\n' 'Stopped.'
            return
        fi
        sleep 1
    done
    printf 'Process is still exiting. PID: %s. No new instance was started.\n' "${running[*]}" >&2
    return 1
}

start_process() {
    # Complete the one-time migration only after the old process has exited.
    if "$PYTHON" -B - "$FORWARDER_DB" <<'PY'
import json
import sqlite3
import sys
from tg_forwarder.config.migration import DEPLOYMENT_KEYS
with sqlite3.connect('file:' + sys.argv[1] + '?mode=ro', uri=True) as db:
    data = json.loads(db.execute('SELECT data FROM app_settings WHERE id=1').fetchone()[0])
sys.exit(0 if DEPLOYMENT_KEYS & data.keys() else 1)
PY
    then
        "$PYTHON" "$ROOT_DIR/main.py" migrate-env --db "$FORWARDER_DB"
    fi
    mkdir -p "$(dirname "$LOG_FILE")"
    # The background process must not inherit the control lock.
    nohup "$PYTHON" "$ROOT_DIR/main.py" serve 9>&- >>"$LOG_FILE" 2>&1 < /dev/null &
    local pid=$!
    printf '%s\n' "$pid" > "$PID_FILE"
    sleep 2
    if is_running "$pid"; then
        printf 'Started in background. PID: %s\nLog: %s\n' "$pid" "$LOG_FILE"
    else
        rm -f "$PID_FILE"
        printf 'Process exited during startup; inspect %s.\n' "$LOG_FILE" >&2
        return 1
    fi
}

find_processes
case "$ACTION" in
    status) show_status ;;
    stop) stop_processes ;;
    start)
        if ((${#ACTIVE_PIDS[@]})); then
            printf '%s\n' 'Already running; use restart to restart it.'
            show_status
        else
            rm -f "$PID_FILE"
            validate_startup
            start_process
        fi
        ;;
    restart)
        validate_startup
        stop_processes
        start_process
        ;;
esac
