#!/bin/bash

set -euo pipefail

cd /app

python3 -m pip install --break-system-packages grpcio==1.73.0 grpcio-tools==1.73.0

cat <<'PROTO' > /app/inventory.proto
syntax = "proto3";

service InventoryService {
  rpc StockItem(StockItemRequest) returns (StockItemResponse);
  rpc ReserveItem(ReserveItemRequest) returns (ReserveItemResponse);
  rpc ReleaseItem(ReleaseItemRequest) returns (ReleaseItemResponse);
  rpc GetStock(GetStockRequest) returns (GetStockResponse);
}

message StockItemRequest {
  string item_name = 1;
  int32 quantity = 2;
}

message StockItemResponse {
  bool success = 1;
  int32 remaining_stock = 2;
}

message ReserveItemRequest {
  string item_name = 1;
  int32 quantity = 2;
}

message ReserveItemResponse {
  bool success = 1;
  int32 remaining_stock = 2;
}

message ReleaseItemRequest {
  string item_name = 1;
  int32 quantity = 2;
}

message ReleaseItemResponse {
  bool success = 1;
  int32 remaining_stock = 2;
}

message GetStockRequest {
  string item_name = 1;
}

message GetStockResponse {
  int32 available_stock = 1;
}
PROTO

python3 -m grpc_tools.protoc -I/app --python_out=/app --grpc_python_out=/app /app/inventory.proto

cat <<'PY' > /app/server.py
from concurrent import futures
import signal
import threading
import time

import grpc

import inventory_pb2
import inventory_pb2_grpc


class Server(inventory_pb2_grpc.InventoryServiceServicer):
    def __init__(self):
        self._stock = {}
        self._lock = threading.Lock()

    def StockItem(self, request, context):
        with self._lock:
            updated = self._stock.get(request.item_name, 0) + request.quantity
            self._stock[request.item_name] = updated
            return inventory_pb2.StockItemResponse(success=True, remaining_stock=updated)

    def ReserveItem(self, request, context):
        with self._lock:
            current = self._stock.get(request.item_name, 0)
            if request.quantity <= current:
                current -= request.quantity
                self._stock[request.item_name] = current
                return inventory_pb2.ReserveItemResponse(success=True, remaining_stock=current)
            return inventory_pb2.ReserveItemResponse(success=False, remaining_stock=current)

    def ReleaseItem(self, request, context):
        with self._lock:
            updated = self._stock.get(request.item_name, 0) + request.quantity
            self._stock[request.item_name] = updated
            return inventory_pb2.ReleaseItemResponse(success=True, remaining_stock=updated)

    def GetStock(self, request, context):
        with self._lock:
            return inventory_pb2.GetStockResponse(available_stock=self._stock.get(request.item_name, 0))


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=16))
    inventory_pb2_grpc.add_InventoryServiceServicer_to_server(Server(), server)
    server.add_insecure_port("0.0.0.0:5328")
    server.start()

    stop_event = threading.Event()

    def handle_signal(signum, frame):
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
PY

python3 - <<'PY'
import os
import signal
import socket
import time


def inode_listening_on_port(port: int) -> set[str]:
    target_port = f"{port:04X}"
    inodes = set()
    for proc_net in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(proc_net, "r", encoding="utf-8") as handle:
                next(handle, None)
                for line in handle:
                    parts = line.split()
                    local_address = parts[1]
                    state = parts[3]
                    inode = parts[9]
                    if local_address.endswith(f":{target_port}") and state == "0A":
                        inodes.add(inode)
        except FileNotFoundError:
            continue
    return inodes


def pids_for_socket_inodes(inodes: set[str]) -> set[int]:
    pids = set()
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        fd_dir = os.path.join("/proc", entry, "fd")
        try:
            for fd in os.listdir(fd_dir):
                fd_path = os.path.join(fd_dir, fd)
                try:
                    link = os.readlink(fd_path)
                except OSError:
                    continue
                if link.startswith("socket:[") and link[8:-1] in inodes:
                    pids.add(int(entry))
                    break
        except OSError:
            continue
    return pids


listener_inodes = inode_listening_on_port(5328)
for pid in pids_for_socket_inodes(listener_inodes):
    if pid != os.getpid():
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

deadline = time.time() + 10
while time.time() < deadline:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        if sock.connect_ex(("127.0.0.1", 5328)) != 0:
            break
    time.sleep(0.2)
PY

if [ -f /tmp/inventory-server.pid ] && kill -0 "$(cat /tmp/inventory-server.pid)" 2>/dev/null; then
  kill "$(cat /tmp/inventory-server.pid)" 2>/dev/null || true
  wait "$(cat /tmp/inventory-server.pid)" 2>/dev/null || true
fi

nohup python3 /app/server.py >/tmp/inventory-server.log 2>&1 &
server_pid=$!
printf '%s\n' "$server_pid" > /tmp/inventory-server.pid

python3 - <<'PY'
import socket
import time

deadline = time.time() + 30
while time.time() < deadline:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        if sock.connect_ex(("127.0.0.1", 5328)) == 0:
            raise SystemExit(0)
    time.sleep(0.2)

raise SystemExit("Timed out waiting for the inventory server to start on port 5328")
PY
