---
name: kv-store-grpc
description: Build and run stateful Python gRPC services defined by protobuf specifications, handling varying API structures, stateful semantics, and runtime requirements.
---

# Skill: Build Stateful Python gRPC Services

## Overview

This skill covers building Python gRPC services from protobuf specifications. Tasks in this family require:

1. Installing `grpcio` and `grpcio-tools` Python packages
2. Writing `.proto` files with service and message definitions
3. Generating Python bindings (`*_pb2.py`, `*_pb2_grpc.py`)
4. Implementing service logic with **thread-safe** stateful semantics
5. Running a gRPC server with proper lifecycle management

## Core Workflow

### 1. Install Dependencies

```bash
pip install grpcio==VERSION grpcio-tools==VERSION
```

Both packages must have matching versions. The task may specify a version.

### 2. Extract Contract Checklist

Treat every literal in the instruction as a test-facing contract. Extract and verify:

- **Proto file path**: Exact path (e.g., `/app/kv-store.proto`)
- **Generated file paths**: Exact expected paths (e.g., `/app/kv_store_pb2.py`)
- **Service name**: Exact service name in proto
- **RPC methods**: Exact method names, request/response type names
- **Message fields**: Exact field names, field numbers, and types
- **Class name**: Exact class name (e.g., `class Server`)
- **Port**: Exact port number

**Rule**: Re-verify against this checklist before finishing. Naming variations exist to catch hardcoded assumptions.

### 3. Analyze the Specification

Parse the task instruction to extract:

- **Proto file path**: Usually specified (e.g., `/app/service.proto`)
- **Service name**: The gRPC service to implement
- **RPC methods**: Names, request types, response types
- **Message fields**: Field numbers, types, names
- **Port**: The port the server must listen on
- **State semantics**: How data persists and behaves across calls

Common protobuf scalar types:
- `string` - UTF-8 text
- `int32`, `int64` - Signed integers
- `uint32`, `uint64` - Unsigned integers
- `bool` - Boolean
- `float`, `double` - Floating point

### 4. Write the Proto File

Structure:

```protobuf
syntax = "proto3";

service ServiceName {
  rpc MethodName(RequestType) returns (ResponseType);
  // ... more methods
}

message RequestType {
  string field1 = 1;
  int32 field2 = 2;
  // ... more fields
}

message ResponseType {
  // fields...
}
```

**Key rules**:
- Field numbers must match the specification exactly
- Field types must match the specification
- Request/response message names are arbitrary but should be descriptive
- Message field names should match the specification's field names
- Comments use `//` (not `#` which is invalid in protobuf)

### 5. Generate Python Bindings

```bash
cd /app
python -m grpc_tools.protoc --python_out=. --grpc_python_out=. -I. filename.proto
```

This generates:
- `filename_pb2.py` - Message classes
- `filename_pb2_grpc.py` - Servicer and stub classes

Import note: The import name in Python is `filename_pb2` where dashes and dots become underscores (`my.service.proto` → `my_service_pb2`).

**Version check**: Both generated files enforce runtime versions at import. Keep `grpcio == grpcio-tools` and **regenerate** if versions drift—never patch generated files.

### 6. Implement the Service (Thread-Safe)

**CRITICAL**: The `grpc.server` uses `ThreadPoolExecutor`, so handlers interleave freely. Wrap **all** state interaction in a `threading.Lock`.

**CRITICAL**: Disable `SO_REUSEPORT` to prevent silent split-brain. On Linux, gRPC enables `SO_REUSEPORT` by default, allowing multiple processes to bind the same port. This causes state to randomly appear/vanish depending on which process handles each connection.

Template:

```python
import grpc
from concurrent import futures
import threading
import os
import pathlib
import filename_pb2
import filename_pb2_grpc


class ServicerName(filename_pb2_grpc.ServiceNameServicer):
    def __init__(self):
        self._store = {}
        self._lock = threading.Lock()
    
    def MethodName(self, request, context):
        with self._lock:
            # All state reads and writes here
            # Never iterate a dict or do check-then-act outside the lock
            pass


def serve(port=5328):
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=10),
        options=(('grpc.so_reuseport', 0),),  # CRITICAL: prevent split-brain
    )
    filename_pb2_grpc.add_ServiceNameServicer_to_server(ServicerName(), server)
    
    # [::] is dual-stack (serves both IPv4 and IPv6)
    bound = server.add_insecure_port(f'[::]:{port}')
    if bound == 0:
        raise RuntimeError(f"Failed to bind to port {port}")
    
    # Write pidfile AFTER successful bind - this is the REAL server PID
    pathlib.Path('/tmp/server.pid').write_text(f'{os.getpid()}\n')
    
    print(f"Server started on port {bound}", flush=True)
    server.start()
    server.wait_for_termination()


if __name__ == '__main__':
    serve()
```

**Lock discipline**:
- Wrap each handler's entire state interaction in one `threading.Lock`
- Never iterate a dict, or do check-then-act / read-modify-write, outside the lock
- Never do blocking I/O or call back into gRPC while holding the lock

**SO_REUSEPORT discipline**:
- Always disable `SO_REUSEPORT` with `options=(('grpc.so_reuseport', 0),)`
- Check `add_insecure_port` return value (0 = failure)
- Write pidfile **after** successful bind (not before)

### 7. State Management Patterns

**Choose the pattern based on the task's state semantics:**

#### Pattern A: Simple Key-Value (no namespaces)
```python
def __init__(self):
    self._store = {}  # key -> value

def Put(self, request, context):
    with self._lock:
        self._store[request.key] = request.value
        return PutResponse(value=request.value)

def Get(self, request, context):
    with self._lock:
        value = self._store.get(request.key, DEFAULT)
        return GetResponse(value=value)
```

#### Pattern B: Namespace-Isolated (v01 style)
```python
def __init__(self):
    self._store = {}  # namespace -> key -> value

def Put(self, request, context):
    with self._lock:
        ns = self._store.setdefault(request.namespace, {})
        ns[request.key] = request.value
        return PutResponse(value=request.value)

def Get(self, request, context):
    with self._lock:
        value = self._store.get(request.namespace, {}).get(request.key, DEFAULT)
        return GetResponse(value=value)
```

#### Pattern C: Multi-Collection
```python
def __init__(self):
    self._store = {}  # collection -> namespace -> key -> value
    # or: self._stores = {} for different data types
```

#### Pattern D: Conditional Operations (check-then-act)
```python
def ConditionalUpdate(self, request, context):
    with self._lock:
        # Entire check-then-act must be atomic
        current = self._store.get(request.key)
        if current is None:
            return Response(success=False)
        if current != request.expected_value:
            return Response(success=False, current_value=current)
        self._store[request.key] = request.new_value
        return Response(success=True, previous_value=current)
```

#### Pattern E: Multi-Key Operations
```python
def BatchPut(self, request, context):
    with self._lock:
        results = []
        for item in request.items:
            self._store[item.key] = item.value
            results.append(item.value)
        return BatchPutResponse(values=results)

def BatchGet(self, request, context):
    with self._lock:
        values = [self._store.get(k, DEFAULT) for k in request.keys]
        return BatchGetResponse(values=values)
```

#### Pattern F: Aggregate Operations
```python
def SumNamespace(self, request, context):
    with self._lock:
        # Safe: sum() iterates while lock is held
        ns = self._store.get(request.namespace, {})
        total = sum(ns.values())
        return SumResponse(total=total)

def CountKeys(self, request, context):
    with self._lock:
        count = len(self._store.get(request.namespace, {}))
        return CountResponse(count=count)
```

#### Pattern G: Read-Modify-Write (Increment/Decrement)
```python
def Increment(self, request, context):
    """Atomically increment a value. CRITICAL: Must be under lock."""
    with self._lock:
        current = self._store.get(request.key, 0)
        new_value = current + request.delta
        self._store[request.key] = new_value
        return IncrementResponse(value=new_value)
```

### 8. Launch, Restart, and Verify Server

**Port binding failures mean "port busy", not "address family unsupported"**. `[::]` is dual-stack and preferred; if bind fails, a process holds the port.

#### Correct Launch (avoid subshell pitfalls)

```bash
# CORRECT: cd first, then background only the leaf command
# $! will be the python process (nohup execs into it)
cd /app
nohup python3 server.py > /app/server.log 2>&1 &
echo $! > /tmp/server.pid

# Wait for log evidence of successful start
sleep 1
tail /app/server.log
```

**WRONG** (captures subshell PID, not server):
```bash
# BAD: && has lower precedence than &, backgrounds entire list in subshell
cd /app && nohup python3 server.py > log 2>&1 &  # $! is subshell, not python
```

#### Robust Restart Protocol (minimal containers)

```bash
PORT=5328
HEX=$(printf '%04X' $PORT)

# Step 1: Kill by pidfile
kill "$(cat /tmp/server.pid 2>/dev/null)" 2>/dev/null

# Step 2: Poll for port to be free (check for LISTEN state 0A)
for i in $(seq 1 50); do
    if ! grep -qiE "[0-9A-F]{8}:$HEX .* 0A" /proc/net/tcp /proc/net/tcp6 2>/dev/null; then
        break
    fi
    sleep 0.2
done

# Step 3: If still busy, find REAL owner via socket inode -> pid
INO=$(awk -v h=":$HEX" '$4=="0A" && $2 ~ h"$" {print $10; exit}' /proc/net/tcp /proc/net/tcp6 2>/dev/null)
if [ -n "$INO" ]; then
    for p in /proc/[0-9]*/fd; do
        if ls -l "$p" 2>/dev/null | grep -q "socket:\[$INO\]"; then
            REAL_PID="${p%/fd}"
            echo "Killing actual port holder: $REAL_PID"
            kill -9 "$REAL_PID" 2>/dev/null
        fi
    done
fi

# Step 4: Launch and verify via log (not PID liveness)
cd /app
nohup python3 server.py > /app/server.log 2>&1 &
sleep 1
if ! grep -q "Server started on port" /app/server.log; then
    echo "Server failed to start. Check /app/server.log:"
    tail /app/server.log
    exit 1
fi
echo "Server started successfully"
```

**Why PID liveness is unreliable**: `$!` may capture a subshell wrapper; a process can be alive but not serving (failed bind after fork); a different process may hold the port. Check the **log evidence** and **channel_ready_future**.

**Wait for readiness (not fixed sleep):**

```python
import grpc

channel = grpc.insecure_channel('localhost:5328')
grpc.channel_ready_future(channel).result(timeout=10)  # raises on timeout
```

**Kill when needed:**

```bash
kill $(cat /tmp/server.pid)
```

**CRITICAL: Kill-by-name is dangerous** - never `pkill python` or `kill $(ps aux | grep python)`. In test harnesses, the tool wrapper itself may be Python. Always use pidfile or port-ownership resolution.

### 9. Pristine-State Delivery Protocol

Follow this exact order to ensure the delivered server is fresh:

1. **Run ALL mutating verification** (basic ops, concurrency burst, split-brain probe) on a temporary server.

2. **Kill the verification server** (use pidfile + port-owner fallback); poll until port is free.

3. **Start the FINAL server** on the required port; confirm via log line + `channel_ready_future`.

4. **Read-only sanity check only** (e.g., `Fetch` of missing key expecting 0 - doubles as empty-store proof).

5. **Stop. Do not mutate the delivered server.**

State is per-process: all client channels share it, and a restart wipes it. The deliverable is exactly one long-lived process on the required port with pristine (empty) state.

## Verification Recipe

Run these tests to verify correctness:

```python
import grpc
import threading
import kv_store_pb2 as pb
import kv_store_pb2_grpc as pbg

# (a) Cross-channel consistency / split-brain probe
# Fresh channel per write; all writes should be visible
for i in range(20):
    ch = grpc.insecure_channel('localhost:5328')
    stub = pbg.KVStoreStub(ch)
    stub.Put(pb.PutRequest(namespace='probe', key=f'k{i}', value=1))
ch = grpc.insecure_channel('localhost:5328')
total = pbg.KVStoreStub(ch).ListNamespaceTotal(
    pb.ListNamespaceTotalRequest(namespace='probe')).total
assert total == 20, f"split-brain or lost writes: got {total}, expected 20"
print("Split-brain test passed")

# (b) Concurrency burst: proves the lock covers read-modify-write paths
def worker(n):
    stub = pbg.KVStoreStub(grpc.insecure_channel('localhost:5328'))
    for i in range(50):
        stub.Put(pb.PutRequest(namespace='burst', key=f'{n}-{i}', value=1))
ts = [threading.Thread(target=worker, args=(n,)) for n in range(10)]
[t.start() for t in ts]
[t.join() for t in ts]
total = pbg.KVStoreStub(grpc.insecure_channel('localhost:5328')).ListNamespaceTotal(
    pb.ListNamespaceTotalRequest(namespace='burst')).total
assert total == 500, f"lost updates: got {total}, expected 500"
print("Concurrency test passed")

# (c) Atomic increment test (if Increment RPC exists)
# Verifies read-modify-write is atomic under the lock
def increment_worker():
    stub = pbg.KVStoreStub(grpc.insecure_channel('localhost:5328'))
    for _ in range(100):
        stub.Increment(pb.IncrementRequest(key='counter', delta=1))
# Run 10 workers concurrently
# After join: assert stub.Get(pb.GetRequest(key='counter')).value == 1000

# CRITICAL: Restart server after verification to ensure pristine state
# kill $(cat /tmp/server.pid)
# Then restart on required port
```

Test (a) detects split-brain: if `SO_REUSEPORT` is enabled and two servers share the port, writes scatter and total < 20.

Test (b) detects missing locks: without proper locking, concurrent writes may be lost.

Test (c) detects non-atomic read-modify-write: if the lock doesn't cover the full read-modify-write cycle, increments will be lost.

## Concurrency Failure Modes

Without proper locking, these crash or lose data under concurrent load:

| Operation | Race Condition | Failure |
|-----------|--------------|---------|
| `sum(dict.values())` | Concurrent `Put`/`Delete` mutates dict mid-iteration | `RuntimeError: dictionary changed size during iteration` → `StatusCode.UNKNOWN` |
| Check-then-act (e.g., `Delete`) | Two threads both pass membership check | `KeyError` on second `del`, or both return `success=true` |
| Read-modify-write (e.g., `Increment`) | Two threads read same value | Lost updates: final value < expected |

**Solution**: One global lock, tiny critical sections. Cost is negligible at this scale.

## Protobuf Advanced Types

### Repeated Fields (lists)

```protobuf
message BatchRequest {
  repeated Entry entries = 1;  // repeated message
  repeated string keys = 2;   // repeated scalar
}
```

Python for **repeated messages**:
```python
# Reading: read-only sequence
for entry in request.entries:
    print(entry.key)

# Mutating: use add() or extend()
entry = request.entries.add()
entry.key = "k"
entry.value = 1

# In response constructor: pass list
return BatchResponse(entries=[Entry(key="k", value=1)])
```

Python for **repeated scalars** (`string`, `int32`, etc.):
```python
# Use append(), not add()
request.keys.append("k")
request.keys.extend(["a", "b", "c"])

# Response constructor
return BatchResponse(keys=["a", "b"])
```

### Map Fields (dicts)

```protobuf
message Config {
  map<string, int32> settings = 1;
}
```

Python:
```python
# Acts like a dict
value = request.settings["key"]
for k, v in request.settings.items():
    pass

# Mutate directly
request.settings["new_key"] = 42
```

### Nested Messages

```protobuf
message Outer {
  Inner child = 1;
}
```

Python:
```python
# Access nested fields (auto-materializes on mutation)
request.child.field_name = "value"  # works even if child not yet set

# Set whole message: use CopyFrom
response.child.CopyFrom(Inner(field_name="value"))
# NOT: response.child = Inner(...)  # raises "Assignment not allowed"

# Check presence (singular message fields have presence in proto3)
if response.HasField('child'):
    response.ClearField('child')
```

### Enums

**Top-level enum:**
```protobuf
enum Status {
  UNSPECIFIED = 0;  // proto3: first value MUST be 0
  ACTIVE = 1;
}
```

Python:
```python
# Module-level constants
if request.status == pb.ACTIVE:
    pass
name = pb.Status.Name(request.status)  # "ACTIVE"
```

**Nested inside message:**
```protobuf
message MyMessage {
  enum Status { UNSPECIFIED = 0; ACTIVE = 1; }
  Status status = 1;
}
```

Python:
```python
# Message-level constants
if request.status == pb.MyMessage.ACTIVE:
    pass
name = pb.MyMessage.Status.Name(request.status)  # "ACTIVE"
```

## Common State Semantics

### Key-Value Operations

| Operation | Behavior |
|-----------|----------|
| Put/Set | Store value, return stored value or ack |
| Get/Fetch | Return value or default if missing |
| Delete | Remove key, return success+old value or false+default if missing |
| List/Scan | Return keys/values matching pattern |
| Aggregate | Sum, count, etc. over a namespace |

### Namespace Isolation

When namespaces are required:
- Each namespace is an independent key space
- Operations in one namespace don't affect others
- Missing/empty namespaces return appropriate defaults

### Default Values

Common defaults for missing keys:
- Integer: 0
- String: "" (empty string)
- Bool: false
- Custom: specified in task

## Handling Variations

### Varying RPC Methods

More methods simply require implementing more methods in the servicer class. Each method follows the same pattern: acquire lock, operate on state, release lock.

### Varying Message Fields

Access fields by the names defined in the proto:

```python
# For: message MyRequest { string name = 1; int32 count = 2; }
request.name   # string
request.count  # int32
```

### Varying State Complexity

Scale the state structure to match requirements:

- Simple: `self._store = {}` (key -> value)
- Namespaced: `self._store = {}` (namespace -> key -> value)
- Multi-collection: `self._store = {}` (collection -> namespace -> key -> value)

### Varying Default Values

Read the task specification for defaults. Common patterns:
- Missing key returns 0 for integers
- Missing key returns empty string for strings
- Missing key returns false for booleans

## Common Issues

1. **Import errors**: Use underscores for dashes in imports (`kv-store.proto` → `kv_store_pb2`)
2. **Port already in use**: Previous server still running; use robust restart protocol (pidfile + inode→PID fallback)
3. **Method not implemented**: Must implement all methods declared in proto
4. **State not persisting**: Store must be in `__init__`, not module-level
5. **Wrong field numbers**: Must match proto specification exactly
6. **Concurrent access crashes**: Add `threading.Lock` around all state operations
7. **Dictionary changed size during iteration**: Always iterate under the lock, or snapshot: `list(d.values())`
8. **Lost updates on increments**: Read-modify-write must be atomic under the lock
9. **Port bind failure**: Check return value of `add_insecure_port` (0 = failure); "port busy" means a process holds it
10. **Server not ready**: Use `channel_ready_future`, not fixed sleep; PID liveness ≠ port serving
11. **State randomly vanishing across channels**: Two server processes on same port (split-brain). Disable `SO_REUSEPORT` and kill stale server.
12. **Wrong PID in pidfile**: Server must write its own pidfile AFTER bind; shell `$!` may capture subshell

## Example: Namespaced Integer Store (v01)

Complete implementation with:
- 4 RPC methods (Put, Fetch, Delete, ListNamespaceTotal)
- Namespace-isolated integer storage with `threading.Lock`
- Port 5328 with bind checking
- Self-written pidfile (correct PID)
- Proper default values (0 for missing keys)
- Race-condition-safe operations
- `SO_REUSEPORT` disabled to prevent split-brain

```python
import grpc
from concurrent import futures
import threading
import os
import pathlib
import kv_store_pb2
import kv_store_pb2_grpc


class Server(kv_store_pb2_grpc.KVStoreServicer):
    def __init__(self):
        self._store = {}  # namespace -> key -> value
        self._lock = threading.Lock()
    
    def Put(self, request, context):
        with self._lock:
            ns = self._store.setdefault(request.namespace, {})
            ns[request.key] = request.value
            return kv_store_pb2.PutResponse(value=request.value)
    
    def Fetch(self, request, context):
        with self._lock:
            value = self._store.get(request.namespace, {}).get(request.key, 0)
            return kv_store_pb2.FetchResponse(value=value)
    
    def Delete(self, request, context):
        with self._lock:
            ns = self._store.get(request.namespace)
            if ns is None or request.key not in ns:
                return kv_store_pb2.DeleteResponse(success=False, value=0)
            value = ns.pop(request.key)  # atomic check+remove
            return kv_store_pb2.DeleteResponse(success=True, value=value)
    
    def ListNamespaceTotal(self, request, context):
        with self._lock:
            total = sum(self._store.get(request.namespace, {}).values())
        return kv_store_pb2.ListNamespaceTotalResponse(total=total)


def serve(port=5328):
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=10),
        options=(('grpc.so_reuseport', 0),),  # prevent split-brain
    )
    kv_store_pb2_grpc.add_KVStoreServicer_to_server(Server(), server)
    
    # [::] is dual-stack (IPv4 and IPv6)
    bound = server.add_insecure_port(f'[::]:{port}')
    if bound == 0:
        raise RuntimeError(f"Failed to bind to port {port}")
    
    # Write pidfile AFTER successful bind - this is the REAL server PID
    pathlib.Path('/tmp/server.pid').write_text(f'{os.getpid()}\n')
    
    print(f"Server started on port {bound}", flush=True)
    server.start()
    server.wait_for_termination()


if __name__ == '__main__':
    serve()
```
