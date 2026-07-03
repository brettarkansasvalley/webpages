#!/bin/bash
# Start the Toasty Webapp API with auto-fetch scheduler

# Kill any existing API processes
fuser -k 5000/tcp 2>/dev/null
sleep 2

# Set working directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Toast API credentials — loaded from .env (gitignored; see ../.env.example)
if [ ! -f "$SCRIPT_DIR/.env" ]; then
  echo "ERROR: $SCRIPT_DIR/.env not found (Toast API credentials)" >&2
  exit 1
fi
set -a
. "$SCRIPT_DIR/.env"
set +a

# JAQ server URL
export JAQ_SERVER_URL="http://localhost:3000"

# Log file
LOG_FILE="/home/ubuntu/new_toasty/toasty/webapp/api.log"

# Clear old log
> "$LOG_FILE"

# Start API server
exec /home/linuxbrew/.linuxbrew/opt/python@3.14/bin/python3.14 -c "
import api
api.app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False, threaded=True)
" >> "$LOG_FILE" 2>&1
