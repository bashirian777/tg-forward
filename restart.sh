#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$ROOT_DIR/.venv/bin/python"
LOG_DIR="$ROOT_DIR/data/logs"
PID_FILE="$ROOT_DIR/data/run/forwarder.pid"
cd "$ROOT_DIR"

# Validate the new configuration before stopping a healthy service.
FORWARDER_DB="$("$PYTHON" -B - <<'PY'
import json
import sqlite3
from tg_forwarder.config.migration import DEPLOYMENT_KEYS, prepare_env
from tg_forwarder.config.models import RuntimeConfig
from tg_forwarder.config.startup import StartupConfig
from tg_forwarder.config.validation import validate_runtime_config
config = StartupConfig.load()
with sqlite3.connect(config.db_path.as_uri() + '?mode=ro', uri=True) as db:
    row = db.execute('SELECT data FROM app_settings WHERE id=1').fetchone()
    if not row:
        raise SystemExit("Run 'init' before starting the service")
    data = json.loads(row[0])
    validate_runtime_config(RuntimeConfig.from_dict(data))
if DEPLOYMENT_KEYS & data.keys():
    prepare_env(config.db_path, config.env_file)
print(config.db_path)
PY
)"

OLD_PIDS=()
while read -r pid; do
    OLD_PIDS+=("$pid")
done < <("$PYTHON" -B - <<'PY'
from tg_forwarder.telegram.session_guard import project_processes
for pid in project_processes({'bot', 'serve'}):
    print(pid)
PY
)

if ((${#OLD_PIDS[@]})); then
    printf '%s\n' 'Stopping project service and waiting for workers...'
    kill -TERM "${OLD_PIDS[@]}" 2>/dev/null || true
    for _ in {1..30}; do
        RUNNING=()
        for pid in "${OLD_PIDS[@]}"; do
            state="$(ps -o stat= -p "$pid" 2>/dev/null || true)"
            if [[ -n "$state" && "$state" != Z* ]]; then
                RUNNING+=("$pid")
            fi
        done
        ((${#RUNNING[@]} == 0)) && break
        sleep 1
    done
    if ((${#RUNNING[@]})); then
        printf '%s\n' 'Old service is still exiting; new instance was not started.' >&2
        exit 1
    fi
fi

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
    "$ROOT_DIR/.venv/bin/tg-forward" migrate-env --db "$FORWARDER_DB"
fi

mkdir -p "$LOG_DIR" "$(dirname "$PID_FILE")"
nohup "$ROOT_DIR/.venv/bin/tg-forward" serve >>"$LOG_DIR/forwarder.log" 2>&1 < /dev/null &
BOT_PID=$!
printf '%s\n' "$BOT_PID" > "$PID_FILE"
sleep 2
if kill -0 "$BOT_PID" 2>/dev/null; then
    printf 'Service started. PID: %s\nLog: %s\n' "$BOT_PID" "$LOG_DIR/forwarder.log"
else
    printf 'Service exited during startup; inspect %s.\n' "$LOG_DIR/forwarder.log" >&2
    rm -f "$PID_FILE"
    exit 1
fi
