#!/bin/bash
set -euo pipefail

cd /app

pip install grpcio==1.73.0 grpcio-tools==1.73.0

cat <<'EOF' > /app/kv-store.proto
syntax = "proto3";

service KVStore {
  rpc UpsertEntry(UpsertEntryRequest) returns (UpsertEntryResponse) {}
  rpc GetBucket(GetBucketRequest) returns (GetBucketResponse) {}
  rpc DeleteEntry(DeleteEntryRequest) returns (DeleteEntryResponse) {}
}

message Entry {
  string bucket = 1;
  string key = 2;
  int32 value = 3;
}

message UpsertEntryRequest {
  Entry entry = 1;
}

message UpsertEntryResponse {
  Entry entry = 1;
}

message GetBucketRequest {
  string bucket = 1;
}

message GetBucketResponse {
  repeated Entry entries = 1;
}

message DeleteEntryRequest {
  string bucket = 1;
  string key = 2;
}

message DeleteEntryResponse {
  bool deleted = 1;
}
EOF

python -m grpc_tools.protoc -I/app --python_out=/app --grpc_python_out=/app /app/kv-store.proto

cat <<'EOF' > /app/server.py
from concurrent import futures

import grpc

import kv_store_pb2
import kv_store_pb2_grpc


class Server(kv_store_pb2_grpc.KVStoreServicer):
    def __init__(self) -> None:
        self._buckets: dict[str, dict[str, int]] = {}

    def UpsertEntry(self, request, context):
        entry = request.entry
        bucket = self._buckets.setdefault(entry.bucket, {})
        bucket[entry.key] = entry.value
        return kv_store_pb2.UpsertEntryResponse(
            entry=kv_store_pb2.Entry(
                bucket=entry.bucket,
                key=entry.key,
                value=entry.value,
            )
        )

    def GetBucket(self, request, context):
        bucket = self._buckets.get(request.bucket, {})
        entries = [
            kv_store_pb2.Entry(bucket=request.bucket, key=key, value=bucket[key])
            for key in sorted(bucket)
        ]
        return kv_store_pb2.GetBucketResponse(entries=entries)

    def DeleteEntry(self, request, context):
        bucket = self._buckets.get(request.bucket)
        deleted = bucket is not None and request.key in bucket
        if deleted:
            del bucket[request.key]
            if not bucket:
                del self._buckets[request.bucket]
        return kv_store_pb2.DeleteEntryResponse(deleted=deleted)


def serve() -> None:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    kv_store_pb2_grpc.add_KVStoreServicer_to_server(Server(), server)
    server.add_insecure_port("[::]:5328")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
EOF

chmod +x /app/server.py
python /app/server.py >/tmp/kv-store-server.log 2>&1 &
