#!/bin/bash

set -euo pipefail

python -m pip install --break-system-packages grpcio==1.73.0 grpcio-tools==1.73.0

cat <<'PROTO' > /app/profile-records.proto
syntax = "proto3";

service ProfileStore {
  rpc UpsertProfile(UpsertProfileRequest) returns (UpsertProfileResponse);
  rpc GetProfile(GetProfileRequest) returns (GetProfileResponse);
  rpc ResetProfile(ResetProfileRequest) returns (ResetProfileResponse);
}

message Profile {
  int32 age = 1;
  repeated int32 scores = 2;
}

message UpsertProfileRequest {
  string profile_id = 1;
  Profile profile = 2;
}

message UpsertProfileResponse {
  Profile profile = 1;
}

message GetProfileRequest {
  string profile_id = 1;
}

message GetProfileResponse {
  Profile profile = 1;
}

message ResetProfileRequest {
  string profile_id = 1;
}

message ResetProfileResponse {
  Profile profile = 1;
}
PROTO

python -m grpc_tools.protoc -I/app --python_out=/app --grpc_python_out=/app /app/profile-records.proto

cat <<'PY' > /app/server.py
from concurrent import futures
import signal
import threading

import grpc

import profile_records_pb2
import profile_records_pb2_grpc


def _empty_profile():
    return profile_records_pb2.Profile(age=0, scores=[])


class Server(profile_records_pb2_grpc.ProfileStoreServicer):
    def __init__(self):
        self._profiles = {}
        self._lock = threading.Lock()

    def UpsertProfile(self, request, context):
        with self._lock:
            stored = {"age": request.profile.age, "scores": list(request.profile.scores)}
            self._profiles[request.profile_id] = stored
            return profile_records_pb2.UpsertProfileResponse(
                profile=profile_records_pb2.Profile(age=stored["age"], scores=stored["scores"])
            )

    def GetProfile(self, request, context):
        with self._lock:
            stored = self._profiles.get(request.profile_id)
            if stored is None:
                profile = _empty_profile()
            else:
                profile = profile_records_pb2.Profile(age=stored["age"], scores=stored["scores"])
            return profile_records_pb2.GetProfileResponse(profile=profile)

    def ResetProfile(self, request, context):
        with self._lock:
            self._profiles.pop(request.profile_id, None)
            return profile_records_pb2.ResetProfileResponse(profile=_empty_profile())


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    profile_records_pb2_grpc.add_ProfileStoreServicer_to_server(Server(), server)
    server.add_insecure_port("[::]:5328")
    server.start()

    stop_event = threading.Event()

    def handle_signal(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    stop_event.wait()
    server.stop(grace=None).wait()


if __name__ == "__main__":
    serve()
PY

nohup python /app/server.py >/tmp/profile-store-server.log 2>&1 &

python - <<'PY'
import socket
import time

deadline = time.time() + 20
while time.time() < deadline:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        if sock.connect_ex(("127.0.0.1", 5328)) == 0:
            raise SystemExit(0)
    time.sleep(0.2)

raise SystemExit("Timed out waiting for the gRPC server to start on port 5328")
PY
