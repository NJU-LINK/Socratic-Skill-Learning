#!/bin/bash
set -euo pipefail

cd /app

python3 -m pip install --break-system-packages grpcio==1.73.0 grpcio-tools==1.73.0

cat <<'EOF' > /app/kv-store.proto
syntax = "proto3";

service KVStore {
  rpc InitCounter(InitCounterRequest) returns (InitCounterResponse);
  rpc Increment(IncrementRequest) returns (IncrementResponse);
  rpc GetVal(GetValRequest) returns (GetValResponse);
}

message InitCounterRequest {
  string key = 1;
  int32 value = 2;
}

message InitCounterResponse {
  int32 val = 1;
}

message IncrementRequest {
  string key = 1;
  int32 delta = 2;
}

message IncrementResponse {
  int32 val = 1;
}

message GetValRequest {
  string key = 1;
}

message GetValResponse {
  int32 val = 1;
}
EOF

python3 -m grpc_tools.protoc -I/app --python_out=/app --grpc_python_out=/app /app/kv-store.proto

cat <<'EOF' > /app/server.py
from concurrent import futures
import signal
import threading
import time

import grpc

import kv_store_pb2
import kv_store_pb2_grpc


class Server(kv_store_pb2_grpc.KVStoreServicer):
    def __init__(self) -> None:
        self._values: dict[str, int] = {}
        self._lock = threading.Lock()

    def InitCounter(self, request, context):
        with self._lock:
            self._values[request.key] = request.value
            return kv_store_pb2.InitCounterResponse(val=self._values[request.key])

    def Increment(self, request, context):
        with self._lock:
            current = self._values.get(request.key, 0)
            updated = current + request.delta
            self._values[request.key] = updated
            return kv_store_pb2.IncrementResponse(val=updated)

    def GetVal(self, request, context):
        with self._lock:
            return kv_store_pb2.GetValResponse(val=self._values.get(request.key, 0))


def serve() -> None:
    # Delay startup so clients need a readiness wait before connecting.
    time.sleep(2)

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=32))
    kv_store_pb2_grpc.add_KVStoreServicer_to_server(Server(), server)
    server.add_insecure_port("0.0.0.0:5328")
    server.start()

    stop_event = threading.Event()

    def handle_signal(signum, frame):
        del signum, frame
        stop_event.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    try:
        while not stop_event.is_set():
            time.sleep(0.5)
    finally:
        server.stop(grace=1).wait()


if __name__ == "__main__":
    serve()
EOF

if [ -f /tmp/kv-store-server.pid ] && kill -0 "$(cat /tmp/kv-store-server.pid)" 2>/dev/null; then
  kill "$(cat /tmp/kv-store-server.pid)" 2>/dev/null || true
  wait "$(cat /tmp/kv-store-server.pid)" 2>/dev/null || true
fi

nohup python3 /app/server.py >/tmp/kv-store-server.log 2>&1 &
server_pid=$!
printf '%s\n' "$server_pid" > /tmp/kv-store-server.pid
