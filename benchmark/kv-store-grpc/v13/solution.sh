#!/bin/bash
set -euo pipefail

cd /app

pip install grpcio==1.73.0 grpcio-tools==1.73.0

cat <<'EOF' > /app/kv-store.proto
syntax = "proto3";

service KVStore {
  rpc GetVal(GetValRequest) returns (GetValResponse) {}
  rpc CompareAndSet(CompareAndSetRequest) returns (CompareAndSetResponse) {}
}

enum CompareAndSetStatus {
  COMPARE_AND_SET_STATUS_UNSPECIFIED = 0;
  UPDATED = 1;
  MISMATCH = 2;
  CREATED = 3;
}

message GetValRequest {
  string key = 1;
}

message GetValResponse {
  int32 value = 1;
}

message CompareAndSetRequest {
  string key = 1;
  int32 expected_val = 2;
  int32 new_val = 3;
}

message CompareAndSetResponse {
  CompareAndSetStatus status = 1;
  int32 value = 2;
}
EOF

python -m grpc_tools.protoc -I/app --python_out=/app --grpc_python_out=/app /app/kv-store.proto

cat <<'EOF' > /app/server.py
from concurrent import futures
import threading

import grpc

import kv_store_pb2
import kv_store_pb2_grpc


class Server(kv_store_pb2_grpc.KVStoreServicer):
    def __init__(self) -> None:
        self._store: dict[str, int] = {}
        self._lock = threading.Lock()

    def GetVal(self, request, context):
        with self._lock:
            value = self._store.get(request.key, 0)
        return kv_store_pb2.GetValResponse(value=value)

    def CompareAndSet(self, request, context):
        with self._lock:
            current = self._store.get(request.key)
            if current is None:
                self._store[request.key] = request.new_val
                return kv_store_pb2.CompareAndSetResponse(
                    status=kv_store_pb2.CREATED,
                    value=request.new_val,
                )
            if current == request.expected_val:
                self._store[request.key] = request.new_val
                return kv_store_pb2.CompareAndSetResponse(
                    status=kv_store_pb2.UPDATED,
                    value=request.new_val,
                )
            return kv_store_pb2.CompareAndSetResponse(
                status=kv_store_pb2.MISMATCH,
                value=current,
            )


def serve() -> None:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=16))
    kv_store_pb2_grpc.add_KVStoreServicer_to_server(Server(), server)
    server.add_insecure_port("[::]:5328")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
EOF

python /app/server.py > /tmp/kv-store-grpc.log 2>&1 &
