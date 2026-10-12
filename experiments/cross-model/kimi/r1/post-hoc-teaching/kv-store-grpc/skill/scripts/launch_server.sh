#!/bin/bash
# Launch gRPC server detached with pidfile and logging
#
# Usage: ./launch_server.sh /app/server.py
#
# IMPORTANT: This script assumes the server writes its own pidfile AFTER bind.
# The server must call: pathlib.Path('/tmp/server.pid').write_text(f'{os.getpid()}\n')
# Shell $! is unreliable (may capture subshell, not python process).

SERVER_SCRIPT="${1:-/app/server.py}"
LOG_FILE="/app/server.log"
PID_FILE="/tmp/server.pid"
PORT="${2:-5328}"

# Function: poll for port to be free
wait_for_port_free() {
    local port=$1
    local hex_port=$(printf '%04X' $port)
    
    for i in $(seq 1 50); do
        if ! grep -qiE "[0-9A-F]{8}:${hex_port} .* 0A" /proc/net/tcp /proc/net/tcp6 2>/dev/null; then
            return 0
        fi
        sleep 0.2
    done
    return 1
}

# Function: find and kill process holding port
kill_port_owner() {
    local port=$1
    local hex_port=$(printf '%04X' $port)
    
    # Find inode from listening socket
    local inode=$(awk -v h=":${hex_port}" '$4=="0A" && $2 ~ h"$" {print $10; exit}' /proc/net/tcp /proc/net/tcp6 2>/dev/null)
    if [ -n "$inode" ]; then
        # Find PID from /proc/*/fd
        for p in /proc/[0-9]*/fd; do
            if ls -l "$p" 2>/dev/null | grep -q "socket:\[${inode}\]"; then
                local real_pid="${p%/fd}"
                echo "Found port holder: $real_pid"
                kill -9 "$real_pid" 2>/dev/null
                return 0
            fi
        done
    fi
    return 1
}

# Step 1: Kill by pidfile if exists
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null)
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Killing server from pidfile (PID $OLD_PID)"
        kill "$OLD_PID"
    fi
fi

# Step 2: Wait for port to be free
if ! wait_for_port_free "$PORT"; then
    echo "Port $PORT still in use, attempting to find owner..."
    if kill_port_owner "$PORT"; then
        sleep 0.5
    else
        echo "WARNING: Could not find port owner, server may fail to bind"
    fi
fi

# Step 3: Launch server
# IMPORTANT: cd first, then run nohup - avoid subshell issues with &&
cd /app
nohup python3 "$SERVER_SCRIPT" > "$LOG_FILE" 2>&1 &

# Wait for server to write pidfile and start
sleep 1

# Step 4: Verify startup via log (not PID - server writes its own pidfile)
if ! grep -q "Server started on port" "$LOG_FILE" 2>/dev/null; then
    echo "ERROR: Server failed to start. Check $LOG_FILE:"
    tail "$LOG_FILE"
    exit 1
fi

# Get actual PID from server-written pidfile
if [ -f "$PID_FILE" ]; then
    ACTUAL_PID=$(cat "$PID_FILE")
    echo "Server started with PID $ACTUAL_PID (self-reported)"
else
    echo "WARNING: Server started but pidfile not found"
fi

echo "Logging to: $LOG_FILE"
echo "Kill with: kill \$(cat $PID_FILE)"
