#!/bin/bash
set -euo pipefail

cd /app

python3 -m pip install grpcio==1.73.0 grpcio-tools==1.73.0

cat > /app/kv-store.proto <<'EOF'
syntax = "proto3";

service KVStore {
    rpc GetVal (GetValRequest) returns (GetValResponse) {}
    rpc SetVal (SetValRequest) returns (SetValResponse) {}
    rpc DeleteVal (DeleteValRequest) returns (DeleteValResponse) {}
    rpc ResetNamespace (ResetNamespaceRequest) returns (ResetNamespaceResponse) {}
}

message KeyRef {
    string namespace = 1;
    string key = 2;
}

message GetValRequest {
    KeyRef ref = 1;
}

message GetValResponse {
    int32 val = 1;
}

message SetValRequest {
    KeyRef ref = 1;
    int32 value = 2;
}

message SetValResponse {
    int32 val = 1;
}

message DeleteValRequest {
    KeyRef ref = 1;
}

message DeleteValResponse {
    int32 val = 1;
}

message ResetNamespaceRequest {
    string namespace = 1;
}

message ResetNamespaceResponse {
    int32 removed = 1;
}
EOF

python3 -m grpc_tools.protoc -I/app --python_out=/app --grpc_python_out=/app /app/kv-store.proto

cat > /app/server.py <<'EOF'
from concurrent import futures
import threading

import grpc

import kv_store_pb2
import kv_store_pb2_grpc


class Server(kv_store_pb2_grpc.KVStoreServicer):
    def __init__(self) -> None:
        self._namespaces: dict[str, dict[str, int]] = {}
        self._lock = threading.Lock()

    def GetVal(self, request, context):
        with self._lock:
            value = self._namespaces.get(request.ref.namespace, {}).get(request.ref.key, 0)
        return kv_store_pb2.GetValResponse(val=value)

    def SetVal(self, request, context):
        with self._lock:
            namespace = self._namespaces.setdefault(request.ref.namespace, {})
            namespace[request.ref.key] = request.value
        return kv_store_pb2.SetValResponse(val=request.value)

    def DeleteVal(self, request, context):
        with self._lock:
            namespace = self._namespaces.get(request.ref.namespace)
            value = 0
            if namespace is not None:
                value = namespace.pop(request.ref.key, 0)
                if not namespace:
                    self._namespaces.pop(request.ref.namespace, None)
        return kv_store_pb2.DeleteValResponse(val=value)

    def ResetNamespace(self, request, context):
        with self._lock:
            removed = len(self._namespaces.pop(request.namespace, {}))
        return kv_store_pb2.ResetNamespaceResponse(removed=removed)


def serve() -> None:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    kv_store_pb2_grpc.add_KVStoreServicer_to_server(Server(), server)
    server.add_insecure_port("[::]:5328")
    server.start()
    server.wait_for_termination()


if __name__ == '__main__':
    serve()
EOF

pkill -f "/app/server.py" 2>/dev/null || true
nohup python3 /app/server.py >/tmp/kv-store-grpc.log 2>&1 &
