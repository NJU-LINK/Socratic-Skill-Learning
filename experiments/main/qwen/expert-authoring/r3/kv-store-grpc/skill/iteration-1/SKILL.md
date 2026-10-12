---
name: kv-store-grpc
description: >
  Build a Python gRPC stateful key-value store service from a task specification.
  Covers proto authoring, code generation, server implementation with in-memory
  state, and reliable server startup. Generalizes across varying RPC signatures,
  message structures, state semantics (namespaces, aggregates, conditionals),
  and runtime requirements.
---

# KV-Store gRPC Service — Compile Skill

## 1. Family Overview

Every task in this family requires:

1. Installing pinned `grpcio` and `grpcio-tools` system-wide.
2. Writing a `.proto` file that defines one gRPC service with unary RPCs.
3. Generating Python stubs (`*_pb2.py` and `*_pb2_grpc.py`).
4. Implementing a Python server class that maintains **in-memory state** across
   RPC calls and client channels.
5. Starting the server on a specified port and leaving it running.

Variation occurs along three axes (see spec.yaml):

| Axis | What varies |
|------|-------------|
| `rpc_api_structure` | Number of RPCs, message field counts/types, nesting, enums |
| `stateful_service_semantics` | Collections, namespaces, default values, conditional writes, aggregates, deletes |
| `runtime_interaction_requirements` | Port, concurrency, startup timing, channel lifecycle |

## 2. Extraction Phase — Read the Task Spec

Parse `task.yaml` (or equivalent instruction block) to extract a **service
blueprint**. Build a mental model with these slots:

```
service_name:       str          # e.g. "KVStore"
proto_path:         str          # e.g. "/app/kv-store.proto"
generated_pb2:      str          # e.g. "/app/kv_store_pb2.py"
generated_pb2_grpc: str          # e.g. "/app/kv_store_pb2_grpc.py"
server_path:        str          # e.g. "/app/server.py"
server_class:       str          # e.g. "Server"
port:               int          # e.g. 5328
grpcio_version:     str          # e.g. "1.73.0" (may be omitted → use task-specified or latest)

rpcs: list of:
  name:           str            # e.g. "Put"
  request_msg:    str            # e.g. "PutRequest"
  response_msg:   str            # e.g. "PutResponse"
  request_fields: list[field]    # (name, type, field_number)
  response_fields: list[field]   # (name, type, field_number)

state_model:
  structure:      str            # "flat_dict" | "namespaced_dict" | "multi_collection" | ...
  default_read:   any            # value returned for missing key (e.g. 0, "", empty message)
  namespaces:     bool           # whether keys are scoped by namespace
  operations:     dict           # semantic rules per RPC (see §5)
```

**Decision rule:** Every field name, type, field number, message name, and RPC
name MUST match the task spec exactly. Do not invent extra fields or rename
anything. When the spec says "field 1", it means protobuf field number 1.

## 3. Dependency Installation

```bash
pip install grpcio==<version> grpcio-tools==<version>
```

- Use the exact version from the task spec. If none specified, use `1.73.0` as default.
- Install **system-wide** (no virtualenv) so test harnesses can import the modules.
- Verify: `python3 -c "import grpc; print(grpc.__version__)"` must print the expected version.

## 4. Proto File Authoring

### 4.1 Template

```protobuf
syntax = "proto3";

service <ServiceName> {
  // One rpc line per RPC, all unary:
  rpc <RpcName>(<RequestMsg>) returns (<ResponseMsg>);
  ...
}

message <RequestMsg> {
  <type> <name> = <field_number>;
  ...
}

message <ResponseMsg> {
  <type> <name> = <field_number>;
  ...
}
```

### 4.2 Field Type Mapping

| Proto type | Python generated type | Notes |
|-----------|----------------------|-------|
| `string`  | `str` | |
| `int32`   | `int` | |
| `int64`   | `int` | |
| `bool`    | `bool` | |
| `float`   | `float` | |
| `double`  | `float` | |
| `bytes`   | `bytes` | |
| enum      | `int` | Define enum in proto, use integer values in Python |
| repeated  | `list` | `repeated string tags = 4;` |
| nested message | message class | Define inner message, reference by name |

### 4.3 Proto Authoring Rules

- **Field numbers** must match the spec exactly — they are part of the wire format.
- **Field names** must use the exact casing from the spec (typically `snake_case` in proto).
- All messages referenced in RPC signatures must be defined.
- Use `syntax = "proto3";` unless the spec says otherwise.
- Write the proto to the exact path specified in the task.

### 4.4 Code Generation

```bash
python3 -m grpc_tools.protoc \
  -I<proto_dir> \
  --python_out=<out_dir> \
  --grpc_python_out=<out_dir> \
  <proto_file>
```

Where `<proto_dir>` is the directory containing the `.proto` file and `<out_dir>`
is typically the same directory. The generated files are:
- `<basename>_pb2.py` — message classes
- `<basename>_pb2_grpc.py` — service stubs, servicer base class, `add_*_to_server`

Verify both files exist after generation.

## 5. Server Implementation

### 5.1 Skeleton

```python
import grpc
from concurrent import futures
import <basename>_pb2
import <basename>_pb2_grpc

class <ServerClass>(<basename>_pb2_grpc.<ServiceName>Servicer):

    def __init__(self):
        # Initialize in-memory state here.
        # Structure depends on state_model (see §5.2)
        self.<state> = ...

    def <RpcName>(self, request, context):
        # Implement per the semantic rules in the task spec
        ...

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    <basename>_pb2_grpc.add_<ServiceName>Servicer_to_server(
        <ServerClass>(), server
    )
    server.add_insecure_port(f"[::]:<port>")
    server.start()
    server.wait_for_termination()

if __name__ == "__main__":
    serve()
```

### 5.2 State Model Patterns

Choose based on the task's state semantics:

**Flat dictionary** (single collection, string keys → scalar values):
```python
self.store: dict[str, int] = {}
```

**Namespaced dictionary** (namespace → key → value):
```python
from collections import defaultdict
self.store: dict[str, dict[str, int]] = defaultdict(dict)
```

**Multi-collection** (separate named stores):
```python
self.stores: dict[str, dict[str, Any]] = {}
```

### 5.3 Common Operation Semantics

Map each RPC to its semantic rule from the task spec. Common patterns:

| Operation | Typical Semantics |
|-----------|-------------------|
| **Put/Set** | `store[key] = value; return value` |
| **Get/Fetch** | `return store.get(key, default)` — check spec for default (often `0` for int, `""` for string) |
| **Delete** | `if key in store: val = store.pop(key); return (True, val) else: return (False, default)` |
| **List/Count** | Aggregate over collection: `sum(store.values())`, `len(store)`, etc. Return `0`/default for empty/absent. |
| **Exists** | `return key in store` |
| **Increment** | `store[key] = store.get(key, 0) + delta; return store[key]` |
| **Conditional update** | Only write if condition holds (e.g., key exists, value matches) |
| **Batch/Multi-key** | Iterate over repeated field in request |

**Critical rule:** Read the task spec for the EXACT default values and edge-case
behavior. "Returns 0 for missing key" ≠ "returns -1 for missing key". These
details are the most common source of test failures.

### 5.4 Namespace Isolation

When the spec requires namespaces:
- Each namespace is an independent key space.
- A key `"foo"` in namespace `"ns1"` is distinct from `"foo"` in namespace `"ns2"`.
- Operations on one namespace must not affect another.
- Aggregations (sum, count, list) only cover the specified namespace.
- Non-existent namespaces return the default value (typically `0` for totals).

### 5.5 State Persistence

- State lives on the servicer instance (`self`).
- The servicer is instantiated **once** and shared across all RPC calls.
- Do NOT reinitialize state in RPC methods.
- State persists across multiple client channels connecting to the same server.

## 6. Server Startup

### 6.1 Reliable Launch

```bash
# Start server in background, redirect output to log file
cd /app && python3 server.py > /app/server.log 2>&1 &
SERVER_PID=$!

# Wait for readiness — poll with a gRPC channel
python3 -c "
import grpc, time, sys
for _ in range(30):
    try:
        ch = grpc.insecure_channel('localhost:<port>')
        grpc.channel_ready_future(ch).result(timeout=1)
        print('Server ready'); sys.exit(0)
    except Exception:
        time.sleep(0.3)
print('Server not ready', file=sys.stderr); sys.exit(1)
"
```

### 6.2 Startup Checklist

- [ ] Server process is running (check PID).
- [ ] Server is listening on the correct port.
- [ ] Server accepts gRPC connections (channel ready).
- [ ] No import errors in server.log.
- [ ] Server stays running (not exiting immediately).

### 6.3 Common Startup Failures

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ModuleNotFoundError` | Generated files not on path | Ensure `_pb2.py` files are in same dir as `server.py` or in `PYTHONPATH` |
| `Address already in use` | Port conflict | Kill previous process: `fuser -k <port>/tcp` |
| Server exits immediately | Missing `wait_for_termination()` | Add `server.wait_for_termination()` after `server.start()` |
| `ImportError` on grpc | Wrong Python / missing install | `pip install grpcio==<ver> grpcio-tools==<ver>` |

## 7. Self-Verification Checklist

Before declaring the task complete, verify ALL of the following:

1. **Proto correctness**: `.proto` file exists at the specified path, compiles
   without errors, and all message/RPC names match the spec.
2. **Generated files**: Both `_pb2.py` and `_pb2_grpc.py` exist and are
   importable.
3. **Server running**: Process is alive, port is open, channel connects.
4. **Semantic spot-check**: Use `grpcurl` or a quick Python client to test
   at least:
   - A write (Put) followed by a read (Fetch/Get) returns the written value.
   - Reading a missing key returns the specified default.
   - State persists across separate calls.
5. **Edge cases**: Test the boundaries mentioned in the spec (empty namespace,
   delete missing key, aggregate on empty collection).

### 7.1 Quick Smoke Test Pattern

```python
import grpc
import <basename>_pb2
import <basename>_pb2_grpc

ch = grpc.insecure_channel("localhost:<port>")
stub = <basename>_pb2_grpc.<ServiceName>Stub(ch)

# Adapt these calls to match the actual RPC names and message fields
resp = stub.<PutRpc>(<PutRequest>(namespace="test", key="k1", value=42))
assert resp.value == 42, f"Put failed: {resp}"

resp = stub.<FetchRpc>(<FetchRequest>(namespace="test", key="k1"))
assert resp.value == 42, f"Fetch failed: {resp}"

resp = stub.<FetchRpc>(<FetchRequest>(namespace="test", key="missing"))
assert resp.value == 0, f"Default value wrong: {resp}"
```

## 8. Variation Handling Guide

When the task differs from the seed (v01), adapt along these axes:

### 8.1 More RPCs or Complex Messages

- Add each RPC to the proto service block.
- Define all new messages with correct field types and numbers.
- Add a method per RPC on the servicer class.
- For `repeated` fields, iterate in the handler; populate with `.append()` or
  list assignment in responses.
- For `enum` fields, define the enum in proto, use integer constants in Python.

### 8.2 Different State Semantics

- **Deletes with tombstones**: Track deleted keys separately if spec requires
  distinguishing "never set" from "deleted".
- **Conditional updates**: Check the condition before writing; return
  appropriate status in the response.
- **Multi-key operations**: Iterate over `repeated` request fields; build
  `repeated` response fields.
- **Aggregates**: Compute over the relevant subset of state; handle empty case.

### 8.3 Stricter Runtime Requirements

- **Higher concurrency**: Increase `max_workers` in `ThreadPoolExecutor`.
- **Readiness probes**: Implement a health check RPC or rely on channel-ready polling.
- **Graceful shutdown**: Register signal handlers if the spec requires clean stops.
- **Long-lived sessions**: Ensure no resource leaks (the default gRPC server
  handles this well for in-memory state).

## 9. Anti-Patterns to Avoid

- **Hardcoding v01 values**: Do not embed specific port numbers, field names, or
  RPC names from the seed. Always extract from the current task spec.
- **Skipping code generation**: Never hand-write `_pb2.py` files; always use
  `grpc_tools.protoc`.
- **Mutable default arguments**: Never use `{}` or `[]` as default parameter
  values in the servicer `__init__`.
- **Re-creating state per call**: State must be on `self`, initialized once in
  `__init__`.
- **Blocking the server thread**: Avoid `time.sleep()` or blocking I/O inside
  RPC handlers unless the spec requires it.
- **Wrong import paths**: Generated files must be importable from the server
  script's working directory.
