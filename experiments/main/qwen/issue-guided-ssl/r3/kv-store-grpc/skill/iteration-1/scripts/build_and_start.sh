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
# Kill any existing server on the same port
if command -v fuser &>/dev/null; then
    fuser -k "${PORT}/tcp" 2>/dev/null || true
fi

# Start server in background
python server.py &
SERVER_PID=$!
echo "Server started with PID $SERVER_PID on port $PORT"

# Wait for readiness
echo "Waiting for server readiness..."
for i in $(seq 1 20); do
    if python -c "
import grpc
channel = grpc.insecure_channel('localhost:${PORT}')
try:
    grpc.channel_ready_future(channel).result(timeout=1)
    print('Server is ready')
    exit(0)
except:
    exit(1)
" 2>/dev/null; then
        break
    fi
    sleep 0.5
done

echo "=== Build and start complete ==="
