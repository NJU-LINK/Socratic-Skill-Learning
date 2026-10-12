#!/bin/bash
set -euo pipefail

cd /app

python3 -m pip install --break-system-packages grpcio==1.73.0 grpcio-tools==1.73.0

cat <<'EOF' > /app/kv-store.proto
syntax = "proto3";

service KVStore {
  rpc Put(PutRequest) returns (PutResponse);
  rpc Fetch(FetchRequest) returns (FetchResponse);
  rpc Delete(DeleteRequest) returns (DeleteResponse);
  rpc ListNamespaceTotal(ListNamespaceTotalRequest) returns (ListNamespaceTotalResponse);
}

message PutRequest {
  string namespace = 1;
  string key = 2;
  int32 value = 3;
}

message PutResponse {
  int32 value = 1;
}

message FetchRequest {
  string namespace = 1;
  string key = 2;
}

message FetchResponse {
  int32 value = 1;
}

message DeleteRequest {
  string namespace = 1;
  string key = 2;
}

message DeleteResponse {
  bool success = 1;
  int32 value = 2;
}

message ListNamespaceTotalRequest {
  string namespace = 1;
}

message ListNamespaceTotalResponse {
  int32 total = 1;
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
    def __init__(self):
        self._store = {}
        self._lock = threading.Lock()

    def Put(self, request, context):
        with self._lock:
            namespace_store = self._store.setdefault(request.namespace, {})
            namespace_store[request.key] = request.value
            return kv_store_pb2.PutResponse(value=request.value)

    def Fetch(self, request, context):
        with self._lock:
            value = self._store.get(request.namespace, {}).get(request.key, 0)
            return kv_store_pb2.FetchResponse(value=value)

    def Delete(self, request, context):
        with self._lock:
            namespace_store = self._store.get(request.namespace)
            if not namespace_store or request.key not in namespace_store:
                return kv_store_pb2.DeleteResponse(success=False, value=0)

            value = namespace_store.pop(request.key)
            if not namespace_store:
                self._store.pop(request.namespace, None)
            return kv_store_pb2.DeleteResponse(success=True, value=value)

    def ListNamespaceTotal(self, request, context):
        with self._lock:
            total = sum(self._store.get(request.namespace, {}).values())
            return kv_store_pb2.ListNamespaceTotalResponse(total=total)


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    kv_store_pb2_grpc.add_KVStoreServicer_to_server(Server(), server)
    server.add_insecure_port("0.0.0.0:5328")
    server.start()

    stop_event = threading.Event()

    def _handle_signal(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

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

python3 - <<'PY'
import socket
import time
import sys

deadline = time.time() + 30
while time.time() < deadline:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        if sock.connect_ex(("127.0.0.1", 5328)) == 0:
            sys.exit(0)
    time.sleep(0.2)

raise SystemExit("server did not start listening on port 5328")
PY
