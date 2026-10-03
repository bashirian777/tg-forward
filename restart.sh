#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$ROOT_DIR/logs"
LOG_FILE="$LOG_DIR/bot.log"
PID_FILE="$ROOT_DIR/bot.pid"

# Select only bot commands whose working directory is this project.
BOT_PATTERN='[p]ython(3(\.[0-9]+)?)? -m src\.main bot'

printf '%s\n' 'Stopping existing bot processes...'
OLD_PIDS=()
while read -r pid; do
    if [[ "$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)" == "$ROOT_DIR" ]]; then
        OLD_PIDS+=("$pid")
    fi
done < <(pgrep -f "$BOT_PATTERN" || true)

if ((${#OLD_PIDS[@]} > 0)); then
    kill -TERM "${OLD_PIDS[@]}" 2>/dev/null || true

    for _ in {1..10}; do
        RUNNING=()
        for pid in "${OLD_PIDS[@]}"; do
            if kill -0 "$pid" 2>/dev/null; then
                RUNNING+=("$pid")
            fi
        done
        ((${#RUNNING[@]} == 0)) && break
        sleep 1
    done

    for pid in "${RUNNING[@]:-}"; do
        kill -KILL "$pid" 2>/dev/null || true
    done
fi

if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    PYTHON="$ROOT_DIR/.venv/bin/python"
elif command -v python >/dev/null 2>&1; then
    PYTHON="$(command -v python)"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="$(command -v python3)"
else
    printf '%s\n' 'Error: python/python3 was not found.' >&2
    exit 1
fi

mkdir -p "$LOG_DIR"
rm -f "$PID_FILE"

printf 'Starting bot with %s...\n' "$PYTHON"
cd "$ROOT_DIR" || exit 1
nohup "$PYTHON" -m src.main bot >>"$LOG_FILE" 2>&1 < /dev/null &
BOT_PID=$!
printf '%s\n' "$BOT_PID" > "$PID_FILE"

sleep 2
if kill -0 "$BOT_PID" 2>/dev/null; then
    printf 'Bot started in background. PID: %s\n' "$BOT_PID"
    printf 'Log: %s\n' "$LOG_FILE"
    printf 'PID file: %s\n' "$PID_FILE"
else
    printf '%s\n' 'Error: bot exited during startup.' >&2
    tail -40 "$LOG_FILE" >&2 || true
    rm -f "$PID_FILE"
    exit 1
fi
