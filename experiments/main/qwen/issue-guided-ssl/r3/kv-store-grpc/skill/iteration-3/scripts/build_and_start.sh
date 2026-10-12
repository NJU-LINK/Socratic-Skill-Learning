#!/bin/bash
# Build and start a gRPC Python server.
#
# Usage: build_and_start.sh <proto_file> [port]
#
# Steps:
# 1. Install grpcio and grpcio-tools if not present
# 2. Generate _pb2.py and _pb2_grpc.py from the proto file
# 3. Start the server in the background
# 4. Wait for readiness
#
# The proto file name determines the generated module names:
#   kv-store.proto -> kv_store_pb2.py, kv_store_pb2_grpc.py
# (hyphens become underscores)

set -e

PROTO_FILE="${1:?Usage: build_and_start.sh <proto_file> [port]}"
PORT="${2:-5328}"
WORK_DIR="$(dirname "$PROTO_FILE")"
PROTO_BASENAME="$(basename "$PROTO_FILE")"

echo "=== Phase 1: Install dependencies ==="
pip install grpcio==1.73.0 grpcio-tools==1.73.0 2>/dev/null || \
pip install grpcio grpcio-tools 2>/dev/null || \
echo "WARNING: Could not install grpcio packages"

echo "=== Phase 2: Generate Python code from proto ==="
cd "$WORK_DIR"
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. "$PROTO_BASENAME"
echo "Generated Python bindings from $PROTO_BASENAME"

echo "=== Phase 3: Start server ==="
# Kill any existing server on the same port (portable method)
python3 -c "
import socket, signal, os, subprocess
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
result = s.connect_ex(('localhost', ${PORT}))
s.close()
if result == 0:
    try:
        result = subprocess.run(['lsof', '-t', '-i:${PORT}'], capture_output=True, text=True)
        if result.stdout.strip():
            for pid in result.stdout.strip().split('\n'):
                os.kill(int(pid), signal.SIGTERM)
            import time; time.sleep(1)
    except:
        pass
" 2>/dev/null || true

# Start server with nohup to ensure it persists across shell sessions
nohup python server.py > /tmp/server.log 2>&1 &
SERVER_PID=$!
echo "Server started with PID $SERVER_PID on port $PORT"

# Wait for readiness
echo "Waiting for server readiness..."
READY=0
for i in $(seq 1 20); do
    if python3 -c "
import grpc, sys
channel = grpc.insecure_channel('localhost:${PORT}')
try:
    grpc.channel_ready_future(channel).result(timeout=1)
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
        echo "Server is ready"
        READY=1
        break
    fi
    sleep 0.5
done

if [ "$READY" -eq 0 ]; then
    echo "ERROR: Server failed to start"
    cat /tmp/server.log
    exit 1
fi

echo "=== Build and start complete ==="
