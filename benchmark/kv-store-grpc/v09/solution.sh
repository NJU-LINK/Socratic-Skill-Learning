#!/bin/bash
set -euo pipefail

cd /app

PYTHON_BIN="python"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    PYTHON_BIN="python3"
fi

"$PYTHON_BIN" -m pip install --break-system-packages grpcio==1.73.0 grpcio-tools==1.73.0

cat > /app/kv-store.proto <<'EOF'
syntax = "proto3";

service KVStore {
  rpc SetVal (SetValRequest) returns (SetValResponse);
  rpc GetVal (GetValRequest) returns (GetValResponse);
  rpc ResetSession (ResetSessionRequest) returns (ResetSessionResponse);
}

message SetValRequest {
  string session_id = 1;
  string key = 2;
  int32 value = 3;
}

message SetValResponse {
  int32 val = 1;
  string session_id = 2;
  int64 expiration_time = 3;
}

message GetValRequest {
  string session_id = 1;
  string key = 2;
}

message GetValResponse {
  int32 val = 1;
  string session_id = 2;
  bool exists = 3;
}

message ResetSessionRequest {
  string session_id = 1;
}

message ResetSessionResponse {
  string session_id = 1;
  int32 removed_keys = 2;
}
EOF

"$PYTHON_BIN" -m grpc_tools.protoc -I/app --python_out=/app --grpc_python_out=/app kv-store.proto

cat > /app/server.py <<'EOF'
from concurrent import futures
import threading
import time

import grpc

import kv_store_pb2
import kv_store_pb2_grpc


SESSION_TTL_SECONDS = 3.0


class Server(kv_store_pb2_grpc.KVStoreServicer):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, dict[str, object]] = {}

    def _purge_if_expired(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            return
        if time.monotonic() >= session["expires_at"]:
            self._sessions.pop(session_id, None)

    def SetVal(self, request, context):
        del context
        with self._lock:
            self._purge_if_expired(request.session_id)
            session = self._sessions.get(request.session_id)
            if session is None:
                session = {"values": {}, "expires_at": 0.0}
                self._sessions[request.session_id] = session

            values = session["values"]
            values[request.key] = request.value
            session["expires_at"] = time.monotonic() + SESSION_TTL_SECONDS
            expiration_time = int(time.time() + SESSION_TTL_SECONDS)

        return kv_store_pb2.SetValResponse(
            val=request.value,
            session_id=request.session_id,
            expiration_time=expiration_time,
        )

    def GetVal(self, request, context):
        del context
        with self._lock:
            self._purge_if_expired(request.session_id)
            session = self._sessions.get(request.session_id)
            if session is None:
                return kv_store_pb2.GetValResponse(
                    val=0,
                    session_id=request.session_id,
                    exists=False,
                )

            values = session["values"]
            if request.key not in values:
                return kv_store_pb2.GetValResponse(
                    val=0,
                    session_id=request.session_id,
                    exists=False,
                )

            return kv_store_pb2.GetValResponse(
                val=values[request.key],
                session_id=request.session_id,
                exists=True,
            )

    def ResetSession(self, request, context):
        del context
        with self._lock:
            self._purge_if_expired(request.session_id)
            session = self._sessions.pop(request.session_id, None)
            removed_keys = 0 if session is None else len(session["values"])

        return kv_store_pb2.ResetSessionResponse(
            session_id=request.session_id,
            removed_keys=removed_keys,
        )


def serve() -> None:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    kv_store_pb2_grpc.add_KVStoreServicer_to_server(Server(), server)
    server.add_insecure_port("[::]:5328")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
EOF

pkill -f "/app/server.py" || true
nohup "$PYTHON_BIN" /app/server.py >/tmp/kv-store-server.log 2>&1 &

ready=0
for _ in $(seq 1 50); do
    if "$PYTHON_BIN" - <<'EOF'
import socket
import sys

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(0.2)
try:
    sock.connect(("127.0.0.1", 5328))
except OSError:
    sys.exit(1)
else:
    sys.exit(0)
finally:
    sock.close()
EOF
    then
        ready=1
        break
    fi
    sleep 0.1
done

if [ "$ready" -ne 1 ]; then
    echo "gRPC server did not start on port 5328" >&2
    exit 1
fi
