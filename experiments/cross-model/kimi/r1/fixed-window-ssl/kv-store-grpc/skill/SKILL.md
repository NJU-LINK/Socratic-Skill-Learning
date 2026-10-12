---
name: kv-store-grpc
description: Build a stateful Python gRPC key-value store server from a proto spec, handling concurrent requests with proper state persistence and namespace isolation.
---

# KV Store gRPC Skill

Build a stateful Python gRPC server implementing a key-value store API defined in a `.proto` file. The server must handle concurrent requests, persist state across multiple client channels, and enforce namespace isolation.

## Task Family Definition

**Invariants** (across all variants):
- Python gRPC server with generated protobuf bindings
- Stateful in-memory storage persisting across RPC calls and client channels
- Thread-safe concurrent request handling
- Server must remain running after launch command completes

**Variation axes** (per-instance):
- **rpc_api_structure**: Number of RPC methods, message field types (strings, ints, enums, nested/repeated fields)
- **stateful_service_semantics**: Read/write operations (CRUD, conditional updates, aggregates), namespace isolation rules, default values for missing keys
- **runtime_interaction_requirements**: Port binding, server lifecycle management, readiness verification

## Implementation Pipeline

### 1. Install Dependencies

```bash
pip3 install grpcio==1.73.0 grpcio-tools==1.73.0
```

### 2. Create Proto File

Write the `.proto` file with service definition and messages per the task spec:

```protobuf
syntax = "proto3";

package kvstore;  # or task-specific package

service KVStore {
  rpc Put(PutRequest) returns (PutResponse);
  rpc Fetch(FetchRequest) returns (FetchResponse);
  // ... additional RPCs per spec
}

message PutRequest {
  string namespace = 1;
  string key = 2;
  int32 value = 3;
}
// ... additional messages
```

### 3. Generate Python Bindings

```bash
cd /app  # Always run from proto directory
python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. <proto-file>.proto
```

**Generated files**: `<proto_base>_pb2.py` and `<proto_base>_pb2_grpc.py`
- Proto filename mapping: `kv-store.proto` → `kv_store_pb2.py` (dashes and dots become underscores)

### 4. Implement Server

```python
import grpc
import threading
from concurrent import futures

import kv_store_pb2
import kv_store_pb2_grpc


class Server(kv_store_pb2_grpc.KVStoreServicer):
    def __init__(self):
        self._lock = threading.Lock()
        self._ns = {}  # namespace -> {key: value}

    def Put(self, request, context):
        with self._lock:
            if request.namespace not in self._ns:
                self._ns[request.namespace] = {}
            self._ns[request.namespace][request.key] = request.value
            return kv_store_pb2.PutResponse(value=request.value)

    def Fetch(self, request, context):
        with self._lock:
            d = self._ns.get(request.namespace)
            if not d or request.key not in d:
                return kv_store_pb2.FetchResponse(value=0)  # default for missing
            return kv_store_pb2.FetchResponse(value=d[request.key])

    def Delete(self, request, context):
        with self._lock:
            d = self._ns.get(request.namespace)
            if not d or request.key not in d:
                return kv_store_pb2.DeleteResponse(success=False, value=0)
            return kv_store_pb2.DeleteResponse(success=True, value=d.pop(request.key))

    def ListNamespaceTotal(self, request, context):
        with self._lock:
            d = self._ns.get(request.namespace)
            if not d:
                return kv_store_pb2.ListNamespaceTotalResponse(total=0)
            total = sum(d.values())  # aggregate under lock
            return kv_store_pb2.ListNamespaceTotalResponse(total=total)


def serve():
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=10),
        options=(('grpc.so_reuseport', 0),),  # Critical: prevent duplicate binds
    )
    kv_store_pb2_grpc.add_KVStoreServicer_to_server(Server(), server)
    # With so_reuseport=0, duplicate bind raises RuntimeError (grpcio 1.73)
    server.add_insecure_port('[::]:5328')
    server.start()
    print("Server started on port 5328", flush=True)
    server.wait_for_termination()


if __name__ == '__main__':
    serve()
```

**Critical patterns**:
- **Lock all state operations**: Use `threading.Lock()` around all handler body operations, including aggregate reads (`sum()`)
- **Disable SO_REUSEPORT**: Prevents silent duplicate server processes that shard state
- **Dual-stack binding**: `[::]:<port>` accepts both IPv4 and IPv6 connections
- **Flush output**: `print(..., flush=True)` or run with `python3 -u` for immediate log visibility

### 5. Launch Server (Detached)

```bash
cd /app && nohup python3 -u server.py > /app/server.log 2>&1 &
```

**Canonical singleton launch**: Always from `/app` directory, always with `-u`, always logging to `/app/server.log`.

**Pre-launch cleanup** (if relaunching):

**Step 1: Detect cleanup tool**
```bash
command -v pkill
```

**Step 2: Execute appropriate kill**
- If `command -v pkill` returned path (e.g., `/usr/bin/pkill`):
  ```bash
  pkill -f '^python3.*server\.py'
  ```
- If `command -v pkill` returned nothing (minimal container), use /proc loop:
  ```bash
  for pid in $(ls /proc | grep -E '^[0-9]+$'); do
    [ "$pid" = "$$" ] && continue; [ "$pid" = "$PPID" ] && continue
    if tr '\0' ' ' < /proc/$pid/cmdline 2>/dev/null | grep -q '^python3.*server\.py'; then
      echo "killing $pid"; kill -9 "$pid"
    fi
  done
  ```

**Critical patterns**:
- Anchor on `^python3` (argv[0]) to avoid matching the shell itself — the shell's cmdline contains your script text
- Exclude `$$` (current shell) and `$PPID` (parent shell) in /proc loop

**Step 3: Verify the kill** (never skip - a failed kill is silent!)
```bash
python3 -c "import socket; s=socket.socket(); s.connect(('localhost',5328)); print('PORT IN USE')" 2>/dev/null || echo "PORT FREE"
```
- Expect "PORT FREE" before relaunching
- If you see "PORT IN USE", the old server is still holding the port — kill failed, investigate

### 6. Verify Readiness

Run a smoke test that exercises all RPCs over **two separate channels**:

```python
import grpc
import kv_store_pb2
import kv_store_pb2_grpc

# Channel 1: Write operations
ch1 = grpc.insecure_channel('localhost:5328')
grpc.channel_ready_future(ch1).result(timeout=10)
stub1 = kv_store_pb2_grpc.KVStoreStub(ch1)
stub1.Put(kv_store_pb2.PutRequest(namespace="ns1", key="k1", value=42))
ch1.close()

# Channel 2: Verify persistence
ch2 = grpc.insecure_channel('localhost:5328')
grpc.channel_ready_future(ch2).result(timeout=10)
stub2 = kv_store_pb2_grpc.KVStoreStub(ch2)
resp = stub2.Fetch(kv_store_pb2.FetchRequest(namespace="ns1", key="k1"))
assert resp.value == 42, "State must persist across channels"
ch2.close()
```

**Verification requirements**:
- `channel_ready_future().result(timeout=10)` confirms endpoint is accepting connections
- All RPC methods called at least once
- State written via channel 1 must be readable via channel 2
- Namespace isolation: operations in one namespace must not affect another

## Critical Gotchas

### 1. SO_REUSEPORT State Sharding

**Symptom**: RPCs succeed but state appears inconsistent across new connections (returns default values for keys that were written).

**Diagnosis**: Multiple server processes are running; gRPC's default SO_REUSEPORT allows them to share the port, and the kernel load-balances connections.

**Fix**: Disable reuseport in server options:
```python
server = grpc.server(
    futures.ThreadPoolExecutor(max_workers=10),
    options=(('grpc.so_reuseport', 0),),
)
```

With this option, duplicate launches raise `RuntimeError: Failed to bind to address` (observed in grpcio 1.73).

### 2. Buffered Logs Masking Launch Status

**Symptom**: Log file is empty immediately after launch; tempted to relaunch.

**Diagnosis**: Python stdout is block-buffered when redirected to file.

**Fix**: Use `python3 -u` (unbuffered) or `print(..., flush=True)` in server.

### 3. Proto Filename → Module Name Mapping

**Symptom**: ImportError for generated modules.

**Rule**: `protoc` maps `-` and `.` in proto filenames to `_` in Python module names.
- `kv-store.proto` → `import kv_store_pb2`
- `my.api.proto` → `import my_api_pb2`

**Fix**: Match imports to the generated filenames exactly.

### 4. Import Context Requirement

**Symptom**: `import kv_store_pb2` fails in server.py.

**Cause**: Generated grpc stub does top-level `import kv_store_pb2`, not package-relative.

**Fix**: Always launch server from `/app` directory so `/app` is on `sys.path`.

## End-State Audit

Before considering the task complete:

1. **Verify single instance**: Exactly one server process running
2. **Verify log line**: `/app/server.log` contains "Server started on port <port>"
3. **Run full smoke test**: All RPCs over two channels, state persistence verified, concurrent burst test passed
4. **Clean restart**: Kill the verified server and relaunch fresh (verification writes state; don't contaminate graded run)
5. **Final readiness probe**: Read-only operations only, then hands off

**CRITICAL ORDERING**: ALL write-testing happens before the clean restart. After relaunch: read-only operations only, then hands off. If you feel the urge to write after the restart, that's a signal your pre-restart verification was insufficient — go back, don't write.

**Final readiness probe** (read-only, non-mutating):
```python
channel = grpc.insecure_channel('localhost:5328')
grpc.channel_ready_future(channel).result(timeout=10)
stub = kv_store_pb2_grpc.KVStoreStub(channel)

# Exercise multiple RPC paths read-only (no writes)
assert stub.Fetch(kv_store_pb2.FetchRequest(namespace="probe_ns1", key="k1")).value == 0
assert stub.Fetch(kv_store_pb2.FetchRequest(namespace="probe_ns2", key="k2")).value == 0
assert stub.ListNamespaceTotal(kv_store_pb2.ListNamespaceTotalRequest(namespace="probe_ns1")).total == 0

channel.close()
print("✓ Read-only probe passed - hands off")
```

**Why this matters**: The frozen solver in iteration 2 did a `Put(final/test=123)` after the clean restart because the final probe was too thin. Resist the victory lap — verify with multiple read-only probes, then hands off.

## Per-Instance Adaptation

When RPC methods or message shapes differ:

1. Update proto file with exact field numbers and types from spec
2. Regenerate bindings (step 3)
3. Implement each servicer method matching the spec semantics:
   - Default values for missing keys (often 0 for int, "" for string)
   - Success/failure flags for conditional operations
   - Aggregate semantics (sum, count, etc.)
   - Namespace isolation rules

When port differs: Update `add_insecure_port('[::]:<port>')` and smoke test connection string.

### Proto3 Python API Pitfalls

When variants use enums, repeated, nested, or optional fields:

**Enums**:
- First enum value must be 0 (proto3 requirement, implicit default)
- Python compares as ints: `resp.status == kv_store_pb2.STATUS_OK`

**Repeated fields**:
- Direct assignment raises `AttributeError`
- Use: `msg.items.extend([...])` or `msg.items.append(item)`
- Returns `RepeatedScalarContainer` (supports len/iter/index)

**Nested messages**:
- Direct assignment raises: `msg.inner = Inner(...)` ✗
- Use kwargs: `Outer(inner=Inner(x=1))` ✓
- Or: `msg.inner.CopyFrom(Inner(...))` ✓
- Subfield access works: `msg.inner.x = 1` ✓

**Presence (optional fields)**:
- Plain scalars can't distinguish "unset" from "zero"
- Check presence with: `request.HasField('value')` (only for `optional` fields in proto)
- Default is always the zero value for the type

## Scripts

Reference implementations in `scripts/`:
- `server_template.py` - Template server with locking, SO_REUSEPORT=0, proper launch
- `smoke_test_template.py` - Full verification suite: correctness, persistence, concurrency

Copy and adapt these for each variant per the UPDATE comments.

## Example: v01 Specification

The v01 task implements:
- Service: `KVStore`
- RPCs: `Put`, `Fetch`, `Delete`, `ListNamespaceTotal`
- State: `{namespace: {key: int32}}`
- Semantics: namespace isolation, 0 default for missing keys, delete returns success+old_value
