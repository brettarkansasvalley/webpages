#!/usr/bin/env bash
#curl -X POST http:127.0.0.1:8092/api/clear-toast-data
set -euo pipefail

# Always run from this script's directory so module imports and relative paths work
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Environment for Toast API — credentials live in .env (gitignored; see .env.example)
if [[ ! -f "$SCRIPT_DIR/.env" ]]; then
  echo "[start.sh] ERROR: $SCRIPT_DIR/.env not found (Toast API credentials)" >&2
  exit 1
fi
set -a
source "$SCRIPT_DIR/.env"
set +a

LOG_FILE="/tmp/uvicorn.log"
: >"$LOG_FILE"  # truncate

# Start the FastAPI app in the background (no --reload when daemonized)
APP_HOST="0.0.0.0"
APP_PORT="8001"

# Kill any process already listening on APP_PORT (e.g., previous uvicorn)
{
  echo "[start.sh] Ensuring port $APP_PORT is free..."
  PIDS=()
  if command -v lsof >/dev/null 2>&1; then
    # lsof gives us PIDs directly
    mapfile -t PIDS < <(lsof -ti TCP:$APP_PORT 2>/dev/null || true)
  else
    # Fallback: parse ss output for pid=
    mapfile -t PIDS < <(ss -ltnp 2>/dev/null | awk -v port=":$APP_PORT" '$4 ~ port { if (match($0, /pid=([0-9]+)/, m)) print m[1] }' | sort -u)
  fi
  if [[ ${#PIDS[@]} -gt 0 ]]; then
    echo "[start.sh] Found process(es) on port $APP_PORT: ${PIDS[*]} — sending TERM" >>"$LOG_FILE"
    for pid in "${PIDS[@]}"; do
      [[ -n "$pid" ]] && kill -TERM "$pid" 2>/dev/null || true
    done
    sleep 1
    # Check again; force kill if necessary
    REM=()
    if command -v lsof >/dev/null 2>&1; then
      mapfile -t REM < <(lsof -ti TCP:$APP_PORT 2>/dev/null || true)
    else
      mapfile -t REM < <(ss -ltnp 2>/dev/null | awk -v port=":$APP_PORT" '$4 ~ port { if (match($0, /pid=([0-9]+)/, m)) print m[1] }' | sort -u)
    fi
    if [[ ${#REM[@]} -gt 0 ]]; then
      echo "[start.sh] Processes still on port $APP_PORT after TERM: ${REM[*]} — sending KILL" >>"$LOG_FILE"
      for pid in "${REM[@]}"; do
        [[ -n "$pid" ]] && kill -KILL "$pid" 2>/dev/null || true
      done
      sleep 0.5
    fi
  fi
} >>"$LOG_FILE" 2>&1

# Prefer python -m uvicorn from the project's virtualenv to avoid broken entrypoint shims
UVICORN_CMD=""
if [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
  UVICORN_CMD="$SCRIPT_DIR/.venv/bin/python -m uvicorn app:app --host $APP_HOST --port $APP_PORT"
elif command -v python3 >/dev/null 2>&1; then
  # Fallback to system python3
  UVICORN_CMD="python3 -m uvicorn app:app --host $APP_HOST --port $APP_PORT"
elif command -v uvicorn >/dev/null 2>&1; then
  # Last resort, if only uvicorn shim is available
  UVICORN_CMD="uvicorn app:app --host $APP_HOST --port $APP_PORT"
else
  echo "[start.sh] ERROR: No python3 or uvicorn found in PATH, cannot start server." >>"$LOG_FILE"
  exit 1
fi

echo "[start.sh] Launching: $UVICORN_CMD" >>"$LOG_FILE"
eval "$UVICORN_CMD" >>"$LOG_FILE" 2>&1 &
UVICORN_PID=$!

# Wait for readiness with timeout
echo "[start.sh] Waiting for app to be ready on http://$APP_HOST:$APP_PORT ..." >>"$LOG_FILE"
START_TS=$(date +%s)
TIMEOUT_SEC=120
# Use 127.0.0.1 for readiness probe even if binding on 0.0.0.0
until curl -sSf -o /dev/null "http://127.0.0.1:$APP_PORT/" 2>>"$LOG_FILE"; do
  sleep 0.5
  if ! kill -0 "$UVICORN_PID" 2>/dev/null; then
    echo "[start.sh] Uvicorn process exited early. Recent log:" >>"$LOG_FILE"
    tail -n 200 "$LOG_FILE" >>"$LOG_FILE" || true
    echo "[start.sh] Aborting." >>"$LOG_FILE"
    exit 1
  fi
  now=$(date +%s)
  if (( now - START_TS > TIMEOUT_SEC )); then
    echo "[start.sh] Timeout waiting for app to start after ${TIMEOUT_SEC}s" >>"$LOG_FILE"
    tail -n 200 "$LOG_FILE" >>"$LOG_FILE" || true
    exit 1
  fi
done

echo "[start.sh] App is ready at http://$APP_HOST:$APP_PORT/" >>"$LOG_FILE"

# Try to open in a browser if a GUI session is available
if [[ -n "${DISPLAY:-}" ]]; then
  KIOSK_FLAGS=(
    --kiosk
    --start-fullscreen
    --incognito
    --noerrdialogs
    --disable-session-crashed-bubble
    --disable-infobars
    --overscroll-history-navigation=0
    --force-device-scale-factor=0.8
    --app="http://$APP_HOST:$APP_PORT/"
  )
  if command -v chromium >/dev/null 2>&1; then
    chromium "${KIOSK_FLAGS[@]}" >/dev/null 2>&1 || true
  elif command -v chromium-browser >/dev/null 2>&1; then
    chromium-browser "${KIOSK_FLAGS[@]}" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then
    # Fallback (no kiosk control)
    xdg-open "http://$APP_HOST:$APP_PORT/" >/dev/null 2>&1 || true
  fi
else
  echo "[start.sh] DISPLAY is not set; skipping browser launch (likely headless)." >>"$LOG_FILE"
fi

exit 0
