---
name: kv-store-grpc
description: >
  Build a Python gRPC stateful key-value store service from a task specification.
  Covers proto authoring, code generation, server implementation with in-memory
  state, and reliable server startup. Generalizes across varying RPC signatures,
  message structures, state semantics (namespaces, aggregates, conditionals),
  and runtime requirements including concurrent access.
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

| Proto | Python generated | Notes |
|-------|------------------|-------|
| `string` | `str` | |
| `int32` / `int64` | `int` | |
| `bool` | `bool` | |
| `float` / `double` | `float` | |
| `bytes` | `bytes` | |
| `enum` | `int` | Define enum in proto; use int values in Python |
| `repeated X` | `RepeatedCompositeFieldContainer` | See §5.4 for how to populate in handlers |
| nested message | message class | Define before use; reference by name in proto |

### Proto gotchas

- **Field names** must use exact casing from spec (typically `snake_case`).
- **Field numbers** are wire-format — wrong numbers = silent data corruption.
- **Reserved words:** If a field name collides with Python builtins (e.g., `type`,
  `id`), proto3 still compiles but the generated Python attribute may have a
  suffix. Test access after generation.
- All messages referenced in `rpc` lines must be defined in the same `.proto`.
- Nested messages must be defined before the message that uses them (or use
  forward reference by name — proto3 allows this within the same file).
- Use `syntax = "proto3";` unless spec says otherwise.

## Step 4 — Generate Python Stubs

```bash
cd <proto_dir> && python3 -m grpc_tools.protoc \
  -I. --python_out=. --grpc_python_out=. <proto_filename>
```

**Verify** both `<basename>_pb2.py` and `<basename>_pb2_grpc.py` exist. If either
is missing, the protoc command failed — check error output.

## Step 5 — Implement the Server

### Skeleton — ALWAYS use threading.Lock() for state

The gRPC server uses `ThreadPoolExecutor` which dispatches RPCs to multiple
threads. **All state access must be protected by a lock** to prevent race
conditions (e.g., check-then-act on namespace dicts).

```python
import grpc
import threading
from concurrent import futures
import <basename>_pb2
import <basename>_pb2_grpc

class <ServerClass>(<basename>_pb2_grpc.<ServiceName>Servicer):

    def __init__(self):
        self.lock = threading.Lock()
        self.store = {}  # state dict — structure depends on spec

    def <RpcName>(self, request, context):
        with self.lock:
            # ALL state reads and writes happen inside the lock
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

**Why the lock is mandatory:** Without it, the pattern
`if ns not in self.store: self.store[ns] = {}` is a race condition — two threads
could both see `ns not in store`, both create `{}`, and one overwrites the
other's data. The lock costs nothing on single-threaded tests and prevents
silent data loss under concurrent load.

### State model selection

| Spec pattern | Python structure |
|-------------|-----------------|
| Flat key→value | `self.store: dict[str, int] = {}` |
| Namespaced key→value | `self.store: dict[str, dict[str, int]] = {}` |
| Multi-collection | `self.stores: dict[str, dict] = {}` |

**Use plain `dict` with explicit `if ns in self.store` checks** rather than
`defaultdict` — this avoids accidentally creating empty namespaces that could
affect aggregate operations like `ListNamespaceTotal`.

### Operation semantics reference

All patterns below execute **inside `with self.lock:`**.

| Operation | Pattern | Key detail |
|-----------|---------|-----------|
| **Put/Set** | `store[ns][key] = val; return Resp(value=val)` | Overwrites existing |
| **Fetch/Get** | `val = store.get(ns, {}).get(key, DEFAULT)` | DEFAULT from spec (commonly `0` for int) |
| **Delete** | `if ns in store and key in store[ns]: val = store[ns].pop(key); return (True, val)` | Missing → `(False, DEFAULT)` |
| **Sum/Total** | `total = sum(store.get(ns, {}).values())` | Empty/absent ns → `0` |
| **Count** | `count = len(store.get(ns, {}))` | Empty/absent ns → `0` |
| **Exists** | `found = ns in store and key in store[ns]` | |
| **Increment** | `store[ns][key] = store[ns].get(key, 0) + delta` | |
| **Reset/Clear** | `store[ns] = {}` or `del store[ns]` | Clears all keys in scope |
| **Conditional write** | Check condition first; only mutate if true | Return status indicating result |

**The #1 source of failures is wrong default values or edge-case behavior.**
Read the spec for EXACT defaults: "returns 0 for missing" ≠ "returns -1".

### Populating repeated and nested fields in responses

When a response has `repeated` fields or nested message fields, use these
patterns inside the handler (still within `with self.lock:`):

**Repeated scalar fields** (`repeated string items = 1;` or `repeated int32 values = 2;`):
```python
# Build the response, then populate
resp = <basename>_pb2.MyResponse()
resp.items.append("a")           # add one item
resp.items.extend(["b", "c"])   # add multiple items
resp.values.extend([1, 2, 3])   # same for int32

# OR use constructor with list (works for scalars):
resp = <basename>_pb2.MyResponse(items=["a", "b", "c"], values=[1, 2, 3])
```

**Repeated nested message fields** (`repeated Entry entries = 1;` where Entry is a message):
```python
resp = <basename>_pb2.MyResponse()

# Method 1: .add() creates and returns a new sub-message in-place
entry = resp.entries.add()
entry.name = "alice"
entry.score = 95

# Method 2: create sub-messages then .append()
e = <basename>_pb2.Entry(name="bob", score=80)
resp.entries.append(e)

# Method 3: .extend() with a list of sub-messages
resp.entries.extend([
    <basename>_pb2.Entry(name="a", score=1),
    <basename>_pb2.Entry(name="b", score=2),
])
```

**Single nested message field** (`Entry winner = 1;`):
```python
resp = <basename>_pb2.MyResponse()
resp.winner.name = "alice"       # auto-creates the sub-message
resp.winner.score = 95
# OR:
resp.winner.CopyFrom(<basename>_pb2.Entry(name="alice", score=95))
```

### Enum fields in handlers

```protobuf
// In proto:
enum Status {
  UNKNOWN = 0;
  ACTIVE = 1;
  INACTIVE = 2;
}
message MyResponse {
  Status status = 1;
}
```

```python
# In Python handler — enums are ints:
resp = <basename>_pb2.MyResponse(status=<basename>_pb2.ACTIVE)
# OR use the integer directly:
resp = <basename>_pb2.MyResponse(status=1)
```

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

## Step 6 — Build, Launch, and Verify

After writing all files, generate stubs, start the server, and poll for readiness:

```bash
cd /app && python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. <proto_filename> && \
echo "Stubs generated" && \
python3 server.py > /app/server.log 2>&1 &
echo "Server PID: $!" && \
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

| Log error | Fix |
|-----------|-----|
| `ModuleNotFoundError` | Stubs not generated or wrong directory — rerun Step 4 |
| `Address already in use` | Kill old: `python3 -c "import os,signal; os.kill(<PID>, signal.SIGTERM)"` |
| Missing `wait_for_termination` | Server exits immediately — add it to `serve()` |
| `SyntaxError` | Check heredoc quoting — use `'PYEOF'` not `PYEOF` |

## Step 7 — Smoke Test

Test each RPC against the live server. For each RPC, verify:
1. Happy path (normal values)
2. Default/missing case (absent key, empty namespace)
3. Edge case from spec (overwrite, delete-missing, aggregate on empty)
4. Cross-call state persistence (put then fetch)
5. Cross-channel persistence (new channel sees prior state)

```python
import grpc
import <basename>_pb2
import <basename>_pb2_grpc

ch = grpc.insecure_channel("localhost:<PORT>")
stub = <basename>_pb2_grpc.<ServiceName>Stub(ch)

# Adapt to actual RPC names and fields from spec
resp = stub.Put(<PutRequest>(namespace="t", key="k", value=42))
assert resp.value == 42

resp = stub.Fetch(<FetchRequest>(namespace="t", key="k"))
assert resp.value == 42

resp = stub.Fetch(<FetchRequest>(namespace="t", key="missing"))
assert resp.value == 0  # spec default

# Cross-channel persistence
ch2 = grpc.insecure_channel("localhost:<PORT>")
stub2 = <basename>_pb2_grpc.<ServiceName>Stub(ch2)
resp = stub2.Fetch(<FetchRequest>(namespace="t", key="k"))
assert resp.value == 42

print("All smoke tests passed")
```

**Adapt field names and RPC calls to match the actual spec.** The above is a
pattern, not a copy-paste solution.

### Process management without shell tools

In minimal containers, `ps`, `fuser`, `pkill` may not exist. Use Python:

```python
import os, signal, socket

# Check process alive:
try: os.kill(pid, 0); print("alive")
except ProcessLookupError: print("dead")

# Kill process:
os.kill(pid, signal.SIGTERM)

# Check port open:
s = socket.socket(); is_open = s.connect_ex(('localhost', PORT)) == 0; s.close()
```

## Step 8 — Completion Checklist

- [ ] `.proto` file at specified path with correct service, RPCs, messages
- [ ] Both `_pb2.py` and `_pb2_grpc.py` generated and importable
- [ ] `server.py` at specified path with correct class name
- [ ] `threading.Lock()` protecting all state access in every RPC handler
- [ ] Server process alive and listening on specified port
- [ ] All RPCs return correct values for happy path AND edge cases
- [ ] State persists across separate calls and separate channels

## Variation Adaptation

**More RPCs or complex messages:** Add each RPC to proto service block and
servicer class. See §5.4 for repeated/nested field patterns in handlers.

**Different state semantics:** Read each RPC's spec rule carefully. Map to the
operation semantics table in §5.3. Pay special attention to default values and
what "missing" means for each operation.

**Stricter runtime (concurrency):** The `threading.Lock()` in the skeleton
already handles concurrent access. For higher throughput, increase `max_workers`
in `ThreadPoolExecutor`. The lock ensures correctness under any concurrency level.
