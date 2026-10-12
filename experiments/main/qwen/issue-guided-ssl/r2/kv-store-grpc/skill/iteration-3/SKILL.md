---
name: kv-store-grpc
description: >
  Build and deploy a real Python gRPC stateful service from a specification.
  Covers proto authoring, code generation, server implementation with
  in-memory state management, and server lifecycle. Handles varying RPC
  interface complexity, stateful semantics, and runtime requirements.
---

# gRPC Stateful Service Builder

## Overview

This skill builds a real Python gRPC server from a task specification. The server
exposes defined RPC methods backed by in-memory state that persists across calls
and client channels. The procedure generalizes across varying API structures,
state semantics, and runtime requirements.

## Procedure

### Step 1: Install Dependencies

```bash
pip install grpcio==1.73.0 grpcio-tools==1.73.0
```

Always pin versions as specified in the task. If no version is specified, use
`grpcio>=1.50.0` and `grpcio-tools>=1.50.0`.

### Step 2: Author the Proto File

Create the `.proto` file at the path specified by the task (typically `/app/<name>.proto`).

**Proto authoring rules:**

- Use `syntax = "proto3";`
- Declare a `package` name (lowercase, no underscores required)
- Define the `service` block with all required RPCs
- Each RPC: `rpc MethodName(RequestMessage) returns (ResponseMessage);`
- All RPCs in this family are **unary** (single request, single response)

**Message field mapping from spec:**

| Spec says | Proto type | Notes |
|-----------|-----------|-------|
| "string field N" | `string name = N;` | Field numbers are 1-indexed, must match spec exactly |
| "int32 field N" | `int32 name = N;` | Use `int32` unless spec says otherwise |
| "bool field N" | `bool name = N;` | |
| "repeated X" | `repeated X name = N;` | For list/array fields |
| "enum" | Define `enum` type, use as field type | |
| nested message | Define separate `message`, use as field type | |

**Key proto pitfalls:**
- Field numbers must be unique within a message and match the spec exactly
- Message names must match what the task specifies (used in generated code)
- The service name must match exactly (used in generated servicer base class)

**Complex proto types with examples:**

*Nested messages:*
```protobuf
message Address {
  string street = 1;
  string city = 2;
}

message Person {
  string name = 1;
  Address address = 2;  // Nested message field
}
```
Python access: `request.address.street`, `request.address.city`

*Repeated fields (lists):*
```protobuf
message ItemList {
  repeated string items = 1;  // List of strings
  repeated int32 numbers = 2; // List of integers
}
```
Python access: `request.items` is a list, iterate with `for item in request.items:`

*Enums:*
```protobuf
enum Status {
  UNKNOWN = 0;  // First value must be 0
  ACTIVE = 1;
  INACTIVE = 2;
}

message UserRequest {
  string user_id = 1;
  Status status = 2;  // Enum field
}
```
Python access: `request.status` is an integer, compare with `Status.ACTIVE` (import enum from generated module)

### Step 3: Generate Python Bindings

```bash
python -m grpc_tools.protoc \
  -I<proto_dir> \
  --python_out=<output_dir> \
  --grpc_python_out=<output_dir> \
  <proto_dir>/<filename>.proto
```

**Critical details:**
- `-I` flag specifies the import search path (usually the directory containing the proto)
- The proto filename uses hyphens (e.g., `kv-store.proto`) but generated Python files
  use underscores (e.g., `kv_store_pb2.py`, `kv_store_pb2_grpc.py`)
- The generated `_pb2.py` contains message classes
- The generated `_pb2_grpc.py` contains stub and servicer classes
- Both files are generated in the same output directory

**Import pattern in server code:**
```python
import <module_name>_pb2
import <module_name>_pb2_grpc
```
Where `<module_name>` is the proto filename with hyphens replaced by underscores
and `.proto` removed.

### Step 4: Implement the Server

Create `server.py` with:

```python
import grpc
from concurrent import futures
import <module>_pb2
import <module>_pb2_grpc


class Server(<module>_pb2_grpc.<ServiceName>Servicer):
    def __init__(self):
        # Initialize in-memory state based on spec semantics
        self._state = ...

    def <RpcMethod>(self, request, context):
        # Access request fields as attributes: request.field_name
        # Return response using generated class:
        return <module>_pb2.<ResponseMessage>(field1=val1, field2=val2)


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    <module>_pb2_grpc.add_<ServiceName>Servicer_to_server(Server(), server)
    server.add_insecure_port('[::]:<PORT>')
    server.start()
    server.wait_for_termination()


if __name__ == '__main__':
    serve()
```

**State management patterns:**

| Spec semantics | Data structure | Notes |
|---------------|---------------|-------|
| Flat key-value store | `dict[str, ValueType]` | Simple mapping |
| Namespaced key-value | `defaultdict(dict)` or `dict[str, dict[str, ValueType]]` | Outer key = namespace |
| Multi-collection | Multiple dicts or a dict of dicts | Map each collection to a field |
| Ordered/sequential | `list` or `collections.deque` | When order matters |
| Aggregate/counter | `dict[str, int]` with sum operations | Compute on read |

**Default value handling:**
- When spec says "returns 0 for missing" → use `dict.get(key, 0)`
- When spec says "returns false for missing" → check `key in dict` first
- Always match the exact default semantics from the spec

**RPC method implementation checklist:**
1. Read all fields from `request` object
2. Apply the specified semantics (read/write/delete/aggregate)
3. Update state if it's a write operation
4. Construct and return the response with all required fields

**Constructing responses with complex types:**

*Nested messages in response:*
```python
# If response has nested message field
address = kv_store_pb2.Address(street="123 Main", city="NYC")
return kv_store_pb2.PersonResponse(name="John", address=address)
```

*Repeated fields in response:*
```python
# If response has repeated field
return kv_store_pb2.ItemListResponse(items=["a", "b", "c"], numbers=[1, 2, 3])
# Or build incrementally:
resp = kv_store_pb2.ItemListResponse()
resp.items.append("a")
resp.items.append("b")
resp.numbers.extend([1, 2, 3])
return resp
```

*Enum values in response:*
```python
# Set enum field using enum constant
return kv_store_pb2.StatusResponse(status=kv_store_pb2.ACTIVE)
# Or use integer value
return kv_store_pb2.StatusResponse(status=1)  # ACTIVE
```

**Compound state operations with proper locking:**

For read-modify-write operations, use locks to ensure atomicity:
```python
def IncrementCounter(self, request, context):
    key = request.key
    amount = request.amount
    with self._lock:
        # Read current value
        current = self._counters.get(key, 0)
        # Modify
        new_value = current + amount
        # Write back
        self._counters[key] = new_value
    return kv_store_pb2.CounterResponse(value=new_value)
```

For conditional updates (e.g., "update only if current value matches expected"):
```python
def ConditionalUpdate(self, request, context):
    key = request.key
    expected = request.expected
    new_value = request.new_value
    with self._lock:
        current = self._store.get(key)
        if current == expected:
            self._store[key] = new_value
            return kv_store_pb2.UpdateResponse(success=True, value=new_value)
        else:
            return kv_store_pb2.UpdateResponse(success=False, value=current)
```

### Step 5: Start the Server

**Critical**: You must `cd` to the directory containing the generated `_pb2.py` files before starting the server, otherwise imports will fail.

```bash
cd /app && python server.py &
```

**Robust readiness check** (preferred over `sleep`):
```bash
# Wait for port to be ready with retry loop
for i in {1..10}; do
    if python3 -c "import socket; s=socket.socket(); s.settimeout(1); s.connect(('localhost',<PORT>)); s.close()" 2>/dev/null; then
        echo "Server ready on port <PORT>"
        break
    fi
    sleep 1
done
```

**Server lifecycle requirements:**
- The server must run as a **long-lived background process**
- Use `&` to background it, or `nohup python server.py &` for extra safety
- **Do NOT use `ps aux` to verify** - `ps` is often unavailable in containers
- Use the port-based readiness check above instead of `sleep 2`
- Verify with a test RPC call before declaring success (see Step 6)
- The server must survive the test execution window

**Startup failure diagnosis:**
- If the server doesn't start, check stderr: `python server.py 2>&1 | head -20`
- Common failures: ImportError (wrong directory), port already in use, syntax errors
- Ensure you're in the correct directory with `pwd` before starting

**Concurrency considerations:**
- `ThreadPoolExecutor(max_workers=10)` handles concurrent RPCs
- For thread-safe state access with complex semantics, use `threading.Lock`:
  ```python
  import threading
  class Server(...):
      def __init__(self):
          self._lock = threading.Lock()
          self._state = ...
      def SomeMethod(self, request, context):
          with self._lock:
              # state access/modification
  ```
- For simple dict operations in CPython, the GIL provides basic safety,
  but explicit locking is safer for compound operations (read-modify-write)

### Step 6: Verify

Write a quick verification script:
```python
import grpc
import <module>_pb2
import <module>_pb2_grpc

channel = grpc.insecure_channel('localhost:<PORT>')
stub = <module>_pb2_grpc.<ServiceName>Stub(channel)
# Call each RPC and verify expected behavior
```

## Variation Handling

### Varying RPC API Structure
- More RPCs: just add more `rpc` declarations and implement each method
- Nested messages: define inner messages, use as field types
- Repeated fields: use `repeated` keyword, access as Python lists
- Enums: define `enum` type, use in messages, access as integer constants
- Different naming: follow the spec exactly; generated code uses the spec names

### Varying State Semantics
- Different operations: implement each according to spec (conditional updates, 
  multi-key ops, batch operations)
- Different defaults: match exactly what spec says (0, empty string, false, etc.)
- Deletes/resets: clear appropriate state entries
- Aggregates: compute from current state on each call (don't cache unless spec says to)

### Varying Runtime Requirements
- Longer-lived: ensure `wait_for_termination()` is used (blocks forever)
- High concurrency: increase `max_workers` in ThreadPoolExecutor
- Readiness: add a health check RPC or verify with a test call after startup
- Multiple channels: state is in the Server instance, shared across all channels
  connecting to the same port

## Common Pitfalls

1. **Proto filename vs module name**: `kv-store.proto` → `kv_store_pb2.py` (hyphens become underscores)
2. **protoc -I path**: Must point to directory containing the proto file
3. **Server not running**: Tests connect to a real gRPC server; it must be started and left running
4. **State not persisting**: State lives in the Server instance; don't recreate it per-request
5. **Wrong port**: Must match the port specified in the task exactly
6. **Missing fields in response**: All fields in the response message must be set
7. **Namespace isolation**: Different namespaces must not share state
8. **Wrong working directory**: Must `cd` to the directory with generated `_pb2.py` files before running server, otherwise `ImportError`
9. **Using `ps` to verify**: `ps` command is often unavailable in containers; use port-based readiness check or gRPC test call instead
10. **Fragile `sleep`**: Use port-based readiness loop instead of `sleep 2` for reliable startup detection
