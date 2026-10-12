#!/bin/bash
set -euo pipefail

cd /app

python3 -m pip install --break-system-packages grpcio==1.73.0 grpcio-tools==1.73.0

cat > /app/kv-store.proto <<'EOF'
syntax = "proto3";

service KVStore {
  rpc BatchSet (BatchSetRequest) returns (BatchSetResponse);
  rpc SumVals (SumValsRequest) returns (SumValsResponse);
}

message KVEntry {
  string key = 1;
  int32 value = 2;
}

message BatchSetRequest {
  repeated KVEntry entries = 1;
}

message BatchSetResponse {
  int32 applied_count = 1;
}

message SumValsRequest {
  repeated string keys = 1;
}

message SumValsResponse {
  int32 total = 1;
  int32 found_count = 2;
}
EOF

python3 -m grpc_tools.protoc -I/app --python_out=/app --grpc_python_out=/app /app/kv-store.proto

cat > /app/server.py <<'EOF'
from concurrent import futures
from threading import Lock

import grpc

import kv_store_pb2
import kv_store_pb2_grpc


class Server(kv_store_pb2_grpc.KVStoreServicer):
    def __init__(self) -> None:
        self._values: dict[str, int] = {}
        self._lock = Lock()

    def BatchSet(self, request, context):
        with self._lock:
            for entry in request.entries:
                self._values[entry.key] = entry.value
        return kv_store_pb2.BatchSetResponse(applied_count=len(request.entries))

    def SumVals(self, request, context):
        total = 0
        found_count = 0
        with self._lock:
            for key in request.keys:
                if key in self._values:
                    total += self._values[key]
                    found_count += 1
        return kv_store_pb2.SumValsResponse(total=total, found_count=found_count)


def serve() -> None:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    kv_store_pb2_grpc.add_KVStoreServicer_to_server(Server(), server)
    server.add_insecure_port("0.0.0.0:5328")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
EOF

pkill -f '/app/server.py' >/dev/null 2>&1 || true
nohup python3 /app/server.py >/tmp/kv-store-server.log 2>&1 &

python3 - <<'EOF'
import socket
import time

deadline = time.time() + 15
while time.time() < deadline:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        if sock.connect_ex(("127.0.0.1", 5328)) == 0:
            raise SystemExit(0)
    time.sleep(0.2)

raise SystemExit("server did not start listening on port 5328")
EOF
