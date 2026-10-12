#!/bin/bash
set -euo pipefail

cd /app

pip install grpcio==1.73.0 grpcio-tools==1.73.0

cat <<'EOF' > /app/kv-store.proto
syntax = "proto3";

service KVStore {
  rpc SetVal(SetValRequest) returns (SetValResponse);
  rpc GetVal(GetValRequest) returns (GetValResponse);
  rpc DumpState(DumpStateRequest) returns (DumpStateResponse);
}

service Health {
  rpc CheckReady(CheckReadyRequest) returns (CheckReadyResponse);
}

message SetValRequest {
  string key = 1;
  int32 value = 2;
}

message SetValResponse {
  int32 val = 1;
}

message GetValRequest {
  string key = 1;
}

message GetValResponse {
  int32 val = 1;
}

message DumpStateRequest {}

message StateEntry {
  string key = 1;
  int32 value = 2;
}

message DumpStateResponse {
  repeated StateEntry entries = 1;
}

message CheckReadyRequest {}

message CheckReadyResponse {
  bool ready = 1;
}
EOF

python -m grpc_tools.protoc -I/app --python_out=/app --grpc_python_out=/app /app/kv-store.proto

cat <<'EOF' > /app/server.py
from concurrent import futures
import threading
import time

import grpc

import kv_store_pb2
import kv_store_pb2_grpc


READY_DELAY_SECONDS = 3.0


class Server(kv_store_pb2_grpc.KVStoreServicer, kv_store_pb2_grpc.HealthServicer):
    def __init__(self) -> None:
        self._data: dict[str, int] = {}
        self._lock = threading.Lock()
        self._ready_at = time.monotonic() + READY_DELAY_SECONDS

    def SetVal(self, request, context):
        with self._lock:
            self._data[request.key] = request.value
            value = self._data[request.key]
        return kv_store_pb2.SetValResponse(val=value)

    def GetVal(self, request, context):
        with self._lock:
            value = self._data.get(request.key, 0)
        return kv_store_pb2.GetValResponse(val=value)

    def DumpState(self, request, context):
        with self._lock:
            items = sorted(self._data.items())
        return kv_store_pb2.DumpStateResponse(
            entries=[kv_store_pb2.StateEntry(key=key, value=value) for key, value in items]
        )

    def CheckReady(self, request, context):
        return kv_store_pb2.CheckReadyResponse(ready=time.monotonic() >= self._ready_at)


def serve() -> None:
    grpc_server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    service = Server()
    kv_store_pb2_grpc.add_KVStoreServicer_to_server(service, grpc_server)
    kv_store_pb2_grpc.add_HealthServicer_to_server(service, grpc_server)
    grpc_server.add_insecure_port("[::]:5328")
    grpc_server.start()
    grpc_server.wait_for_termination()


if __name__ == "__main__":
    serve()
EOF

nohup python /app/server.py >/tmp/kv-store-grpc.log 2>&1 &
