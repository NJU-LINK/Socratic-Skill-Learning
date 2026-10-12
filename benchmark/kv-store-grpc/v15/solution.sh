#!/bin/bash
set -euo pipefail

cd /app

PYTHON_BIN="$(command -v python3 || command -v python)"

if command -v uv >/dev/null 2>&1; then
  uv pip install --system grpcio==1.73.0 grpcio-tools==1.73.0
elif "$PYTHON_BIN" -m pip install grpcio==1.73.0 grpcio-tools==1.73.0; then
  :
else
  "$PYTHON_BIN" -m pip install --break-system-packages grpcio==1.73.0 grpcio-tools==1.73.0
fi

cat >/app/kv-store.proto <<'PROTO'
syntax = "proto3";

service KVStore {
  rpc UpsertItem(UpsertItemRequest) returns (UpsertItemResponse) {}
  rpc GetItem(GetItemRequest) returns (GetItemResponse) {}
  rpc ListItems(ListItemsRequest) returns (ListItemsResponse) {}
}

message ItemRecord {
  string key = 1;
  int32 quantity = 2;
  repeated string tags = 3;
}

message UpsertItemRequest {
  ItemRecord item = 1;
}

message UpsertItemResponse {
  ItemRecord item = 1;
}

message GetItemRequest {
  string key = 1;
}

message GetItemResponse {
  ItemRecord item = 1;
}

message ListItemsRequest {}

message ListItemsResponse {
  repeated ItemRecord items = 1;
}
PROTO

"$PYTHON_BIN" -m grpc_tools.protoc -I/app --python_out=/app --grpc_python_out=/app /app/kv-store.proto

cat >/app/server.py <<'PY'
from concurrent import futures
import threading

import grpc

import kv_store_pb2
import kv_store_pb2_grpc


class Server(kv_store_pb2_grpc.KVStoreServicer):
    def __init__(self) -> None:
        self._items: dict[str, dict[str, object]] = {}
        self._lock = threading.Lock()

    def UpsertItem(self, request, context):
        record = kv_store_pb2.ItemRecord(
            key=request.item.key,
            quantity=request.item.quantity,
        )
        record.tags.extend(request.item.tags)

        with self._lock:
            self._items[record.key] = {
                "quantity": record.quantity,
                "tags": list(record.tags),
            }

        return kv_store_pb2.UpsertItemResponse(item=record)

    def GetItem(self, request, context):
        with self._lock:
            stored = self._items.get(request.key)

        if stored is None:
            return kv_store_pb2.GetItemResponse(
                item=kv_store_pb2.ItemRecord(key=request.key, quantity=0)
            )

        record = kv_store_pb2.ItemRecord(
            key=request.key,
            quantity=stored["quantity"],
        )
        record.tags.extend(stored["tags"])
        return kv_store_pb2.GetItemResponse(item=record)

    def ListItems(self, request, context):
        with self._lock:
            snapshot = [
                (key, value["quantity"], list(value["tags"]))
                for key, value in sorted(self._items.items())
            ]

        items = []
        for key, quantity, tags in snapshot:
            record = kv_store_pb2.ItemRecord(key=key, quantity=quantity)
            record.tags.extend(tags)
            items.append(record)

        return kv_store_pb2.ListItemsResponse(items=items)


def serve() -> None:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=16))
    kv_store_pb2_grpc.add_KVStoreServicer_to_server(Server(), server)
    server.add_insecure_port("[::]:5328")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
PY

if [ -f /tmp/kv-store-grpc.pid ]; then
  kill "$(cat /tmp/kv-store-grpc.pid)" 2>/dev/null || true
fi
pkill -f '/app/server.py' 2>/dev/null || true

nohup "$PYTHON_BIN" /app/server.py >/tmp/kv-store-grpc.log 2>&1 &
echo $! >/tmp/kv-store-grpc.pid

"$PYTHON_BIN" - <<'PY'
import socket
import sys
import time

for _ in range(100):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        if sock.connect_ex(("127.0.0.1", 5328)) == 0:
            sys.exit(0)
    time.sleep(0.1)

raise SystemExit("server did not start listening on port 5328")
PY
