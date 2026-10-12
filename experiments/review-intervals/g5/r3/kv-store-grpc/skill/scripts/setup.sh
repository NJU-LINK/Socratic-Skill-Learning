#!/bin/bash
# Setup script for kv-store-grpc service
# This script installs dependencies, generates protobuf bindings, and starts the server.
#
# Usage:
#   ./setup.sh [proto_file] [port]
#
# Arguments:
#   proto_file - Path to .proto file (default: kv-store.proto in current directory)
#   port - Port to listen on (default: 5328)
#
# This script assumes:
# - Python 3.8+ is available
# - The proto file and server.py are in the current directory
# - You want to run the server in the background

set -e

PROTO_FILE="${1:-kv-store.proto}"
PORT="${2:-5328}"
WORK_DIR="${3:-.}"  # Directory containing proto file and server.py (default: current dir)

echo "=== kv-store-grpc setup ==="
echo "Proto file: $PROTO_FILE"
echo "Port: $PORT"
echo "Working directory: $WORK_DIR"

# Step 1: Install dependencies
echo ""
echo "Step 1: Installing gRPC dependencies..."
pip install grpcio==1.73.0 grpcio-tools==1.73.0 > /dev/null 2>&1
echo "✓ Dependencies installed"

# Step 2: Generate protobuf bindings
echo ""
echo "Step 2: Generating Python bindings..."
cd "$WORK_DIR"
python -m grpc_tools.protoc \
  -I. \
  --python_out=. \
  --grpc_python_out=. \
  "$PROTO_FILE"
echo "✓ Bindings generated"

# Step 3: Verify generated files exist
BASE_NAME="${PROTO_FILE%.proto}"
BASE_NAME="${BASE_NAME//-/_}"   # hyphens → underscores (protoc converts hyphens to underscores)
PB2_FILE="${BASE_NAME}_pb2.py"
PB2_GRPC_FILE="${BASE_NAME}_pb2_grpc.py"

if [ ! -f "$PB2_FILE" ] || [ ! -f "$PB2_GRPC_FILE" ]; then
  echo "✗ Error: Generated files not found"
  exit 1
fi
echo "✓ Generated files verified: $PB2_FILE, $PB2_GRPC_FILE"

# Step 4: Update server.py with the correct port (if needed)
if [ "$PORT" != "5328" ]; then
  echo ""
  echo "Step 3: Updating server port to $PORT..."
  sed -i "s/\[::\]:5328/[::]:$PORT/g" server.py
  echo "✓ Port updated"
fi

# Step 5: Start the server
echo ""
echo "Step 4: Starting gRPC server..."

# Stop any existing server on this port (portable approach)
EXISTING_PID=$(ps aux | grep "[p]ython server.py" | awk '{print $2}' | head -1)
if [ -n "$EXISTING_PID" ]; then
  echo "Server already running (PID: $EXISTING_PID), stopping..."
  kill "$EXISTING_PID" 2>/dev/null || true
  sleep 1
fi

cd "$WORK_DIR"
python server.py &
SERVER_PID=$!
sleep 2

# Verify server is running
if ! kill -0 $SERVER_PID 2>/dev/null; then
  echo "✗ Error: Server failed to start"
  exit 1
fi

echo "✓ Server started (PID: $SERVER_PID)"
echo ""
echo "=== Setup complete ==="
echo "Server is listening on port $PORT"
echo "To stop the server: kill $SERVER_PID"
