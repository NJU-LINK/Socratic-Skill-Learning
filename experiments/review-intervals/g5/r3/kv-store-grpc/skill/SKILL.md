---
name: kv-store-grpc
description: >
  Build a stateful Python gRPC service with in-memory state, thread-safe request handling,
  and correct proto compilation. Covers the full pipeline from .proto authoring through
  code generation to server implementation and lifecycle management. Generalizes across
  variations in RPC structure, state semantics, and runtime requirements.
---

# kv-store-grpc

Build a real Python gRPC service with in-memory stateful semantics. This skill covers the
complete pipeline: proto definition → code generation → server implementation → lifecycle
management. It generalizes across variations in RPC API structure, state management semantics,
and runtime interaction requirements.

## When to Use

- Building a Python gRPC service (server-side) with protobuf-defined RPCs
- Service must maintain in-memory state across RPC calls
- Service must handle concurrent requests safely
- Service must remain running and serve requests over a port

## Package Structure

This skill package contains:

```
skill/kv-store-grpc/
├── SKILL.md              # This file — complete documentation
├── templates/
│   ├── kv-store.proto    # Reference proto (v01 example)
│   └── server.py         # Reference server implementation (v01 example)
└── scripts/
    └── setup.sh          # Automated setup script (optional)
```

**You do not need to list directories** — all files are documented here. Read the templates to understand the pattern, then adapt to the task requirements.

## Quick Start Procedure

Follow these steps in order. Do NOT skip steps or copy templates verbatim without reading the task requirements first.

1. **Read task.yaml carefully** — identify the exact service name, RPC methods, message fields, field numbers, port, and state semantics
2. **Install dependencies**: Use the versions specified in the task. If not specified, use `pip install grpcio==1.73.0 grpcio-tools==1.73.0`
3. **Write the proto file** at the path specified in the task (e.g., `/app/<name>.proto`) — adapt from `templates/kv-store.proto` but match task requirements exactly
4. **Generate Python bindings**: `python -m grpc_tools.protoc -I<dir> --python_out=<dir> --grpc_python_out=<dir> <dir>/<proto>.proto`
5. **Verify generated files exist** and check the `_pb2_grpc.py` for correct import paths and class names
6. **Implement server.py** — adapt from `templates/server.py`: correct base class, all RPC methods, proper state structure, correct port
7. **Start the server** as a background process: `cd /app && python server.py &`
8. **Smoke test** with a client to verify all RPCs work before declaring done
9. **Leave the server running** — do not kill it; tests will connect to it

## Core Pipeline

### 1. Install Dependencies

```bash
pip install grpcio==1.73.0 grpcio-tools==1.73.0
```

**Version flexibility:** Use the versions specified in the task. If the task specifies different versions (e.g., `grpcio==1.70.0`), use those instead. The key requirement is that `grpcio` and `grpcio-tools` versions must match — the generated `_pb2_grpc.py` includes a version check that will fail if they don't match.

Pin exact versions to ensure protoc compatibility with generated code.

### 2. Author the Proto File

```protobuf
syntax = "proto3";

package <package_name>;

service <ServiceName> {
  rpc <MethodA>(<MethodA>Request) returns (<MethodA>Response);
  rpc <MethodB>(<MethodB>Request) returns (<MethodB>Response);
  // ... more RPCs as needed
}

message <MethodA>Request {
  <type> <field_name> = <field_number>;
  // ... more fields
}

message <MethodA>Response {
  <type> <field_name> = <field_number>;
}
```

**Critical rules:**
- `syntax = "proto3";` is required (not proto2)
- Every field MUST have an explicit field number starting at 1
- Field numbers must be unique within a message
- The proto filename can contain hyphens (e.g., `kv-store.proto`), but protoc generates
  Python files with underscores (`kv_store_pb2.py`)
- Use `package` declaration for namespace organization

**Field types:** `string`, `int32`, `int64`, `bool`, `float`, `double`, `bytes`, or nested
message types. For repeated fields: `repeated string tags = 1;`. For enums: define an `enum`
block and use it as a field type.

### 3. Generate Python Bindings

```bash
python -m grpc_tools.protoc \
  -I<proto_directory> \
  --python_out=<output_directory> \
  --grpc_python_out=<output_directory> \
  <proto_directory>/<proto_file>.proto
```

**The `-I` flag is the most common gotcha.** It controls the import path in generated code.
If your proto is at `/app/kv-store.proto` and you run:

```bash
python -m grpc_tools.protoc -I/app --python_out=/app --grpc_python_out=/app /app/kv-store.proto
```

The generated `kv_store_pb2_grpc.py` will contain `import kv_store_pb2` (correct).

If you instead run from a different directory without `-I/app`, you might get
`import app.kv_store_pb2` (wrong — will fail at runtime).

**Rule:** Always set `-I` to the directory containing the proto file, and use the same
directory for `--python_out` and `--grpc_python_out`.

### 4. Implement the Servicer

```python
import threading
from concurrent import futures

import grpc
import <proto_name>_pb2
import <proto_name>_pb2_grpc


class Server(<proto_name>_pb2_grpc.<ServiceName>Servicer):
    def __init__(self):
        # State storage - adapt structure to task requirements
        self._store = {}  # or whatever structure the task requires
        self._lock = threading.Lock()  # CRITICAL for thread safety

    def <MethodA>(self, request, context):
        # Access request fields: request.<field_name>
        # Return response: <proto_name>_pb2.<MethodA>Response(<field>=<value>)
        with self._lock:
            # ... state manipulation ...
            pass
        return <proto_name>_pb2.<MethodA>Response(...)

    # ... implement all RPC methods ...


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    <proto_name>_pb2_grpc.add_<ServiceName>Servicer_to_server(Server(), server)
    server.add_insecure_port('[::]:<port>')
    server.start()
    server.wait_for_termination()


if __name__ == '__main__':
    serve()
```

**Key patterns:**

- **Servicer base class:** Generated as `{ServiceName}Servicer` in `_pb2_grpc.py`
- **Registration function:** Generated as `add_{ServiceName}Servicer_to_server(servicer, server)`
- **Method signature:** `def MethodName(self, request, context):` — always two parameters
- **Thread safety:** Python gRPC uses `ThreadPoolExecutor` — multiple threads handle requests
  concurrently. ALL access to shared mutable state MUST be protected by a lock.
- **Server lifecycle:** `server.start()` is non-blocking; `server.wait_for_termination()` blocks
  the main thread so the process stays alive. Without it, the script exits immediately and the
  server dies.

### 5. State Management Patterns

The state structure depends on the task's semantics. Common patterns:

**Flat key-value (single namespace):**
```python
self._store = {}  # key -> value
```

**Namespaced key-value (isolated collections):**
```python
self._store = {}  # namespace -> {key -> value}
# Access: self._store.get(ns, {}).get(key, default)
```

**Multi-collection (related data types):**
```python
self._users = {}     # user_id -> user_data
self._sessions = {}  # session_id -> session_data
```

**Default value semantics:**
- Missing key returns a default (e.g., `0` for int, `""` for string, `False` for bool)
- Use `dict.get(key, default)` pattern
- For aggregate operations (sum, count), iterate over values with a lock held

**Delete semantics:**
- Return the removed value and a success flag
- Missing key: return `success=False, value=<default>`
- Use `dict.pop(key, None)` and check for `None`

**Conditional updates:**
- Check current value before updating
- All check-then-act must happen within a single lock acquisition

### 6. Testing Approach

Write an inline smoke test that creates a client, exercises all RPCs, and verifies responses:

```python
import grpc
import <proto_name>_pb2
import <proto_name>_pb2_grpc

channel = grpc.insecure_channel('localhost:<port>')
stub = <proto_name>_pb2_grpc.<ServiceName>Stub(channel)

# Test each RPC method
response = stub.<Method>(<proto_name>_pb2.<Method>Request(...))
assert response.<field> == expected_value

channel.close()
```

Start the server as a background process before testing:
```bash
python server.py &
sleep 2  # Wait for server to bind
# Run tests
```

## Family Variation Guide

### Variation: RPC API Structure

**More RPCs:** Add more `rpc` declarations in the service block, define corresponding
request/response messages, and implement each method in the Servicer class.

**Complex message fields:**
- Nested messages: Define the inner message, then use it as a field type
- Repeated fields: `repeated string items = 1;` — access as a Python list
- Enums: Define `enum Status { ACTIVE = 0; INACTIVE = 1; }` — use as field type
- Oneof: `oneof choice { string text = 1; int32 number = 2; }`

**Naming variations:** The service name and method names can vary. The generated Python
classes follow the pattern `{ServiceName}Servicer`, `{MethodName}Request`, `{MethodName}Response`.
Always check the generated `_pb2_grpc.py` file to confirm exact class names.

### Variation: Stateful Service Semantics

**Larger key spaces:** The nested dict pattern scales to thousands of keys. For very large
state, consider using `collections.defaultdict` to simplify initialization.

**Multiple namespaces/collections:** Use a dict of dicts, or separate dicts for each collection.
Protect all with a single lock (or use per-collection locks for finer granularity).

**Aggregate operations (sum, count, min, max):** Iterate over values within a lock:
```python
with self._lock:
    total = sum(self._store.get(ns, {}).values())
```

**Conditional updates:** Check-then-act within a single lock acquisition to avoid race conditions.

**Reset/clear operations:** Add an RPC that clears state:
```python
def Reset(self, request, context):
    with self._lock:
        self._store.clear()
    return <proto_name>_pb2.ResetResponse()
```

### Variation: Runtime Interaction Requirements

**Longer-lived servers:** The `wait_for_termination()` pattern keeps the server alive indefinitely.
For health monitoring, add a periodic health check or use gRPC's built-in health service.

**Concurrent request bursts:** The `ThreadPoolExecutor(max_workers=N)` controls concurrency.
For high load, increase `max_workers` (e.g., 50-100). The lock ensures state consistency
regardless of concurrency level.

**Startup delays/readiness:** Add a readiness check or health endpoint. The server is ready
once `server.start()` returns. If tests connect immediately, add a small sleep or retry logic
in the client.

**Multiple client channels:** Each `grpc.insecure_channel()` creates an independent connection.
The server handles all channels concurrently via the thread pool. State is shared across all
channels (it's in the Servicer instance).

## Common Pitfalls

1. **protoc import path:** Wrong `-I` flag → generated code has wrong imports → `ModuleNotFoundError`
2. **Missing lock:** Concurrent requests corrupt state → `RuntimeError: dictionary changed size during iteration`
3. **Missing `wait_for_termination()`:** Server starts but script exits immediately → server dies
4. **Wrong field numbers:** Proto field numbers must be explicit and unique → generated code won't match
5. **Version mismatch:** grpcio and grpcio-tools versions must match → version check fails
6. **Proto filename vs generated code:** Hyphens in proto filename become underscores in Python imports
7. **Default values:** Proto3 doesn't distinguish between "field not set" and "field set to default" —
   missing int32 fields are `0`, missing string fields are `""`, missing bool fields are `False`

## Adaptation Checklist for Variants

When the task varies from v01, use this checklist to identify what needs to change:

### Mapping from task.yaml to Implementation

Extract these from task.yaml and map them to your implementation:

| task.yaml specifies | Where it goes |
|---------------------|---------------|
| Service name (e.g., `KVStore`) | Proto `service` block, Python class inheritance, registration function |
| RPC methods (e.g., `Put`, `Fetch`) | Proto `rpc` declarations, Python method implementations |
| Request/response fields and numbers | Proto `message` definitions with field numbers |
| Port (e.g., `5328`) | `server.add_insecure_port('[::]:<port>')` |
| State semantics (e.g., "namespaced", "overwrite") | Python state structure and method logic |
| Default values (e.g., "returns 0 for missing") | Python `.get(key, default)` patterns |
| Proto file path (e.g., `/app/kv-store.proto`) | File creation location |
| Generated file paths (e.g., `/app/kv_store_pb2.py`) | Verify these exist after protoc |
| gRPC versions (e.g., `grpcio==1.73.0`) | `pip install` command |

### 1. Proto File Changes
- [ ] **Service name**: Change `service KVStore` → `service <NewName>`
- [ ] **RPC methods**: Add/remove/modify `rpc` declarations to match task requirements
- [ ] **Message definitions**: Update request/response messages with correct fields and field numbers
- [ ] **Field types**: Use appropriate types (string, int32, bool, nested messages, repeated fields, enums)
- [ ] **Package name**: Update `package kvstore;` if needed (affects generated code organization)

### 2. Generated Code Naming
The proto filename determines the generated Python module names:
- Proto file: `my-service.proto` → Generated: `my_service_pb2.py`, `my_service_pb2_grpc.py`
- **Rule**: Hyphens in proto filename become underscores in Python imports
- Update `import` statements in `server.py` to match the generated module names

### 3. Server Implementation Changes
- [ ] **Servicer base class**: Change `KVStoreServicer` → `<NewServiceName>Servicer`
- [ ] **Registration function**: Change `add_KVStoreServicer_to_server` → `add_<NewServiceName>Servicer_to_server`
- [ ] **Method implementations**: Implement all RPC methods defined in the proto
- [ ] **State structure**: Adapt based on task semantics (see "State Structure Decision Tree" below)
- [ ] **Port**: Change `5328` to the port specified in the task

### 4. State Structure Decision Tree

```
Does the task require isolated collections?
├─ YES → Use nested dict: {namespace → {key → value}}
│        Example: "namespaced key-value store"
│
└─ NO → Does the task require multiple related data types?
        ├─ YES → Use separate dicts: {users: {}, sessions: {}}
        │        Example: "user management with sessions"
        │
        └─ NO → Use flat dict: {key → value}
                 Example: "simple key-value cache"
```

**Additional considerations:**
- **Aggregate operations** (sum, count, min, max): Iterate over values within a lock
- **Conditional updates**: Check-then-act within a single lock acquisition
- **Default values**: Use `dict.get(key, default)` for missing keys
- **Delete semantics**: Return removed value + success flag, or default + False if missing

### 5. Testing Adaptation
- [ ] Update client stub creation to match new service name
- [ ] Test all RPC methods with valid and edge-case inputs
- [ ] Verify state persistence across multiple calls
- [ ] Test namespace isolation if applicable
- [ ] Test default value behavior for missing keys
- [ ] Test concurrent access if task requires it

## Reference Implementation

See `templates/kv-store.proto` and `templates/server.py` for a working v01 example with
namespaced integer storage, Put/Fetch/Delete/ListNamespaceTotal RPCs, and thread-safe state
management.

**Important**: These templates are v01-specific. Use the Adaptation Checklist above to modify
them for different variants. The templates demonstrate the pattern, but you must adapt the
service name, RPC methods, state structure, and port to match the task requirements.
