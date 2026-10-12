#!/usr/bin/env bash
# protoc_gen.sh — generate Python gRPC bindings from a proto file.
# Usage: protoc_gen.sh <proto_file> [out_dir]
#   default out_dir = directory containing the proto file.
#
# Encodes the filename-derivation rule:
#   Python module = proto base name with every non-identifier character
#   replaced by '_', plus _pb2 / _pb2_grpc.
#   e.g. kv-store.proto -> kv_store_pb2.py + kv_store_pb2_grpc.py
set -euo pipefail

proto="${1:?usage: protoc_gen.sh <proto_file> [out_dir]}"
proto_dir="$(cd "$(dirname "$proto")" && pwd)"
proto_base="$(basename "$proto")"
proto_stem="${proto_base%.proto}"
out="${2:-$proto_dir}"

cd "$proto_dir"
python3 -m grpc_tools.protoc -I"$proto_dir" --python_out="$out" --grpc_python_out="$out" "$proto_base"

# Derive and print the generated module names (the family naming rule).
mod="${proto_stem//[^A-Za-z0-9_]/_}"
echo "generated: ${out}/${mod}_pb2.py, ${out}/${mod}_pb2_grpc.py"
echo "servicer base class: check <ServiceName>Servicer in ${mod}_pb2_grpc.py"