---
name: kv-store-grpc
description: >
  Build a Python gRPC stateful key-value store service from a task specification.
  Covers proto authoring, code generation, server implementation with in-memory
  state, and reliable server startup. Generalizes across varying RPC signatures,
  message structures, state semantics (namespaces, aggregates, conditionals),
  and runtime requirements.
---

# KV-Store gRPC Service

## Step 1 — Parse the Task Spec

Extract these exact values from `task.yaml`:

| Slot | Example | Rule |
|------|---------|------|
| `service_name` | `KVStore` | Exact name from spec |
| `proto_path` | `/app/kv-store.proto` | Exact path from spec |
| `pb2_path` | `/app/kv_store_pb2.py` | Derived: replace `-` with `_`, append `_pb2.py` |
| `pb2_grpc_path` | `/app/kv_store_pb2_grpc.py` | Same derivation + `_grpc.py` |
| `server_path` | `/app/server.py` | Exact path from spec |
| `server_class` | `Server` | Exact name from spec |
| `port` | `5328` | Exact integer from spec |
| `grpcio_version` | `1.73.0` | Exact version from spec |
| `rpcs[]` | Put, Fetch, Delete, … | Each with request/response message names, fields, types, field numbers |
| `state_semantics` | namespaced dict, defaults, … | Per-RPC behavioral rules |

**Critical:** Every field name, field number, message name, and RPC name must match
the spec exactly. "Field 1" means protobuf field number 1.

## Step 2 — Install Dependencies

```bash
pip install grpcio==<VERSION> grpcio-tools==<VERSION>
```

Verify: `python3 -c "import grpc; print(grpc.__version__)"` → must print the expected version.

## Step 3 — Write the Proto File

### Proto template

```protobuf
syntax = "proto3";

service <ServiceName> {
  rpc <RpcName>(<RequestMsg>) returns (<ResponseMsg>);
  // …one line per RPC
}

message <MsgName> {
  <proto_type> <field_name> = <field_number>;
  // …one line per field
}
```

### Field type mapping

| Proto | Python | Notes |
|-------|--------|-------|
| `string` | `str` | |
| `int32` / `int64` | `int` | |
| `bool` | `bool` | |
| `float` / `double` | `float` | |
| `bytes` | `bytes` | |
| `enum` | `int` | Define enum in proto; use int values in Python |
| `repeated X` | `list` | `.append()` or `[:]` assignment in handlers |
| nested message | message class | Define before use |

### Proto gotchas

- **Field names** must use exact casing from spec (typically `snake_case`).
- **Field numbers** are wire-format — wrong numbers = silent data corruption.
- **Reserved words:** If a field is named something that collides with Python
  builtins or protobuf internals (e.g., `type`, `id`), it still works in proto3
  but the generated Python attribute may have a suffix. Test access.
- All messages referenced in `rpc` lines must be defined in the same `.proto`.
- Use `syntax = "proto3";` unless spec says otherwise.

## Step 4 — Generate Python Stubs

```bash
cd <proto_dir> && python3 -m grpc_tools.protoc \
  -I. --python_out=. --grpc_python_out=. <proto_filename>
```

**Verify** both `<basename>_pb2.py` and `<basename>_pb2_grpc.py` exist. If either
is missing, the protoc command failed — check error output.

## Step 5 — Implement the Server

### Skeleton (fill in from spec)

```python
import grpc
from concurrent import futures
import <basename>_pb2
import <basename>_pb2_grpc

class <ServerClass>(<basename>_pb2_grpc.<ServiceName>Servicer):

    def __init__(self):
        # ONE state initialization — persists across all calls and channels
        self.store = {}  # or defaultdict(dict) for namespaced

    def <RpcName>(self, request, context):
        # Implement per spec semantics
        ...

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    <basename>_pb2_grpc.add_<ServiceName>Servicer_to_server(<ServerClass>(), server)
    server.add_insecure_port("[::]:<PORT>")
    server.start()
    server.wait_for_termination()

if __name__ == "__main__":
    serve()
```

### State model selection

| Spec pattern | Python structure |
|-------------|-----------------|
| Flat key→value | `self.store: dict[str, int] = {}` |
| Namespaced key→value | `self.store: dict[str, dict[str, int]] = {}` (check `ns in self.store` before access) |
| Multi-collection | `self.stores: dict[str, dict] = {}` |

**Use plain `dict` with explicit `if ns in self.store` checks** rather than
`defaultdict` — this avoids accidentally creating empty namespaces that could
affect aggregate operations like `ListNamespaceTotal`.

### Operation semantics reference

| Operation | Pattern | Key detail |
|-----------|---------|-----------|
| **Put/Set** | `store[ns][key] = val; return val` | Overwrites existing |
| **Fetch/Get** | `store.get(ns, {}).get(key, DEFAULT)` | DEFAULT from spec (commonly `0` for int) |
| **Delete** | `if key in store[ns]: val = store[ns].pop(key); return (True, val)` | Missing → `(False, DEFAULT)` |
| **Sum/Total** | `sum(store.get(ns, {}).values())` | Empty/absent ns → `0` |
| **Count** | `len(store.get(ns, {}))` | Empty/absent ns → `0` |
| **Exists** | `key in store.get(ns, {})` | |
| **Increment** | `store[ns][key] = store[ns].get(key, 0) + delta` | |
| **Conditional write** | Check condition first; only write if true | Return status indicating whether write occurred |

**The #1 source of failures is wrong default values or edge-case behavior.**
Read the spec for EXACT defaults: "returns 0 for missing" ≠ "returns -1".

### Namespace isolation rules

- Each namespace is an independent key space.
- Operations on namespace A must not affect namespace B.
- Aggregations (sum, count) only cover the specified namespace.
- Non-existent or empty namespaces return the default (typically `0`).

### State persistence rules

- State lives on `self`, initialized **once** in `__init__`.
- The servicer is instantiated once and shared across all RPC calls.
- State persists across multiple client channels to the same server.
- Never reinitialize state inside an RPC method.

## Step 6 — Build, Launch, and Verify (single pipeline)

Run this combined pipeline after writing all files. It generates stubs, starts
the server, and polls for readiness — all in one command:

```bash
# 1. Generate stubs
cd /app && python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. <proto_filename> && \
echo "Stubs generated" && \
# 2. Kill anything on the target port (Python-based, works in minimal containers)
python3 -c "
import socket, signal, os
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
if s.connect_ex(('localhost', <PORT>)) == 0:
    print('WARNING: port <PORT> already in use')
s.close()
" && \
# 3. Start server in background
python3 server.py > /app/server.log 2>&1 &
echo "Server PID: $!" && \
# 4. Wait for readiness via gRPC channel
python3 -c "
import grpc, time, sys
for _ in range(30):
    try:
        ch = grpc.insecure_channel('localhost:<PORT>')
        grpc.channel_ready_future(ch).result(timeout=1)
        print('Server ready'); sys.exit(0)
    except Exception:
        time.sleep(0.3)
print('Server FAILED to start — check /app/server.log', file=sys.stderr)
sys.exit(1)
"
```

Replace `<PORT>` and `<proto_filename>` with actual values from Step 1.

### If the server fails to start

```bash
cat /app/server.log
```

Common causes:

| Log error | Fix |
|-----------|-----|
| `ModuleNotFoundError: kv_store_pb2` | Stubs not generated or wrong directory — rerun Step 4 |
| `Address already in use` | Kill old process: `python3 -c "import os,signal; os.kill(<PID>, signal.SIGTERM)"` |
| Missing `wait_for_termination` | Server exits immediately — add it to `serve()` |
| `SyntaxError` in server.py | Check heredoc quoting — use `'PYEOF'` not `PYEOF` |

## Step 7 — Smoke Test

Run a comprehensive client-side test against the live server:

```python
import grpc
import <basename>_pb2
import <basename>_pb2_grpc

ch = grpc.insecure_channel("localhost:<PORT>")
stub = <basename>_pb2_grpc.<ServiceName>Stub(ch)

# Test each RPC per spec semantics. For each RPC, test:
# 1. Happy path (normal values)
# 2. Default/missing case (absent key, empty namespace)
# 3. Edge case from spec (overwrite, delete-missing, aggregate on empty)
# 4. Cross-call state persistence (put then fetch in separate calls)

# Example pattern for a namespaced store:
resp = stub.Put(<PutRequest>(namespace="t", key="k", value=42))
assert resp.value == 42

resp = stub.Fetch(<FetchRequest>(namespace="t", key="k"))
assert resp.value == 42

resp = stub.Fetch(<FetchRequest>(namespace="t", key="missing"))
assert resp.value == 0  # spec default

resp = stub.Delete(<DeleteRequest>(namespace="t", key="k"))
assert resp.success == True and resp.value == 42

resp = stub.Delete(<DeleteRequest>(namespace="t", key="k"))
assert resp.success == False and resp.value == 0

# Namespace isolation
resp = stub.Fetch(<FetchRequest>(namespace="other", key="k"))
assert resp.value == 0

print("All smoke tests passed")
```

**Adapt field names and RPC calls to match the actual spec.** The above is a
pattern, not a copy-paste solution.

### Process management without shell tools

In minimal containers, `ps`, `fuser`, `pkill`, `kill` may not exist. Use Python:

```python
# Check if a process is alive
import os, signal
try:
    os.kill(pid, 0)  # signal 0 = existence check
    print(f"PID {pid} is alive")
except ProcessLookupError:
    print(f"PID {pid} is dead")

# Kill a process
import os, signal
os.kill(pid, signal.SIGTERM)

# Check if a port is open
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
is_open = s.connect_ex(('localhost', PORT)) == 0
s.close()
```

## Step 8 — Completion Checklist

Before declaring done:

- [ ] `.proto` file at specified path with correct service, RPCs, messages
- [ ] Both `_pb2.py` and `_pb2_grpc.py` generated and importable
- [ ] `server.py` at specified path with correct class name
- [ ] Server process alive and listening on specified port
- [ ] gRPC channel connects successfully
- [ ] All RPCs return correct values for happy path AND edge cases
- [ ] State persists across separate calls (and separate channels if spec requires)

## Variation Adaptation

When the task differs from the seed:

**More RPCs or complex messages:** Add each RPC to proto service block and
servicer class. For `repeated` fields, iterate in handler; use `.append()` or
list assignment in responses. For `enum` fields, define enum in proto.

**Different state semantics:** Read each RPC's spec rule carefully. Map to the
operation semantics table above. Pay special attention to default values and
what "missing" means for each operation.

**Stricter runtime:** Increase `max_workers` for concurrency. Use the
channel-ready polling loop for startup timing. The `server.wait_for_termination()`
call keeps the server alive indefinitely.
