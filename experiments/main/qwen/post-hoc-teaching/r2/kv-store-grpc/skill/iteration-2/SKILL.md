---
name: kv-store-grpc
description: >
  Build and deploy a stateful Python gRPC service from a task specification.
  Covers the full pipeline: installing grpcio/grpcio-tools, authoring a .proto
  file with arbitrary service/RPC/message definitions, generating Python
  bindings, implementing a thread-safe in-memory servicer with correct state
  semantics, and launching the server on the specified port. Handles variation
  in RPC structure (method count, field types including nested/repeated/enum),
  stateful semantics (namespaces, aggregates, conditional operations, multi-key
  logic), and runtime requirements (concurrency, reliability, port).
---

# Python gRPC Stateful Service Builder

## Overview

This skill builds a running Python gRPC server from a task specification. The
specification defines a protobuf service with unary RPCs, message types, and
in-memory stateful behavior. The output is a live gRPC server ready to accept
client connections.

## Step-by-Step Procedure

### Step 1: Install Dependencies

```bash
pip install grpcio==1.73.0 grpcio-tools==1.73.0
```

Always install both packages at the pinned version. The grpcio-tools package
provides the `protoc` plugin needed for code generation. If the task specifies
different versions, use those instead.

### Step 2: Parse the Task Specification

Extract these elements from the task instruction:

| Element | What to look for | Example |
|---------|-----------------|---------|
| Proto filename | The `.proto` file path | `/app/kv-store.proto` |
| Package name | Protobuf package declaration | `kvstore` |
| Service name | The `service` block name | `KVStore` |
| RPC methods | Each `rpc Name(Request) returns (Response)` | `Put`, `Fetch`, `Delete` |
| Message types | All `message` definitions with fields | `PutRequest`, `PutResponse` |
| Field types | Protobuf types: `string`, `int32`, `int64`, `bool`, `float`, `double`, `bytes`, enums, nested messages, `repeated` fields | `string namespace = 1` |
| Port number | The port the server must listen on | `5328` |
| Server class name | The Python class implementing the servicer | `Server` |
| Server file path | Where to write server.py | `/app/server.py` |
| State semantics | How in-memory state behaves across calls | "overwrite-on-set", "default 0 for missing", "sum values" |
| Namespace/isolation | Whether state is partitioned | "namespaces are isolated" |

**CRITICAL**: All paths, names, and port numbers come from the task specification, not from this skill. The examples in this skill (like `/app/kv-store.proto`, port `5328`, class `Server`) are from the v01 variant. Always use the exact values specified in your task.

### Step 3: Write the .proto File

#### Proto File Structure

```protobuf
syntax = "proto3";

package <package_name>;

service <ServiceName> {
  rpc <Method1>(<Request1>) returns (<Response1>);
  rpc <Method2>(<Request2>) returns (<Response2>);
  // ... more RPCs
}

message <Request1> {
  <type> <field_name> = <field_number>;
  // ... more fields
}

message <Response1> {
  <type> <field_name> = <field_number>;
  // ... more fields
}
// ... more messages
```

#### Critical Rules for Proto Files

1. **Field numbers** must be unique within a message and start from 1. Use exactly the numbers specified in the task.
2. **Message names** must match exactly what the RPC definitions reference.
3. **Package name** is typically a lowercase version of the service name, but use whatever the task specifies. If unspecified, use a reasonable lowercase derivation.
4. **Proto3 defaults**: all scalar fields default to their zero value (0 for ints, "" for strings, false for bools). This is important for understanding default behavior.

#### Protobuf Field Type Mapping

| Protobuf Type | Python Type (accessed from message) |
|---------------|-------------------------------------|
| `string` | `str` |
| `int32`, `int64`, `uint32`, `uint64`, `sint32`, `sint64`, `fixed32`, `fixed64` | `int` |
| `float`, `double` | `float` |
| `bool` | `bool` |
| `bytes` | `bytes` |
| `enum` | `int` (the enum value number) |
| nested `Message` | sub-message instance |
| `repeated <type>` | `RepeatedScalarContainer` (list-like) |
| `repeated Message` | `RepeatedCompositeContainer` (list-like) |
| `map<K,V>` | dict-like |

#### Handling Enums

```protobuf
enum Status {
  UNKNOWN = 0;   // First value MUST be 0 in proto3
  ACTIVE = 1;
  INACTIVE = 2;
}
```

In Python, enum fields are accessed as integers. Use the generated enum constants for comparison:
```python
if request.status == kv_store_pb2.ACTIVE:
    ...
```

#### Handling Nested Messages

```protobuf
message Inner {
  string value = 1;
}
message Outer {
  Inner inner = 1;
  string name = 2;
}
```

Access in Python: `request.inner.value`

#### Handling Repeated Fields

```protobuf
message Items {
  repeated string names = 1;
  repeated ItemDetail details = 2;
}
```

Access in Python: iterate like a list, use `.append()` to add when constructing responses.

#### Handling Map Fields

```protobuf
message Config {
  map<string, int32> settings = 1;
}
```

Access in Python: dict-like interface.

### Step 4: Generate Python Bindings

```bash
cd /app
python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. <proto_filename>.proto
```

#### Generated File Naming Convention

The generated Python files follow a strict convention: **hyphens in the proto filename become underscores** in the generated Python module names.

| Proto filename | Generated files |
|---------------|-----------------|
| `kv-store.proto` | `kv_store_pb2.py`, `kv_store_pb2_grpc.py` |
| `my_service.proto` | `my_service_pb2.py`, `my_service_pb2_grpc.py` |
| `data-store-v2.proto` | `data_store_v2_pb2.py`, `data_store_v2_pb2_grpc.py` |

This is critical: the import statements in server.py must use the underscore version.

#### What Gets Generated

- `<name>_pb2.py`: Message classes with serialization/deserialization
- `<name>_pb2_grpc.py`: Stub (client), Servicer (base class to inherit), and `add_<ServiceName>Servicer_to_server()` function

### Step 5: Implement the Servicer

#### Import Pattern

```python
import grpc
from concurrent import futures
import threading
import <generated_module_name>_pb2
import <generated_module_name>_pb2_grpc
```

#### Class Structure

```python
class <ServerClassName>(<generated_module_name>_pb2_grpc.<ServiceName>Servicer):
    def __init__(self):
        self._lock = threading.Lock()
        # Initialize state data structures based on task requirements
        self._state = {}

    def <MethodName>(self, request, context):
        with self._lock:
            # Access request fields: request.<field_name>
            # Implement business logic
            # Return response: <generated_module_name>_pb2.<ResponseMessage>(field1=val1, ...)
            pass
```

#### State Management Patterns

**Thread Safety**: Always use `threading.Lock()` to protect shared state. The gRPC server uses a thread pool, so multiple RPCs can execute concurrently.

**Lock Granularity**: For most tasks, a single global lock is sufficient and simplest. For variants with very high concurrency requirements (hundreds of simultaneous requests), consider per-namespace or per-collection locks to reduce contention. However, start with a single lock unless performance testing shows it's a bottleneck.

**Common State Patterns**:

1. **Simple key-value store**:
   ```python
   self._data = {}  # {key: value}
   ```

2. **Namespaced key-value store**:
   ```python
   self._namespaces = {}  # {namespace: {key: value}}
   # Always auto-create namespace on access:
   def _get_ns(self, ns_name):
       if ns_name not in self._namespaces:
           self._namespaces[ns_name] = {}
       return self._namespaces[ns_name]
   ```

3. **Multi-collection store**:
   ```python
   self._collections = {
       'collection_a': {},
       'collection_b': [],
   }
   ```

4. **Counter/accumulator**:
   ```python
   self._counters = {}  # {key: int}
   # Increment: self._counters[key] = self._counters.get(key, 0) + 1
   ```

#### Implementing Complex State Operations

Variants may require more sophisticated state operations beyond simple get/set:

**Conditional updates** (e.g., "only update if current value is less than new value"):
```python
def ConditionalPut(self, request, context):
    with self._lock:
        current = self._data.get(request.key, 0)
        if request.value > current:  # condition check
            self._data[request.key] = request.value
            return module_pb2.Response(updated=True, value=request.value)
        return module_pb2.Response(updated=False, value=current)
```

**Multi-key operations** (e.g., "transfer value from key A to key B"):
```python
def Transfer(self, request, context):
    with self._lock:  # single lock covers all keys atomically
        src_val = self._data.get(request.source_key, 0)
        if src_val < request.amount:
            return module_pb2.Response(success=False)
        self._data[request.source_key] = src_val - request.amount
        self._data[request.dest_key] = self._data.get(request.dest_key, 0) + request.amount
        return module_pb2.Response(success=True)
```

**Reset/clear operations**:
```python
def ResetNamespace(self, request, context):
    with self._lock:
        if request.namespace in self._namespaces:
            del self._namespaces[request.namespace]
        return module_pb2.Response(success=True)
```

**Aggregate reads with filtering** (e.g., "sum only values above a threshold"):
```python
def FilteredTotal(self, request, context):
    with self._lock:
        ns = self._get_ns(request.namespace)
        total = sum(v for v in ns.values() if v >= request.min_value)
        return module_pb2.Response(total=total)
```

#### Default Value Semantics

- For `int32` fields: proto3 default is `0`
- For `string` fields: proto3 default is `""`
- For `bool` fields: proto3 default is `false`
- For missing keys in a dict: use `.get(key, default_value)` pattern
- The task specification defines what "missing" means — it could be 0, empty string, empty list, etc.

#### Response Construction

Always construct response objects using the generated message class:
```python
return <module>_pb2.<ResponseMessage>(field1=value1, field2=value2)
```

All fields not explicitly set will get their proto3 default values.

### Step 6: Server Launch

```python
def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    <module>_pb2_grpc.add_<ServiceName>Servicer_to_server(<ServerClassName>(), server)
    port = server.add_insecure_port('[::]:<port>')
    if port == 0:
        raise RuntimeError('Failed to bind to port <port> — is another server already running?')
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()
```

**CRITICAL**: `add_insecure_port()` returns `0` on failure instead of raising an exception. Without the `if port == 0` check, the server will start successfully but listen on nothing, while a stale server on the same port silently handles (and rejects) your RPCs.

#### Key Points for Server Launch

1. **`max_workers`**: Use at least 10 for concurrent request handling. For heavy concurrency requirements, increase to 50 or more.
2. **`[::]:<port>`**: Listens on all interfaces (IPv4 and IPv6). Use the exact port from the task specification.
3. **`add_insecure_port` returns int**: Returns the bound port on success, **0 on failure**. Always check for 0 and raise immediately — this is the single most common cause of silent server failures.
4. **`wait_for_termination()`**: Blocks the main thread, keeping the server alive.
5. **Start as background process**: Launch with `&` and verify it's running:
   ```bash
   cd /app && python3 server.py > /tmp/server.log 2>&1 &
   sleep 2
   # Check server.log for RuntimeError about port binding
   cat /tmp/server.log
   ```

### Step 7: Verification

After starting the server, verify it is **your** server (not a stale one from a previous run) by calling a real RPC method. `channel_ready_future` only proves *something* is listening — it does not prove the correct service is registered.

```python
import grpc
import <module>_pb2
import <module>_pb2_grpc

channel = grpc.insecure_channel('localhost:<port>')
stub = <module>_pb2_grpc.<ServiceName>Stub(channel)

# Call the simplest RPC with trivial inputs to confirm YOUR service is responding.
# If a stale server from a different task is on this port, this will raise
# UNIMPLEMENTED / "Method not found!" — immediately revealing the conflict.
resp = stub.<SimplestMethod>(<SimplestRequest>())
print(f'Server verified: {resp}')

# Then test each RPC method with basic inputs
# Verify responses match expected semantics
```

### Step 8: Test Edge Cases

Variants with complex state semantics often have subtle edge cases. Test these boundary conditions:

**Missing/absent data**:
- Fetch a key that doesn't exist → should return the specified default (often 0)
- Delete a key that doesn't exist → should return success=false with default value
- Aggregate operation on empty/absent namespace → should return 0 or empty result

**State transitions**:
- Overwrite an existing key → should update the value
- Delete then fetch → should return default
- Multiple operations on the same key in sequence

**Namespace isolation** (if applicable):
- Operations in namespace A should not affect namespace B
- Aggregate operations should only include the specified namespace

**Concurrent access** (if high concurrency is required):
- Multiple simultaneous writes to the same key
- Read-while-write scenarios
- Ensure no race conditions or data corruption

## Server Lifecycle Management

### Ensuring Clean Startup

Before starting a new server, always ensure no previous server is occupying the
target port. Background server processes from earlier steps can persist and
cause "address already in use" errors or, worse, silently serve stale code.

```bash
# Kill any existing server processes
pkill -f "python3 server.py" 2>/dev/null
sleep 2

# Verify port is free
python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
result = s.connect_ex(('localhost', PORT))
s.close()
print('FREE' if result != 0 else 'IN USE')
"
```

### Starting the Server Reliably

```bash
cd /app && python3 server.py > /tmp/server.log 2>&1 &
sleep 2

# Check for startup errors first
cat /tmp/server.log

# Then verify YOUR server is responding (not a stale one)
python3 -c "
import grpc
import <module>_pb2
import <module>_pb2_grpc
ch = grpc.insecure_channel('localhost:PORT')
stub = <module>_pb2_grpc.<ServiceName>Stub(ch)
# Call the simplest RPC to confirm correct service is registered
stub.<SimplestMethod>(<SimplestRequest>())
print('Server verified and ready')
"
```

If `server.log` contains errors, the server failed to start — check for import
errors, port conflicts, or proto generation issues. If the verification RPC fails
with UNIMPLEMENTED, a stale server from a previous run is occupying the port.

## Common Pitfalls and Solutions

### 1. Proto filename vs import name mismatch
- Proto file: `my-service.proto` → Import: `import my_service_pb2`
- Hyphens become underscores in Python module names

### 2. Forgetting thread safety
- The gRPC server uses ThreadPoolExecutor → multiple threads access state concurrently
- Always wrap state mutations in `with self._lock:`

### 3. Wrong default values
- Proto3 scalars default to zero values (0, "", false)
- But application-level defaults may differ (e.g., "Fetch returns 0 for missing key" means the application returns 0, which happens to match proto3 default)
- Always check: does the task specify explicit default behavior for missing/absent data?

### 4. Namespace isolation
- If the task mentions namespaces, ensure state is properly partitioned
- Operations in one namespace must not affect another

### 5. Aggregate operations
- For "sum", "count", "average" operations, always compute from current state
- Handle empty/absent collections gracefully (return 0 or appropriate default)

### 6. Delete semantics
- Track whether the key existed before deletion
- Return the deleted value if it existed, or a default if it didn't
- Often accompanied by a `success` boolean flag

### 7. Server not staying alive
- Must use `server.wait_for_termination()` or equivalent blocking call
- Launch as background process with proper working directory (`cd /app`)

### 8. Generated code not found
- Ensure `protoc` is run from the directory containing the .proto file
- Use `-I.` to set the import path
- Check that generated files exist before importing

### 9. Silent port binding failure (`add_insecure_port` returns 0)
- `server.add_insecure_port('[::]:PORT')` returns the bound port number on success, but returns **0** (not an exception!) if the port is already in use or otherwise unavailable
- The server then calls `start()` successfully and `wait_for_termination()` blocks forever — but it is serving nothing
- Meanwhile, a stale server from a previous run may still be listening on the same port, causing RPCs to return `UNIMPLEMENTED` / "Method not found!"
- **Fix**: Always capture and check the return value: `port = server.add_insecure_port(...); if port == 0: raise RuntimeError(...)`
- **Symptom**: `channel_ready_future` succeeds (something is listening!) but RPC calls fail with `StatusCode.UNIMPLEMENTED` and "Method not found!"
- **Root cause diagnosis**: Check `/tmp/server.log` — if it contains no error, the server started fine but bound to nothing. The stale server is the one responding.

## Handling Variation Dimensions

### RPC API Structure Variation

- **More RPCs**: Simply add more `rpc` lines in the service block and corresponding methods in the servicer class
- **Complex messages**: Use nested messages, repeated fields, enums, maps as needed
- **Naming variations**: The service, method, and message names can be anything — always read them from the task specification
- **Multiple services**: If the task defines multiple services, implement each as a separate servicer class and register all with the server

### Stateful Service Semantics Variation

- **Different data structures**: Use dicts, lists, sets, nested dicts, or combinations as required
- **Conditional updates**: Check preconditions before modifying state
- **Multi-key operations**: Process all keys atomically under the lock
- **Aggregate reads**: Compute from current state on each call (don't cache unless task requires it)
- **Reset/clear operations**: Provide methods to clear state if specified

### Runtime Requirements Variation

- **Higher concurrency**: Increase `max_workers` in ThreadPoolExecutor
- **Startup delays**: Add `time.sleep()` after `server.start()` if tests need warmup time
- **Health checks**: Implement a simple health-check RPC if specified
- **Long-running tests**: Ensure the server process doesn't exit; use `wait_for_termination()`
- **Multiple client channels**: The server handles this automatically; just ensure thread safety

## Complete Example Template

```python
# server.py
import grpc
from concurrent import futures
import threading
import <module>_pb2
import <module>_pb2_grpc

class Server(<module>_pb2_grpc.<ServiceName>Servicer):
    def __init__(self):
        self._lock = threading.Lock()
        # State initialization based on task requirements
        self._data = {}

    # Implement each RPC method as specified
    def <Method1>(self, request, context):
        with self._lock:
            # Business logic here
            return <module>_pb2.<Response1>(...)

    def <Method2>(self, request, context):
        with self._lock:
            return <module>_pb2.<Response2>(...)

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    <module>_pb2_grpc.add_<ServiceName>Servicer_to_server(Server(), server)
    port = server.add_insecure_port('[::]:<port>')
    if port == 0:
        raise RuntimeError('Failed to bind to port <port> — is another server already running?')
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()
```

## Execution Checklist

1. [ ] Install grpcio and grpcio-tools (pinned versions)
2. [ ] Write .proto file with correct service, RPCs, messages, and field numbers
3. [ ] Generate Python bindings with protoc
4. [ ] Verify generated files exist with correct names (hyphens → underscores)
5. [ ] Implement servicer class inheriting from generated base class
6. [ ] Implement all RPC methods with correct state semantics
7. [ ] Add thread safety (Lock) around all state access
8. [ ] Write server launch code with correct port and worker count
9. [ ] Add `if port == 0: raise RuntimeError(...)` check after `add_insecure_port`
10. [ ] Start server as background process
11. [ ] Check server.log for binding errors
12. [ ] Verify server by calling a real RPC method (not just channel_ready_future)
13. [ ] Test each RPC method with basic inputs
14. [ ] Test edge cases: missing keys, empty namespaces, delete-then-fetch, overwrites
15. [ ] Verify namespace isolation if applicable
