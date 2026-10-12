#!/bin/bash
# Generate Python bindings from proto file and verify outputs
# Usage: ./generate.sh <proto_file>

set -e

PROTO_FILE="${1:-kv-store.proto}"

echo "Generating Python bindings from ${PROTO_FILE}..."

python -m grpc_tools.protoc \
    -I. \
    --python_out=. \
    --grpc_python_out=. \
    "${PROTO_FILE}"

echo "Verifying generated files:"
ls -la *_pb2.py *_pb2_grpc.py 2>/dev/null

echo ""
echo "Proto to module mapping (replace dashes with underscores):"
echo "  ${PROTO_FILE} -> ${PROTO_FILE//-/_}_pb2.py"
