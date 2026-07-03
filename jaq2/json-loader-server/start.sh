#!/bin/bash

# JAQ JSON Loader Server Startup Script
# This script ensures a clean restart of the server

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_BINARY="$SCRIPT_DIR/../target/release/json-loader-server"
PID_FILE="$SCRIPT_DIR/server.pid"
LOG_FILE="$SCRIPT_DIR/server.log"
PORT=3001

echo "=== JAQ JSON Loader Server Manager ==="

# Function to check if server is running
check_server() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            return 0  # Running
        fi
    fi
    return 1  # Not running
}

# Function to kill existing server processes
kill_existing() {
    echo "Checking for existing server processes..."
    
    # Kill by PID file if exists
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "Stopping server process (PID: $PID)..."
            kill -TERM "$PID" 2>/dev/null
            sleep 2
            # Force kill if still running
            if ps -p "$PID" > /dev/null 2>&1; then
                echo "Force killing process..."
                kill -9 "$PID" 2>/dev/null
            fi
        fi
        rm -f "$PID_FILE"
    fi
    
    # Free up this instance's configured port only
    echo "Checking for processes using port $PORT..."
    PORT_PIDS=$(lsof -t -i:$PORT 2>/dev/null || fuser -n tcp $PORT 2>/dev/null)
    if [ -n "$PORT_PIDS" ]; then
        echo "Killing processes using port $PORT: $PORT_PIDS"
        echo "$PORT_PIDS" | xargs kill -TERM 2>/dev/null
        sleep 2
        STILL_RUNNING=$(lsof -t -i:$PORT 2>/dev/null || fuser -n tcp $PORT 2>/dev/null)
        if [ -n "$STILL_RUNNING" ]; then
            echo "Force killing remaining processes on port $PORT: $STILL_RUNNING"
            echo "$STILL_RUNNING" | xargs kill -9 2>/dev/null
        fi
        sleep 1
    fi
    
    echo "Cleanup complete."
}

# Function to start server
start_server() {
    echo "Starting server..."
    
    # Check if binary exists
    if [ ! -f "$SERVER_BINARY" ]; then
        echo "Error: Server binary not found at $SERVER_BINARY"
        echo "Building..."
        cd "$SCRIPT_DIR/.." && cargo build --release -p json-loader-server
        if [ $? -ne 0 ]; then
            echo "Build failed!"
            exit 1
        fi
    fi
    
    # Start server
    cd "$SCRIPT_DIR"
    nohup "$SERVER_BINARY" > "$LOG_FILE" 2>&1 &
    SERVER_PID=$!
    echo $SERVER_PID > "$PID_FILE"
    
    echo "Server started with PID: $SERVER_PID"
    
    # Wait for server to be ready
    echo "Waiting for server to be ready..."
    for i in {1..10}; do
        sleep 1
        if curl -s http://localhost:$PORT/stats > /dev/null 2>&1; then
            echo "Server is ready!"
            echo ""
            echo "Server stats:"
            curl -s http://localhost:$PORT/stats | python3 -m json.tool 2>/dev/null || curl -s http://localhost:$PORT/stats
            echo ""
            echo "Server URL: http://localhost:$PORT"
            return 0
        fi
        echo "  Attempt $i/10..."
    done
    
    echo "Warning: Server may not have started properly. Check logs: $LOG_FILE"
    return 1
}

# Function to show status
show_status() {
    if check_server; then
        PID=$(cat "$PID_FILE")
        echo "Server is running (PID: $PID)"
        echo ""
        echo "Current stats:"
        curl -s http://localhost:$PORT/stats | python3 -m json.tool 2>/dev/null || curl -s http://localhost:$PORT/stats
    else
        echo "Server is not running"
    fi
}

# Function to stop server
stop_server() {
    kill_existing
    echo "Server stopped"
}

# Main logic
case "${1:-restart}" in
    start)
        if check_server; then
            echo "Server is already running"
            show_status
        else
            start_server
        fi
        ;;
    stop)
        stop_server
        ;;
    restart)
        kill_existing
        sleep 1
        start_server
        ;;
    status)
        show_status
        ;;
    logs)
        if [ -f "$LOG_FILE" ]; then
            tail -f "$LOG_FILE"
        else
            echo "No log file found"
        fi
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        echo ""
        echo "Commands:"
        echo "  start    - Start the server (if not running)"
        echo "  stop     - Stop the server"
        echo "  restart  - Restart the server (default)"
        echo "  status   - Show server status and stats"
        echo "  logs     - Follow server logs"
        exit 1
        ;;
esac
