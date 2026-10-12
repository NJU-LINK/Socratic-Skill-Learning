---
name: kv-store-grpc
description: >
  Build a stateful Python gRPC service from a proto specification. Covers the
  full lifecycle: writing .proto files, generating Python bindings with
  grpc_tools.protoc, implementing a servicer class with in-memory state that
  persists across calls and client channels, and launching a long-lived
  insecure gRPC server on a specified port. Handles arbitrary RPC structures
  (unary methods, nested/repeated/enum fields, multiple services), varied
  stateful semantics (namespaced stores, conditional updates, aggregates,
  deletes, resets), and diverse runtime requirements (concurrency, readiness,
  sustained load).
---

# Python gRPC Stateful Service Construction

## Overview

This skill builds a real, running Python gRPC server from a task specification.
The process has six phases: (0) parse task requirements, (1) install dependencies, (2) write the .proto
file, (3) generate Python bindings, (4) implement the servicer with correct
state semantics, and (5) launch the server and leave it running.

## Phase 0: Parse Task Requirements

**Before writing any code, extract all concrete parameters from the task instruction.**

Create a checklist and fill it in by reading the task carefully:

- [ ] **Proto file**: What is the exact file path? (e.g., `/app/kv-store.proto`)
- [ ] **Service name**: What is the service called? (e.g., `KVStore`)
- [ ] **RPC methods**: List each method with request/response message names
- [ ] **Message fields**: For each message, list field names, types, and field numbers
- [ ] **Generated files**: What are the exact paths for `_pb2.py` and `_pb2_grpc.py`?
- [ ] **Server file**: What is the exact file path? (e.g., `/app/server.py`)
- [ ] **Server class name**: What must the servicer class be named? (e.g., `Server`)
- [ ] **Port number**: What port must the server listen on? (e.g., `5328`)
- [ ] **State semantics**: 
  - What is the data model? (flat KV, namespaced, multi-collection?)
  - What are the default values for missing keys/namespaces?
  - What is the overwrite behavior?
  - What does delete return? (success flag, removed value?)
  - What do aggregate operations return? (sum, count, list?)
  - Are there any conditional update rules?
- [ ] **Dependencies**: What versions of `grpcio` and `grpcio-tools` are required?

**Do not proceed until you have extracted all parameters.** If the task is ambiguous, re-read it carefully. The task instruction is the authoritative source for all these details — they vary across variants and are not fixed.

## Phase 1: Install Dependencies

Install the exact versions of `grpcio` and `grpcio-tools` specified in the
task. These must match because the generated code embeds a version check.

```bash
pip install grpcio==<VERSION> grpcio-tools==<VERSION>
```

If no version is specified, use the latest compatible pair. Both packages must
be the same version.

**Note:** In some environments (particularly Python 3.11+ with externally managed packages), you may need `pip install --break-system-packages` to install system-wide. If you see an "externally-managed-environment" error, add that flag.

## Phase 2: Write the .proto File

### Proto Syntax Rules

- Use `syntax = "proto3";`
- Declare a `package` (any valid name; it becomes part of the RPC method path)
- Define the `service` block with all required RPC methods
- Define all `message` types referenced by the RPCs

### Message Field Mapping

For each message, translate the task specification into proto fields:

| Task specifies | Proto type | Notes |
|---|---|---|
| string field N | `string name = N;` | Field numbers start at 1, must be sequential and unique within a message |
| int32 field N | `int32 name = N;` | Use `int32` unless the task says otherwise |
| int64 field N | `int64 name = N;` | For larger integers |
| bool field N | `bool name = N;` | |
| float/double field N | `float name = N;` / `double name = N;` | |
| repeated X field N | `repeated X name = N;` | For list/array fields |
| nested message | Define inner `message` and reference by name | |
| enum field N | Define `enum` type, use as field type | First enum value must be 0 |

### RPC Method Mapping

Each unary RPC in the task becomes:
```protobuf
rpc MethodName(RequestMessage) returns (ResponseMessage);
```

**Critical:** Use the exact names from the task specification for services, methods, messages, and fields. Naming variations are a spec-declared axis—do not normalize or rename. If the task says `FetchData`, use `FetchData`, not `Fetch` or `GetData`.

### File Naming

The proto file name determines the generated Python module names. The proto
file `foo-bar.proto` generates `foo_bar_pb2.py` and `foo_bar_pb2_grpc.py`
(hyphens become underscores). The task may specify exact file paths—follow them.

**Critical naming chain:** The proto filename → generated module names → import statements in server.py must all be consistent:
- Proto file: `my-service.proto`
- Generated: `my_service_pb2.py`, `my_service_pb2_grpc.py`
- Server imports: `import my_service_pb2` and `import my_service_pb2_grpc`

If you get the import names wrong, the server will fail to start. Always verify the generated filenames and use the exact module names (with underscores) in your imports.

## Phase 3: Generate Python Bindings

```bash
cd <WORK_DIR>
python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. <proto_file>
```

Key details:
- `-I.` sets the import path to the current directory
- `--python_out=.` generates the `_pb2.py` message classes
- `--grpc_python_out=.` generates the `_pb2_grpc.py` service stubs and servicer base
- The generated file names use underscores for hyphens in the proto filename
- **Verify both output files exist after generation**
- **Follow exact paths from the task**: If the task specifies output locations (e.g., "Generate `/app/kv_store_pb2.py`"), ensure the generated files end up at those exact paths. Adjust `--python_out` and `--grpc_python_out` accordingly.

### Verify Generated Class Names

After generation, inspect the `_pb2_grpc.py` file to confirm the exact class names:
```bash
grep -E "class |def add_" <module>_pb2_grpc.py
```

This reveals:
- `<ServiceName>Stub`: Client stub class
- `<ServiceName>Servicer`: Base class to extend
- `add_<ServiceName>Servicer_to_server`: Registration function

Use these exact names in your server implementation. Do not assume names—verify them.

### Understanding Generated Classes

The `_pb2_grpc.py` file contains:
- `<ServiceName>Stub`: Client-side stub (takes a channel in constructor)
- `<ServiceName>Servicer`: Base class to extend for server implementation
- `add_<ServiceName>Servicer_to_server(servicer, server)`: Registration function

## Phase 4: Implement the Servicer

### Class Structure

```python
import grpc
from concurrent import futures
import threading
import <module>_pb2
import <module>_pb2_grpc

class Server(<module>_pb2_grpc.<ServiceName>Servicer):
    def __init__(self):
        self._lock = threading.Lock()
        # Initialize in-memory state based on task requirements
        self._state = ...

    def <MethodName>(self, request, context):
        with self._lock:
            # Access request fields as attributes: request.field_name
            # Perform state operations inside the lock
            ...
        # Return response using generated class: <module>_pb2.<ResponseMessage>(...)
        ...
```

### State Management Patterns

Choose data structures based on the task's state semantics:

**Flat key-value store:**
```python
self._store = {}  # key -> value
```

**Namespaced key-value store:**
```python
self._store = {}  # namespace -> {key -> value}
```

**Multiple collections / typed data:**
```python
self._collections = {
    'collection_a': {},
    'collection_b': [],
}
```

### Common State Semantics

| Requirement | Implementation |
|---|---|
| Default value for missing key | `dict.get(key, default)` |
| Overwrite on set | Direct assignment `d[k] = v` |
| Delete with return | `d.pop(k, sentinel)` then check sentinel |
| Conditional update | Check condition before modifying (e.g., only update if new > old) |
| Aggregate (sum, count) | `sum(d.values())`, `len(d)` |
| Multi-key operations | Iterate over relevant keys, return list/dict |
| Namespace isolation | Separate dicts per namespace |
| Reset/clear | `d.clear()` or `del d[k]` in a loop |

### Complex Message Construction

When the proto defines nested messages, repeated fields, or enums, use these construction patterns:

**Nested messages:**
```python
# Proto:
# message Item { string name = 1; int32 value = 2; }
# message Container { Item primary = 1; }

# Construct nested message first, then pass to parent
item = module_pb2.Item(name="foo", value=10)
resp = module_pb2.Container(primary=item)

# Or nest directly in constructor
resp = module_pb2.Container(
    primary=module_pb2.Item(name="foo", value=10)
)
```

**Repeated fields:**
```python
# Proto:
# message ListResponse { repeated Item items = 1; }

# Build a Python list, pass to constructor
items = [
    module_pb2.Item(name="a", value=1),
    module_pb2.Item(name="b", value=2),
]
return module_pb2.ListResponse(items=items)
```

Pass a Python list directly to the repeated field in the constructor. Avoid `.append()` or `.extend()` after construction when possible—constructor assignment is cleaner and more idiomatic.

**Enums:**
```python
# Proto:
# enum Status { UNKNOWN = 0; ACTIVE = 1; DELETED = 2; }
# message Item { Status status = 1; }

# Access enum values as module attributes
item = module_pb2.Item(status=module_pb2.ACTIVE)

# Compare enum values
if item.status == module_pb2.DELETED:
    ...
```

**Critical rule for proto3 enums:** The first enum value must be 0. This is not optional—it's required by the proto3 specification because 0 is the default value for all fields. If your task defines an enum, ensure the first value is named something like `UNKNOWN`, `UNSPECIFIED`, or `DEFAULT` and has value 0.

### Thread Safety

**Always use locking for state operations.** The gRPC server uses a thread
pool, and even though CPython has a GIL, the GIL only protects individual
bytecode instructions—not multi-step logical operations.

**The race condition pattern:**
```python
# WRONG: check-then-act is not atomic
if key in self._store:          # CHECK (bytecode 1)
    value = self._store.pop(key) # ACT (bytecode 2) - another thread can intervene
```

Between the check and the act, another thread can modify the state. Thread A
checks "key exists" → True. Thread B checks "key exists" → True and pops it.
Thread A now pops a missing key → `KeyError` → gRPC returns UNIMPLEMENTED.

**The correct pattern—lock around all compound state operations:**
```python
import threading

class Server(...):
    def __init__(self):
        self._lock = threading.Lock()
        self._store = {}

    def Put(self, request, context):
        with self._lock:
            if request.namespace not in self._store:
                self._store[request.namespace] = {}
            self._store[request.namespace][request.key] = request.value
        return kv_store_pb2.PutResponse(value=request.value)

    def Delete(self, request, context):
        with self._lock:
            ns_dict = self._store.get(request.namespace)
            if ns_dict and request.key in ns_dict:
                value = ns_dict.pop(request.key)
                return kv_store_pb2.DeleteResponse(success=True, value=value)
        return kv_store_pb2.DeleteResponse(success=False, value=0)
```

**Rule:** Any time you read state, make a decision based on it, and then write
state, you need a lock. This includes:
- Check-then-act (if key exists, delete it)
- Read-modify-write (get value, increment, set value)
- Conditional creation (if namespace doesn't exist, create it)

Lock even for "simple" operations. The overhead is negligible, and it makes
your implementation robust across all concurrency scenarios without needing to
reason about which specific variants require it.

### gRPC Error Handling

If the task requires returning specific error codes (e.g., NOT_FOUND, INVALID_ARGUMENT), use the context object:

```python
def Fetch(self, request, context):
    with self._lock:
        value = self._store.get(request.key)
    if value is None:
        context.set_code(grpc.StatusCode.NOT_FOUND)
        context.set_details(f'Key {request.key} not found')
        return module_pb2.FetchResponse()  # Return empty response
    return module_pb2.FetchResponse(value=value)
```

**Key points:**
- Set the code and details on the context before returning
- Still return a response object (can be empty/default)
- Common status codes: `NOT_FOUND`, `INVALID_ARGUMENT`, `ALREADY_EXISTS`, `INTERNAL`
- If the task doesn't specify error handling, use the default behavior (return default values)

## Phase 5: Launch the Server

### Standard Server Startup

```python
def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    <module>_pb2_grpc.add_<Service>Servicer_to_server(Server(), server)
    server.add_insecure_port('[::]:<PORT>')
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()
```

Key details:
- `futures.ThreadPoolExecutor(max_workers=10)`: Adjust workers based on expected concurrency
- `add_insecure_port('[::]:<PORT>')`: `[::]` binds to all interfaces (IPv4 + IPv6)
- `server.start()`: Non-blocking; starts serving in background threads
- `server.wait_for_termination()`: Blocks the main thread until the server stops
- The server must be started as a background process and left running

### Starting the Server

```bash
cd <WORK_DIR> && python3 server.py &
sleep 2  # Allow time for server startup
```

### Readiness Check

After starting, verify the server is accepting connections:

```python
import grpc
channel = grpc.insecure_channel('localhost:<PORT>')
grpc.channel_ready_future(channel).result(timeout=5)
```

Or simply make a test RPC call and check for a response.

## Verification Checklist

After implementation, verify:

1. **Proto correctness**: All messages have correct field names, types, and numbers
2. **Generation success**: Both `_pb2.py` and `_pb2_grpc.py` exist
3. **Import chain**: `server.py` can import the generated modules without errors
4. **Server startup**: Process is running and port is bound
5. **Each RPC method**: Test with a client stub for:
   - Normal operation (happy path)
   - Edge cases (missing keys, empty collections, default values)
   - State persistence across multiple calls
   - Namespace/collection isolation if applicable
6. **State semantics**: Verify the specific behaviors required:
   - Overwrite behavior
   - Default values for missing data
   - Delete semantics (return value, success flag)
   - Aggregate computations
   - Cross-call state persistence

## Variation Handling

### When RPC Structure Varies

- More RPCs: Add each to the service block and implement each method
- Complex messages: Use nested messages, repeated fields, enums as needed
- Multiple services: Define each service separately; generate one `_pb2_grpc.py` with all servicers
- Streaming RPCs: Use `stream` keyword; implement generator-based handlers

### When State Semantics Varies

- Parse the task description carefully for the exact data model
- Map each RPC to its read/write semantics on the state
- Pay attention to: default values, error conditions, return values for edge cases
- Consider whether state needs to survive server restarts (usually not for in-memory stores)

### When Runtime Requirements Vary

- Higher concurrency: Increase `max_workers`, add thread safety
- Readiness gates: Add health check RPC or startup delay
- Long-lived tests: Ensure no resource leaks, handle graceful shutdown
- Multiple channels: State must persist regardless of which channel connects
