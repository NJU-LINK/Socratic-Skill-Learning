#!/bin/bash
set -euo pipefail

cd /app

python -m pip install grpcio==1.73.0 grpcio-tools==1.73.0

cat > /app/kv-store.proto <<'EOF'
syntax = "proto3";

service KVStore {
    rpc BatchSet (BatchSetRequest) returns (BatchSetResponse) {}
    rpc BatchGet (BatchGetRequest) returns (BatchGetResponse) {}
}

message BatchEntry {
    string key = 1;
    int32 value = 2;
}

message BatchSetRequest {
    repeated BatchEntry entries = 1;
}

message BatchSetResponse {
    int32 written_count = 1;
    repeated BatchEntry entries = 2;
}

message BatchGetRequest {
    repeated string keys = 1;
}

message BatchGetResponse {
    repeated BatchEntry entries = 1;
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

    def BatchSet(self, request, context):
        response_entries = []
        for entry in request.entries:
            self.kv_dict[entry.key] = entry.value
            response_entries.append(
                kv_store_pb2.BatchEntry(key=entry.key, value=self.kv_dict[entry.key])
            )

        return kv_store_pb2.BatchSetResponse(
            written_count=len(request.entries),
            entries=response_entries,
        )

    def BatchGet(self, request, context):
        return kv_store_pb2.BatchGetResponse(
            entries=[
                kv_store_pb2.BatchEntry(key=key, value=self.kv_dict.get(key, 0))
                for key in request.keys
            ]
        )


def serve() -> None:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    kv_store_pb2_grpc.add_KVStoreServicer_to_server(Server(), server)
    server.add_insecure_port("[::]:5328")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
EOF

python /app/server.py >/tmp/kv-store-server.log 2>&1 &
