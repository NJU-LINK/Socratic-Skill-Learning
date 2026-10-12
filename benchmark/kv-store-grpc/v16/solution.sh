#!/bin/bash
set -euo pipefail

cd /app

python -m pip install grpcio==1.73.0 grpcio-tools==1.73.0

cat > /app/kv-store.proto <<'EOF'
syntax = "proto3";

service KVStore {
    rpc GetVal (GetValRequest) returns (GetValResponse) {}
    rpc SetVal (SetValRequest) returns (SetValResponse) {}
    rpc DeleteVal (DeleteValRequest) returns (DeleteValResponse) {}
}

message GetValRequest {
    string key = 1;
}

message GetValResponse {
    int32 val = 1;
}

message SetValRequest {
    string key = 1;
    int32 value = 2;
}

message SetValResponse {
    int32 val = 1;
}

message DeleteValRequest {
    string key = 1;
}

message DeleteValResponse {
    bool deleted = 1;
}
EOF

python -m grpc_tools.protoc -I/app --python_out=/app --grpc_python_out=/app /app/kv-store.proto

cat > /app/server.py <<'EOF'
from concurrent import futures

import grpc

import kv_store_pb2
import kv_store_pb2_grpc


class Server(kv_store_pb2_grpc.KVStoreServicer):
    def __init__(self) -> None:
        self.kv_dict: dict[str, int] = {}

    def GetVal(self, request, context):
        return kv_store_pb2.GetValResponse(val=self.kv_dict.get(request.key, 0))

    def SetVal(self, request, context):
        self.kv_dict[request.key] = request.value
        return kv_store_pb2.SetValResponse(val=request.value)

    def DeleteVal(self, request, context):
        deleted = request.key in self.kv_dict
        if deleted:
            del self.kv_dict[request.key]
        return kv_store_pb2.DeleteValResponse(deleted=deleted)


def main() -> None:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    kv_store_pb2_grpc.add_KVStoreServicer_to_server(Server(), server)
    server.add_insecure_port("[::]:5328")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    main()
EOF

nohup python /app/server.py >/tmp/kv-store-server.log 2>&1 &
