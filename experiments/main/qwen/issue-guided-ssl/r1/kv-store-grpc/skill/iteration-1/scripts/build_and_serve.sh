#!/usr/bin/env bash
# build_and_serve.sh — Master script for gRPC stateful service deployment
#
# Usage: This script is a template. The calling agent must:
#   1. Provide the .proto content (via heredoc or parameter)
#   2. Provide the server.py implementation
#   3. Specify the port number
#
# This script handles: dependency installation, proto generation, server launch, readiness check.
#
# Example invocation pattern (agent fills in PROTO_CONTENT, SERVER_CONTENT, PORT):
#
#   PROTO_CONTENT="..." SERVER_CONTENT="..." PORT=5328 bash scripts/build_and_serve.sh

set -euo pipefail

# --- Configuration (override via environment) ---
PORT="${PORT:-5328}"
PROTO_FILE="${PROTO_FILE:-/app/service.proto}"
SERVER_FILE="${SERVER_FILE:-/app/server.py}"
GRPCIO_VERSION="${GRPCIO_VERSION:-1.73.0}"
GRPCIO_TOOLS_VERSION="${GRPCIO_TOOLS_VERSION:-1.73.0}"

echo "=== Step 1: Install dependencies ==="
pip install "grpcio==${GRPCIO_VERSION}" "grpcio-tools==${GRPCIO_TOOLS_VERSION}" 2>&1 | tail -3

echo "=== Step 2: Verify proto file exists ==="
if [ ! -f "$PROTO_FILE" ]; then
    echo "ERROR: Proto file not found at $PROTO_FILE"
    echo "The agent must write the proto file before running this script."
    exit 1
fi
echo "Proto file: $PROTO_FILE"

echo "=== Step 3: Generate Python bindings ==="
cd /app
python -m grpc_tools.protoc \
    -I/app \
    --python_out=/app \
    --grpc_python_out=/app \
    "$PROTO_FILE"

# List generated files
echo "Generated files:"
ls -la /app/*_pb2*.py

echo "=== Step 4: Verify server file exists ==="
if [ ! -f "$SERVER_FILE" ]; then
    echo "ERROR: Server file not found at $SERVER_FILE"
    echo "The agent must write the server implementation before running this script."
    exit 1
fi

echo "=== Step 5: Kill any existing server on port $PORT ==="
# Find and kill any process using the port (if possible)
kill $(lsof -t -i:$PORT 2>/dev/null) 2>/dev/null || true
sleep 1

echo "=== Step 6: Start server ==="
cd /app
python "$SERVER_FILE" &
SERVER_PID=$!
echo "Server started with PID $SERVER_PID"

echo "=== Step 7: Wait for readiness ==="
sleep 2

# Verify server is still running
if kill -0 $SERVER_PID 2>/dev/null; then
    echo "Server is running (PID $SERVER_PID)"
else
    echo "ERROR: Server process died"
    exit 1
fi

echo "=== Deployment complete ==="
echo "gRPC server listening on port $PORT"
echo "Server PID: $SERVER_PID"
